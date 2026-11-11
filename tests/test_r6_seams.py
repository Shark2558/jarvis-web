# tests/test_r6_seams.py -- R6 I0 seams (docs/plans/r6-build-book.md "Seams the I0 adds"): the two
# keyring purposes, the two passkey purposes and their targets, the three book alert kinds (23 in
# all, "important", held at night and rung by day), the four Book settings, the D11 import
# boundary of `jarvis.buildbook`, the package data, and the R6 eval suite's stub parts.
# The app wiring, the console shell and the routes: tests/test_r6_wiring_seams.py and
# tests/test_r6_contract.py. The data model and the fixed lines: tests/test_r6_buildbook_model.py.
from __future__ import annotations

import ast
import json
import re
import subprocess
import sys
import tomllib
from datetime import UTC, datetime
from pathlib import Path
from typing import get_args

import pytest
from pydantic import ValidationError
from test_permissions_service import UID, Rig

from jarvis.alerts import AlertKind
from jarvis.buildbook import model
from jarvis.config import Settings
from jarvis.keyring import PURPOSES, SECRET_PURPOSES, Keyring
from jarvis.notify.held import summary
from jarvis.notify.models import NO_SWITCH, NotifySettings
from jarvis.notify.policy import DAYTIME_RING_KINDS, decide
from jarvis.notify.ports import DEFAULT_URGENCY, Signal
from jarvis.notify.telegram_out import R1_TOGGLE
from jarvis.permissions.errors import PasskeyRejected, PermissionRejected
from jarvis.permissions.models import (
    BOOK_LOCK_TARGET,
    BOOK_OPEN_TARGET,
    TARGETED_PURPOSES,
    ChallengeRequest,
    Purpose,
)
from jarvis.permissions.service import purpose_binding

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src" / "jarvis"
STATIC = SRC / "api" / "static"
KEY = bytes(range(1, 33))
BOOK_KINDS = ("book_sealed", "book_seal_failed", "book_session_closed")
NOON_IST = datetime(2026, 11, 10, 6, 30, tzinfo=UTC)  # 12:00 in Asia/Kolkata
TWO_AM_IST = datetime(2026, 11, 9, 20, 30, tzinfo=UTC)  # 02:00 in Asia/Kolkata
LOCK = "bl_0123456789ab"


# ---- 1. keyring ----------------------------------------------------------------------------------
def test_the_keyring_gains_the_two_book_purposes() -> None:
    assert {"book_index", "book_session"} <= set(PURPOSES)
    assert not {"book_index", "book_session"} & set(SECRET_PURPOSES)
    ring = Keyring(KEY)
    blob = ring.cipher("book_index").encrypt(b"[]", aad="book/index/u/v1")
    assert ring.cipher("book_index").decrypt(blob, aad="book/index/u/v1") == b"[]"
    # book_session is a cipher (the sealed turns) AND a MAC domain (the token's mac, D9)
    sealed = ring.cipher("book_session").encrypt(b"t", aad="book/session/u/bk/v1")
    assert ring.cipher("book_session").decrypt(sealed, aad="book/session/u/bk/v1") == b"t"
    tag = ring.mac("book_session", "token")
    assert ring.mac_matches("book_session", "token", tag)
    assert tag != ring.mac("tickets", "token")  # its own MAC domain


# ---- 2. passkey purposes -------------------------------------------------------------------------
@pytest.mark.parametrize("purpose", ["book_open", "book_resume"])
def test_the_book_passkey_purposes_are_targeted(purpose: str) -> None:
    assert purpose in get_args(Purpose) and purpose in TARGETED_PURPOSES


def test_the_lock_target_is_one_lock_id_and_the_model_agrees() -> None:
    assert BOOK_LOCK_TARGET == r"^bl_[0-9a-f]{12}$" == model.LOCK_ID
    assert BOOK_OPEN_TARGET == r"^(owner|guest)$"


def test_a_resume_is_bound_to_exactly_one_lock_id() -> None:
    assert purpose_binding(UID, "book_resume", LOCK) != purpose_binding(
        UID, "book_resume", "bl_ba9876543210"
    )
    for bad in (None, "", "bl_0123", "bl_0123456789AB", "bl_0123456789abc", "xl_0123456789ab"):
        with pytest.raises(PermissionRejected):
            purpose_binding(UID, "book_resume", bad)


