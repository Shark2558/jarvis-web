# tests/test_r6_seams.py
"""R6 I0 seams: the shared hooks the four R6 workstreams build on (docs/plans/r6-build-book.md,
"Seams the I0 adds" items 1-10).

The two keyring purposes (`book_index`, `book_session`), the two passkey purposes (`book_open`,
`book_resume` bound to exactly one guest lock id), the three book alert kinds (important: ring in
waking hours even when only urgent things ring, held in quiet hours), the four Book settings.
The console half (assets in order, `/book/show` with the console's CSP) and the D11 import
boundary of `jarvis.buildbook` are further down.
"""

from __future__ import annotations

import ast
import fnmatch
import hashlib
import io
import json
import re
import subprocess
import tomllib
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from typing import get_args

import pytest
from pydantic import ValidationError

from jarvis.alerts import AlertKind
from jarvis.buildbook import lines, model, ports
from jarvis.config import Settings
from jarvis.integrations.vault import VaultError
from jarvis.keyring import PURPOSES, Keyring
from jarvis.notify.models import NotifySettings
from jarvis.notify.policy import DAYTIME_RING_KINDS, decide
from jarvis.notify.ports import DEFAULT_URGENCY, Signal
from jarvis.permissions.groups import PermissionRejected
from jarvis.permissions.models import (
    BOOK_LOCK_TARGET,
    TARGETED_PURPOSES,
    ChallengeRequest,
    Purpose,
)
from jarvis.permissions.service import purpose_binding
from jarvis.tools.audit import AuditLog

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "src/jarvis/api/static"
KEY = bytes(range(1, 33))
UID = "u_owner"
LOCK = "bl_0123456789ab"
BOOK_KINDS = ("book_sealed", "book_seal_failed", "book_session_closed")
NOON_IST = datetime(2026, 11, 10, 6, 30, tzinfo=UTC)  # 12:00 in Asia/Kolkata
TWO_AM_IST = datetime(2026, 11, 9, 20, 30, tzinfo=UTC)  # 02:00 in Asia/Kolkata


# ---- 1 keyring purposes ------------------------------------------------------------------------
def test_the_book_index_and_session_purposes_have_their_own_keys() -> None:
    assert {"book_index", "book_session"} <= set(PURPOSES)
    ring = Keyring(KEY)
    aad = f"book/index/{UID}/v1"
    blob = ring.cipher("book_index").encrypt(b"releases", aad=aad)
    assert ring.cipher("book_index").decrypt(blob, aad=aad) == b"releases"
    for other in ("book_session", "vault_index", "vault"):
        with pytest.raises(VaultError):
            ring.cipher(other).decrypt(blob, aad=aad)
    # D9: the session token is stored as a MAC in the book_session domain, never in clear
    tag = ring.mac("book_session", "token")
    assert tag != ring.mac("tickets", "token") and ring.mac_matches("book_session", "token", tag)


# ---- 2 passkey purposes --------------------------------------------------------------------------
def test_book_open_and_book_resume_are_targeted_passkey_purposes() -> None:
    for purpose in ("book_open", "book_resume"):
        assert purpose in get_args(Purpose) and purpose in TARGETED_PURPOSES
    req = ChallengeRequest(purpose="book_resume", target=LOCK)
    assert req.target == LOCK


def test_book_open_is_bound_to_the_owner_and_the_purpose_and_takes_no_target() -> None:
    bound = purpose_binding(UID, "book_open", None)
    assert bound == purpose_binding(UID, "book_open", "")
    assert bound != purpose_binding("u_other", "book_open", None)
    assert bound != purpose_binding(UID, "vault_unlock", None)  # a vault proof never opens it
    with pytest.raises(PermissionRejected):
        purpose_binding(UID, "book_open", LOCK)


def test_book_resume_is_bound_to_exactly_one_guest_lock() -> None:
    assert BOOK_LOCK_TARGET == r"^bl_[0-9a-f]{12}$" and re.fullmatch(BOOK_LOCK_TARGET, LOCK)
    other = "bl_ba9876543210"
    assert purpose_binding(UID, "book_resume", LOCK) != purpose_binding(UID, "book_resume", other)
    bad_targets = (
        None,
        "",
        "bl_0123456789a",
        "bl_0123456789abc",
        "BL_0123456789AB",
        "bl_0123456789aG",
        "h_01234567:1",
    )
    for bad in bad_targets:
        with pytest.raises(PermissionRejected):
            purpose_binding(UID, "book_resume", bad)


def test_the_console_passkey_helper_allows_both_book_purposes() -> None:
    js = (STATIC / "console-permissions.js").read_text(encoding="utf-8")
    allow = re.search(r"if \(!\[([^\]]+)\]\.includes\(purpose\)\)", js)
    assert allow, "JarvisPasskey.prove's allow-list"
    listed = set(re.findall(r"'([a-z_]+)'", allow.group(1)))
    assert {"book_open", "book_resume"} <= listed
    assert listed <= set(TARGETED_PURPOSES)


# ---- 3 alert kinds -------------------------------------------------------------------------------
def test_three_book_kinds_join_the_alert_kinds_as_important_daytime_rings() -> None:
    kinds = get_args(AlertKind)
    assert set(BOOK_KINDS) <= set(kinds) and len(kinds) == len(set(kinds)) == 23
    for kind in BOOK_KINDS:
        assert DEFAULT_URGENCY[kind] == "important"
        assert kind in DAYTIME_RING_KINDS


@pytest.mark.parametrize("kind", BOOK_KINDS)
@pytest.mark.parametrize("ring_for", ["urgent", "important"])
def test_a_book_notice_rings_in_waking_hours(kind: str, ring_for: str) -> None:
    # the default is ring_for="urgent": an important kind outside DAYTIME_RING_KINDS stays silent
    signal = Signal(source="system", kind=kind)  # type: ignore[arg-type]
    assert decide(signal, NotifySettings(ring_for=ring_for), NOON_IST).action == "ring"  # type: ignore[arg-type]


@pytest.mark.parametrize("kind", BOOK_KINDS)
def test_a_book_notice_is_held_in_quiet_hours(kind: str) -> None:
    signal = Signal(source="system", kind=kind)  # type: ignore[arg-type]
    assert decide(signal, NotifySettings(), TWO_AM_IST).action == "hold"


def test_the_alerts_card_lists_the_book_kinds_only_with_every_other_important_kind() -> None:
    """I0 rule: a book kind joins the Alerts card's switch list only if every other important
    kind is on it. R4's vitals_critical / health_fault are not, so the book kinds are not either
    (their switch still works through PUT /v1/notify/settings)."""
    js = (STATIC / "console-alerts.js").read_text(encoding="utf-8")
    block = js[js.index("const KINDS = [") : js.index("];", js.index("const KINDS = ["))]
    listed = set(re.findall(r"\['([a-z_]+)', '", block))
    important = {k for k, v in DEFAULT_URGENCY.items() if v == "important" and k != "test"}
    if important - set(BOOK_KINDS) <= listed:
        assert set(BOOK_KINDS) <= listed
    else:
        assert not set(BOOK_KINDS) & listed


# ---- 4 settings ----------------------------------------------------------------------------------
def test_book_settings_defaults_and_bounds() -> None:
    s = Settings(_env_file=None)
    assert (s.book_session_minutes, s.book_idle_minutes) == (45, 10)
    assert (s.book_max_total_mb, s.book_talk_questions) == (60, 20)
    for field, good, bad in (
        ("book_session_minutes", (15, 120), (14, 121)),
        ("book_idle_minutes", (5, 30), (4, 31)),
        ("book_max_total_mb", (20, 200), (19, 201)),
        ("book_talk_questions", (1, 50), (0, 51)),
    ):
        for v in good:
            assert getattr(Settings(_env_file=None, **{field: v}), field) == v
        for v in bad:
            with pytest.raises(ValidationError):
                Settings(_env_file=None, **{field: v})


# ---- 6 the buildbook package: model, lines, ports ----------------------------------------------
FIXTURE = ROOT / "tests/fixtures/book"