def test_an_open_is_bound_to_its_audience() -> None:
    """D8 names no target; I0 binds the audience (owner | guest) so a passkey check made to open
    the book for the owner can't open a guest session, and the other way round."""
    owner = purpose_binding(UID, "book_open", "owner")
    assert owner != purpose_binding(UID, "book_open", "guest")
    for bad in (None, "", "Owner", "admin", "guest:1"):
        with pytest.raises(PermissionRejected):
            purpose_binding(UID, "book_open", bad)
    ChallengeRequest(purpose="book_open", target="guest")
    ChallengeRequest(purpose="book_resume", target=LOCK)
    with pytest.raises(ValidationError):
        ChallengeRequest(purpose="book_shred", target=LOCK)  # type: ignore[arg-type]


async def test_book_proofs_are_single_use_and_serve_only_their_own_purpose() -> None:
    rig = Rig()
    await rig.register()
    proof = await rig.proof("book_resume", target=LOCK)
    with pytest.raises(PasskeyRejected):  # made for one lock, used for another
        await rig.svc.check_purpose(UID, "book_resume", "bl_ba9876543210", proof)
    proof = await rig.proof("vault_unlock")
    with pytest.raises(PasskeyRejected):  # access eval: a vault_unlock proof opens no book
        await rig.svc.check_purpose(UID, "book_open", "owner", proof)
    proof = await rig.proof("book_open", target="owner")
    with pytest.raises(PasskeyRejected):  # an owner open is no guest open
        await rig.svc.check_purpose(UID, "book_open", "guest", proof)
    proof = await rig.proof("book_open", target="guest")
    note = await rig.svc.check_purpose(UID, "book_open", "guest", proof)
    assert note is not None and note.startswith("passkey ")
    with pytest.raises(PasskeyRejected):  # single use
        await rig.svc.check_purpose(UID, "book_open", "guest", proof)


def test_the_console_passkey_helper_allows_the_book_purposes() -> None:
    js = (STATIC / "console-permissions.js").read_text(encoding="utf-8")
    found = re.search(r"if \(!\[([^\]]*)\]\.includes\(purpose\)\)", js)
    assert found is not None
    allowed = set(re.findall(r"'([a-z_]+)'", found.group(1)))
    assert allowed == {
        "vault_unlock",
        "privacy_delete",
        "privacy_export",
        "home_disarm",
        "book_open",
        "book_resume",
    }


# ---- 3. alert kinds ------------------------------------------------------------------------------
def test_three_book_kinds_make_twenty_three() -> None:
    kinds = get_args(AlertKind)
    # R11 added thirteen helper kinds after them (tests/test_r11_seams.py): 36 in all
    assert set(BOOK_KINDS) <= set(kinds) and len(kinds) == len(set(kinds)) == 36
    assert set(DEFAULT_URGENCY) == set(kinds)


@pytest.mark.parametrize("kind", BOOK_KINDS)
def test_a_book_kind_is_important_rings_by_day_and_is_held_at_night(kind: str) -> None:
    assert DEFAULT_URGENCY[kind] == "important" and kind in DAYTIME_RING_KINDS
    quiet_default = NotifySettings(ring_for="urgent")  # "Only urgent things ring" (the default)
    signal = Signal(source="system", kind=kind)  # type: ignore[arg-type]
    assert decide(signal, quiet_default, NOON_IST).action == "ring"
    assert decide(signal, quiet_default, TWO_AM_IST).action == "hold"
    # an owner switch, like every non-burglar kind; R1's Telegram toggles stay R1's
    assert kind not in NO_SWITCH and kind not in R1_TOGGLE
    off = NotifySettings(kinds={kind: "off"})
    assert decide(signal, off, NOON_IST).action == "drop"


def test_held_book_alerts_are_named_in_the_morning_summary() -> None:
    items = [{"kind": k, "at": "2026-11-10T01:00:00+05:30"} for k in BOOK_KINDS]
    text = summary(items)
    for words in ("1 build book sealed", "1 build book not sealed", "1 build book session closed"):
        assert words in text, text


def test_the_alerts_card_lists_the_book_kinds() -> None:
    js = (STATIC / "console-alerts.js").read_text(encoding="utf-8")
    block = js[js.index("const KINDS = [") : js.index("];", js.index("const KINDS = ["))]
    listed = re.findall(r"\['([a-z_]+)', '", block)
    at = listed.index(BOOK_KINDS[0])  # R11's thirteen helper kinds follow them
    assert listed[at : at + 3] == list(BOOK_KINDS) and listed[at + 3] == "disaster_alert"


# ---- 4. settings ---------------------------------------------------------------------------------
BOUNDS = (
    ("book_session_minutes", 45, (15, 120)),
    ("book_idle_minutes", 10, (5, 30)),
    ("book_max_total_mb", 60, (20, 200)),
    ("book_talk_questions", 20, (1, 50)),
)