def test_the_caps_the_parts_share() -> None:
    m = model
    assert (m.KEEP, m.CHUNK_BYTES, m.CHUNKS_PER_COMMIT) == (3, 512 * 1024, 6)
    assert (m.MAX_BOOK_BYTES, m.MAX_SOURCE_BYTES) == (2 * 1024 * 1024, 15 * 1024 * 1024)
    assert (m.MAX_LIMITATIONS, m.LIMITATION_CHARS, m.DIGEST_CHUNK_CHARS) == (80, 200, 1500)
    assert (m.DIGEST_CONTEXT_CHARS, m.QUESTION_CHARS, m.REPLY_CHARS) == (10_000, 500, 1200)
    assert (m.HISTORY_TURNS, m.TALK_MAX_TOKENS, m.ASKS_PER_MINUTE) == (8, 400, 6)
    assert (m.OPENS_PER_MINUTE, m.LEASE_S, m.SEAL_BUDGET_S, m.TICKET_S) == (5, 120, 20, 60)
    assert model.LOCK_ID == BOOK_LOCK_TARGET  # one lock id shape for the lock and the passkey


def test_the_book_has_eight_sections_and_thirteen_scenes_in_the_planned_order() -> None:
    assert model.SECTION_IDS == (
        "architecture", "stack", "libraries", "integrations",
        "workflows", "limitations", "costs", "decisions",
    )  # fmt: skip
    titles = [t for _, t in model.SCENES]
    assert titles == [
        "The build book", "Eight layers", "One conversation turn", "Memory and privacy",
        "Confirm before commit", "Voice", "Home", "On its own", "Stack and licences", "Costs",
        "Not built yet", "Questions", "Closing",
    ]  # fmt: skip
    assert model.BOOK_SCENES == 11  # 12 and 13 are lines.py's fixed lines


def _release(**over: object) -> dict[str, object]:
    sha = "3f2a1c9e5b7d4a6c8e0f1a2b3c4d5e6f7a8b9c0d"
    base: dict[str, object] = {
        "id": sha[:7],
        "sha": sha,
        "label": "R6",
        "committed_at": "2026-11-10T09:30:00+05:30",
        "book_sha256": "a" * 64,
        "source_sha256": "b" * 64,
        "source_bytes": 4_000_000,
    }
    return {**base, **over}


def test_a_release_is_consistent_or_refused() -> None:
    assert model.Release.model_validate(_release()).built
    failed = model.Release.model_validate(
        _release(book_sha256=None, source_sha256=None, source_bytes=0, error="snapshot refused")
    )
    assert not failed.built
    for bad in (
        _release(id="0000000"),  # id is sha[:7]
        _release(label="R6.1.2"),
        _release(committed_at="2026-11-10T09:30:00"),  # no offset
        _release(error="boom"),  # a failed build carries no book
        _release(source_sha256=None),  # a built one names both files
        _release(source_bytes=16 * 1024 * 1024),  # over the 15 MB cap
        _release(extra=1),
    ):
        with pytest.raises(ValidationError):
            model.Release.model_validate(bad)


def test_the_fixture_book_is_a_valid_book_and_its_release_matches_the_bytes() -> None:
    raw = (FIXTURE / "_book/book.json").read_bytes()
    book = model.Book.model_validate_json(raw)
    release = model.Release.model_validate_json((FIXTURE / "_book/release.json").read_bytes())
    assert book.release.id == release.id and release.built
    assert hashlib.sha256(raw).hexdigest() == release.book_sha256
    zipped = (FIXTURE / "_book/source.zip").read_bytes()
    assert hashlib.sha256(zipped).hexdigest() == release.source_sha256
    assert len(zipped) == release.source_bytes
    with zipfile.ZipFile(io.BytesIO(zipped)) as zf:
        names = zf.namelist()
    assert len(names) == 3 and all(n.startswith(f"JARVIS-source-{release.id}/") for n in names)
    assert names == sorted(names)
    assert [s.n for s in book.show.scenes] == list(range(1, 12))
    assert list(book.sections()) == list(model.SECTION_IDS)
    # canonical: sorted keys, NFC, rupees only
    assert raw == json.dumps(
        json.loads(raw), sort_keys=True, ensure_ascii=False, separators=(",", ":")
    ).encode("utf-8")
    assert "$" not in raw.decode("utf-8") and "₹" in raw.decode("utf-8")