@pytest.mark.parametrize(("name", "default", "bounds"), BOUNDS)
def test_the_book_settings_have_defaults_and_bounds(
    name: str, default: int, bounds: tuple[int, int]
) -> None:
    s = Settings(_env_file=None)
    assert getattr(s, name) == default
    assert (Settings.model_fields[name].description or "").strip()
    lo, hi = bounds
    for ok in (lo, hi):
        assert getattr(Settings(_env_file=None, **{name: ok}), name) == ok
    for bad in (lo - 1, hi + 1):
        with pytest.raises(ValidationError):
            Settings(_env_file=None, **{name: bad})


def test_the_idle_limit_is_shorter_than_the_session() -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, book_session_minutes=15, book_idle_minutes=20)


# ---- 10. the D11 boundary, package data, ignore, evals -------------------------------------------
FORBIDDEN = (
    "jarvis.core.brain",
    "jarvis.tools",
    "jarvis.memory",
    "jarvis.documents",
    "jarvis.integrations.google",
)


def _imported(path: Path, base: Path) -> set[str]:
    """Every module a file imports (absolute or relative), and every dotted 'jarvis.' string it
    holds (an importlib call by name counts too). `base` is the folder holding `jarvis/`."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    pkg = path.relative_to(base).with_suffix("").parts[:-1]
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found |= {a.name for a in node.names}
        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            if node.level:
                parent = list(pkg[: len(pkg) - node.level + 1])
                mod = ".".join([*parent, mod] if mod else parent)
            found.add(mod)
            found |= {f"{mod}.{a.name}" for a in node.names}
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            if node.value.startswith("jarvis."):
                found.add(node.value)
    return found


def _boundary_breaks(
    root: Path, forbidden: tuple[str, ...], base: Path = SRC.parent
) -> list[tuple[str, str]]:
    return [
        (str(f.relative_to(base)), mod)
        for f in sorted(root.rglob("*.py"))
        for mod in _imported(f, base)
        if any(mod == bad or mod.startswith(bad) for bad in forbidden)
    ]


def test_the_buildbook_package_keeps_the_d11_boundary() -> None:
    assert (SRC / "buildbook" / "__init__.py").is_file()
    assert _boundary_breaks(SRC / "buildbook", FORBIDDEN) == []
    # the generator reads the app as text and ASTs, never imports it (D2)
    assert _boundary_breaks(SRC / "buildbook" / "gen", ("jarvis.api",)) == []


def test_the_boundary_probe_catches_every_way_in(tmp_path: Path) -> None:
    pkg = tmp_path / "jarvis" / "buildbook"
    pkg.mkdir(parents=True)
    (pkg / "probe.py").write_text(
        "import jarvis.tools.gateway\n"
        "from jarvis.integrations import google\n"
        "from ..memory import inmemory\n"
        "import importlib\nimportlib.import_module('jarvis.documents.service')\n",
        encoding="utf-8",
    )
    broken = {mod for _, mod in _boundary_breaks(pkg, FORBIDDEN, base=tmp_path)}
    assert {
        "jarvis.tools.gateway",
        "jarvis.integrations.google",
        "jarvis.memory.inmemory",
        "jarvis.documents.service",
    } <= broken


def test_the_built_book_is_ignored_by_git_and_shipped_as_package_data() -> None:
    ignored = (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert "src/jarvis/buildbook/_book/" in ignored
    cfg = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert cfg["tool"]["setuptools"]["package-data"]["jarvis.buildbook"] == ["_book/*"]


def test_the_r6_book_eval_suite_runs_every_part_built_and_gated() -> None:
    run = ROOT / "evals" / "r6_book" / "run.py"
    r = subprocess.run([sys.executable, str(run), "--mock"], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout[-2000:] + r.stderr[-2000:]
    report = json.loads((run.parent / "report.json").read_text())
    parts = {c["id"].split(":")[0] for c in report["results"]}
    assert parts == {"gen", "seal", "access", "guest", "wipe", "lock"}
    assert report["pass_rate"] == 1
    nc = report["negative_control"]
    assert nc["suite_failed"] is True and nc["parts_not_built"] == []  # every control fails
    # I1: gated in the mock run (make eval-mock, CI)
    mock = (ROOT / "evals" / "run_all_mock.py").read_text(encoding="utf-8")
    assert (
        '("r6_book (gated)", [sys.executable, str(HERE / "r6_book" / "run.py"), "--mock"], True)'
        in mock
    )