def test_a_scene_must_match_its_number_and_its_beats() -> None:
    beat = {"id": "s02b01", "text": "I am built in eight layers."}
    assert model.Scene(n=2, id="layers", title="Eight layers", beats=(beat,)).id == "layers"  # type: ignore[arg-type]
    with pytest.raises(ValidationError):
        model.Scene(n=3, id="layers", title="x", beats=(beat,))  # type: ignore[arg-type]
    with pytest.raises(ValidationError):
        model.Scene(n=3, id="turn", title="x", beats=(beat,))  # type: ignore[arg-type]
    book = json.loads((FIXTURE / "_book/book.json").read_bytes())
    book["show"]["scenes"] = list(reversed(book["show"]["scenes"]))
    with pytest.raises(ValidationError):
        model.Book.model_validate(book)


def test_sealed_entries_and_sessions_never_show_a_key_or_a_token() -> None:
    sealed = model.SealedFile(
        kind="book", fid="bf_0123456789ab", size=10, sha256="c" * 64, count=1, dek="WRAPPED-DEK"
    )
    assert "WRAPPED-DEK" not in repr(sealed)
    assert "token" not in model.SessionView.model_fields
    view = model.SessionView(
        session_id="bk_0123456789abcdef",
        audience="guest",
        created_at="2026-11-10T14:02:00+05:30",
        last_seen="2026-11-10T14:03:00+05:30",
        until="2026-11-10T14:47:00+05:30",
        questions_left=20,
    )
    assert view.state == "open"
    with pytest.raises(ValidationError):
        model.SessionView(**{**view.model_dump(), "audience": "admin"})
    lock = model.GuestLock(id=LOCK, session_id=view.session_id, since=view.created_at)
    assert lock.id == LOCK


LINES = {
    "ask": "Do you have any questions about how I'm built?",
    "follow_up": "Anything else you'd like to know?",
    "refuse_data": "That belongs to my owner, and none of it is in this session. I can tell you "
    "how I'm built.",
    "refuse_action": "I can't do anything from the build book; I can explain how that feature "
    "works.",
    "refuse_meta": "I'll keep to explaining how I'm built.",
    "ai_off": "My conversational brain is off, so I can't take questions; the show still works.",
    "limit": "That's all the questions I can take in one session.",
    "credit": "Everything you've seen was designed and built by {by}. The credit is all {his}.",
    "sealed_guest": "The code is sealed in my vault, for the people my owner allows.",
    "thanks_guest": "Thank you for listening.",
    "sealed_owner": "The code is sealed in your vault, for the people you allow, {h}.",
    "thanks_owner": "Thank you, {h}.",
    "hand_back": "Please hand the device back to my owner.",
}


def test_the_fixed_lines_are_pinned_word_for_word() -> None:
    assert dict(lines.LINES) == LINES


def test_the_closing_fills_the_honorific_the_possessive_and_the_creator() -> None:
    assert lines.closing("guest", honorific="Sir", creator="Akash") == (
        "Everything you've seen was designed and built by Akash, my owner and creator. "
        "The credit is all his.",
        "The code is sealed in my vault, for the people my owner allows.",
        "Thank you for listening.",
    )
    owner = lines.closing("owner", honorific="Ma'am")
    assert owner[0].endswith("built by my owner and creator. The credit is all hers.")
    assert owner[1:] == (
        "The code is sealed in your vault, for the people you allow, Ma'am.",
        "Thank you, Ma'am.",
    )
    assert lines.possessive("Captain") == "theirs" and lines.possessive("sir") == "his"


def test_a_creator_name_cannot_inject_a_placeholder() -> None:
    said = lines.say("credit", honorific="Sir", creator="{h} {his} {by}")
    assert said.startswith("Everything you've seen was designed and built by {h} {his} {by}, my")
    assert said.endswith("The credit is all his.")


def test_each_part_has_its_port() -> None:
    for name in ("BookSource", "BookVault", "BookSessions", "ShowLock", "BookTalker", "BookAudit"):
        assert hasattr(getattr(ports, name), "_is_runtime_protocol"), name
    assert isinstance(AuditLog(), ports.BookAudit)  # the real chain fits the buildbook's view
    assert issubclass(ports.BookUnavailable, Exception)


# ---- 10 the D11 import boundary ----------------------------------------------------------------
BUILDBOOK = ROOT / "src/jarvis/buildbook"
FORBIDDEN = ("jarvis.core.brain", "jarvis.tools", "jarvis.memory", "jarvis.documents")
FORBIDDEN_PREFIX = "jarvis.integrations.google"  # google, google_tasks, ... (the owner's Google)


def _imported(source: str, module: str) -> set[str]:
    """Every module a source file imports, relative imports resolved against `module`."""
    found: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            found |= {a.name for a in node.names}
        elif isinstance(node, ast.ImportFrom):
            base = node.module or ""
            if node.level:
                parent = module.split(".")[: -node.level]
                base = ".".join([*parent, base] if base else parent)
            found.add(base)
            found |= {f"{base}.{a.name}" for a in node.names}
        elif isinstance(node, ast.Call) and getattr(node.func, "attr", "") == "import_module":
            found.add("<dynamic import>")
        elif isinstance(node, ast.Call) and getattr(node.func, "id", "") == "__import__":
            found.add("<dynamic import>")
    return found


def _forbidden(names: set[str]) -> set[str]:
    return {
        n
        for n in names
        if n == "<dynamic import>"
        or n.startswith(FORBIDDEN_PREFIX)
        or any(n == f or n.startswith(f + ".") for f in FORBIDDEN)
    }


def test_the_boundary_check_catches_every_import_form() -> None:
    for line in (
        "from jarvis.tools.audit import AuditLog",
        "import jarvis.core.brain",
        "from jarvis import tools",
        "from jarvis.integrations import google",
        "from jarvis.integrations.google_tasks import x",
        "from ...memory import SessionStore",  # relative, from jarvis.buildbook.gen.x
        "importlib.import_module('jarvis.documents')",
    ):
        assert _forbidden(_imported(line, "jarvis.buildbook.gen.x")), line
    allowed = (
        "from jarvis.llm.router import ModelRouter",
        "from jarvis.keyring import Keyring",
        "from jarvis.core.guardrails import ActionRisk",
        "from jarvis.vault.unlock import x",
    )
    for line in allowed:
        assert not _forbidden(_imported(line, "jarvis.buildbook.x")), line


def test_the_buildbook_imports_no_brain_tool_memory_document_or_google_module() -> None:
    files = sorted(BUILDBOOK.rglob("*.py"))
    assert files, "jarvis.buildbook exists"
    bad: dict[str, set[str]] = {}
    for path in files:
        # "jarvis.buildbook.gen.__init__": a level-1 relative import then names the package itself
        module = ".".join(path.relative_to(ROOT / "src").with_suffix("").parts)
        hits = _forbidden(_imported(path.read_text(encoding="utf-8"), module))
        if hits:
            bad[str(path.relative_to(ROOT))] = hits
    assert bad == {}


# ---- 10 packaging: the built book reaches the image, never git -------------------------------------
def test_the_built_book_is_git_ignored_but_the_fixtures_are_not() -> None:
    def ignored(rel: str) -> bool:
        r = subprocess.run(["git", "check-ignore", "-q", "--no-index", rel], cwd=ROOT, check=False)
        return r.returncode == 0

    for name in ("book.json", "source.zip", "release.json"):
        assert ignored(f"src/jarvis/buildbook/_book/{name}"), name
        assert not ignored(f"tests/fixtures/book/_book/{name}"), name


def test_the_built_book_and_the_generator_lists_are_package_data() -> None:
    cfg = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    globs = cfg["tool"]["setuptools"]["package-data"]["jarvis.buildbook"]
    for rel in ("_book/book.json", "_book/source.zip", "_book/release.json"):
        assert any(fnmatch.fnmatch(rel, g) for g in globs), rel
    for rel in ("gen/redact.json", "gen/fake_secrets.txt"):  # part A's lists, read when installed
        assert any(fnmatch.fnmatch(rel, g) for g in globs), rel
