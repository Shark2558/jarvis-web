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
from typing import Any, get_args

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


# ---- 10 packaging: the built book reaches the image, never git -----------------------------------
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


# ---- 5 the app's three slots ---------------------------------------------------------------------
def test_app_py_has_the_three_r6_slots_in_place_and_stays_within_760_lines() -> None:
    src = (ROOT / "src/jarvis/api/app.py").read_text(encoding="utf-8")
    assert len(src.splitlines()) <= 760
    lines_ = [ln.strip() for ln in src.splitlines()]
    at = {key: next(i for i, ln in enumerate(lines_) if ln.startswith(key)) for key in (
        "await wire_r4(", "await wire_r6(", "install_show_lock(app, s)",
        "_install_google_sign_in(app, s)", "install_r6_routes(app)",
        "app.include_router(console_router)", "if s.auth_mode is AuthMode.GOOGLE:",
    )}  # fmt: skip
    assert at["await wire_r6("] == at["await wire_r4("] + 1
    assert at["install_show_lock(app, s)"] == at["_install_google_sign_in(app, s)"] - 1
    assert at["install_show_lock(app, s)"] == at["if s.auth_mode is AuthMode.GOOGLE:"] + 1
    assert at["install_r6_routes(app)"] == at["app.include_router(console_router)"] - 1
    # the extraction (item 5): the slice 10-12 wiring lives in api/feature_wiring.py now
    assert "def _wire_features" not in src and "def _wire_slice12" not in src
    for pinned, limit in (("tools/gateway.py", 760), ("core/brain.py", 799)):
        assert len((ROOT / "src/jarvis" / pinned).read_text().splitlines()) <= limit, pinned


async def test_wire_r6_leaves_every_r6_part_off_until_i1(client: Any) -> None:
    from jarvis.api.r6_wiring import R6_STATE

    app = client._transport.app
    assert R6_STATE == (
        "book_source", "book_vault", "book_sealer", "book_sessions",
        "book_lock", "book_talk", "book_service",
    )  # fmt: skip
    for attr in R6_STATE:
        assert getattr(app.state, attr) is None, attr


# ---- 9 the console shell: the Book panel, the 423 hop, /book/show --------------------------------
# Part D's files, as I0 stubs (empty headers): the panel's two scripts and stylesheet in the
# console; the show's scripts in book.html in this order, then its 3D entry module (which imports
# the scene modules itself, as console-3d.js imports console-3d-scenes.js).
PANEL_SCRIPTS = ("console-book.js", "console-book-reader.js")
SHOW_SCRIPTS = (
    "console-fx.js",
    "console-permissions.js",
    "console-book-voice.js",
    "console-book-2d.js",
    "console-book-show.js",
    "console-book-talk.js",
)
SHOW_MODULE = "console-book-3d.js"
SCENE_MODULES = (
    "console-book-scenes.js",
    "console-book-scenes-flow.js",
    "console-book-scenes-data.js",
)
D_STUBS = (
    *PANEL_SCRIPTS,
    "console-book.css",
    *SHOW_SCRIPTS[2:],
    SHOW_MODULE,
    *SCENE_MODULES,
    "book.css",
)


def _html(name: str) -> str:
    return (STATIC / name).read_text(encoding="utf-8")


def _css_classes() -> set[str]:
    found: set[str] = set()
    for path in STATIC.glob("*.css"):
        css = re.sub(r"/\*.*?\*/", "", path.read_text(encoding="utf-8"), flags=re.S)
        found |= set(re.findall(r"\.([A-Za-z_][\w-]*)", css))
    return found


@pytest.mark.parametrize("name", D_STUBS)
def test_each_part_d_file_exists_is_served_and_names_the_plan(name: str) -> None:
    from jarvis.api.console import APP_ASSETS

    text = _html(name)
    assert name in APP_ASSETS
    assert ("css" if name.endswith(".css") else "javascript") in APP_ASSETS[name]
    assert "r6-build-book.md" in text.splitlines()[0] + text.splitlines()[1]
    limit = 300 if name.endswith(".css") else 400
    assert len(text.splitlines()) <= limit and text.isascii()


def test_the_book_dock_button_and_more_sheet_item_sit_after_people() -> None:
    html = _html("console.html")
    dock = html[html.index('<nav class="dock card"') : html.index("</nav>")]
    tabs = re.findall(r'<button class="dk([^"]*)" type="button" data-open="(\w+)"', dock)
    names = [n for _, n in tabs]
    assert names[names.index("people") + 1] == "book"
    cls = dict((n, c) for c, n in tabs)["book"]
    assert cls.split() == ["ovf"]  # a phone shows it behind More
    assert 'data-open="book" aria-controls="p-book" aria-pressed="false"' in dock
    assert "<span>Book</span>" in dock[dock.index('data-open="book"') :]
    sheet = re.findall(r'data-sheet-open="(\w+)"', html)
    assert sheet[sheet.index("people") + 1] == "book"


def test_the_book_panel_is_an_empty_shell_in_existing_classes_only() -> None:
    html = _html("console.html")
    start = html.index('<section class="panel card" id="p-book"')
    panel = html[start : html.index("</section>", start)]
    assert 'data-panel="book" aria-labelledby="t-book" hidden' in panel
    assert '<h2 id="t-book">Book</h2>' in panel and 'id="bookBody"' in panel
    used = {c for attr in re.findall(r'class="([^"]+)"', panel) for c in attr.split()}
    assert used - _css_classes() == set()  # no new class: never change the aesthetics
    assert "style=" not in panel and "<script" not in panel
    for needed in ("rhead", "k", "kv", "bnote"):
        assert needed in used, needed


def test_the_console_loads_the_panel_files_after_the_r5_1_ones() -> None:
    html = _html("console.html")
    tags = re.findall(r'<script src="/static/([^"]+)" defer></script>', html)
    at = tags.index("console-people.js")
    assert tuple(tags[at + 1 : at + 3]) == PANEL_SCRIPTS
    links = re.findall(r'<link rel="stylesheet" href="/static/([^"]+)">', html)
    assert links[-1] == "console-book.css" and links[-2] == "console-systems.css"


def test_book_is_in_the_deck_order_and_has_a_default_place() -> None:
    js = _html("console-deck.js")
    order = re.search(r"const ORDER = \[([^\]]+)\];", js)
    assert order
    ids = re.findall(r"'([a-z]+)'", order.group(1))
    assert ids[ids.index("people") + 1] == "book"
    assert re.search(r"\bbook: \{ x:", js)


def test_a_423_from_the_server_takes_the_console_to_the_show() -> None:
    js = _html("console.js")
    assert js.count("r.status === 423") == 3  # api(), raw() and the sign-in check (/auth/me)
    assert "location.replace(SHOW_PAGE)" in js and "const SHOW_PAGE = '/book/show';" in js


async def test_the_show_page_has_the_console_csp_and_loads_the_planned_assets(client: Any) -> None:
    from jarvis.api.console import CONSOLE_CSP

    r = await client.get("/book/show")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/html")
    assert r.headers["content-security-policy"] == CONSOLE_CSP
    for header, value in (
        ("cache-control", "no-store"),
        ("x-content-type-options", "nosniff"),
        ("x-frame-options", "DENY"),
        ("referrer-policy", "no-referrer"),
    ):
        assert r.headers[header] == value, header
    html = r.text
    tags = re.findall(r"<script\b[^>]*>", html)
    assert all('src="/static/' in t for t in tags)  # no inline script (the CSP forbids it)
    classic = re.findall(r'<script src="/static/([^"]+)" defer></script>', html)
    assert tuple(classic) == SHOW_SCRIPTS
    assert re.findall(r'<script type="module" src="/static/([^"]+)"></script>', html) == [
        SHOW_MODULE
    ]
    assert html.index(f"/static/{SHOW_SCRIPTS[-1]}") < html.index(f"/static/{SHOW_MODULE}")
    links = re.findall(r'<link rel="stylesheet" href="/static/([^"]+)">', html)
    assert links == ["console.css", "console-deck.css", "book.css"]
    assert "https://" not in html and "http://" not in html
    for deck_only in ('id="dock"', 'id="p-chat"', "/static/console.js", "/static/console-deck.js"):
        assert deck_only not in html  # it boots without the deck


# ---- 10 the mock eval skeleton -------------------------------------------------------------------
R6_EVALS = ROOT / "evals/r6_book/run.py"
PART_SUITES = ("gen", "seal", "access", "guest", "wipe", "lock")


def test_the_r6_book_eval_runner_waits_for_the_part_suites() -> None:
    import sys

    present = [n for n in PART_SUITES if (R6_EVALS.parent / f"{n}.py").is_file()]
    r = subprocess.run(
        [sys.executable, str(R6_EVALS), "--mock"], capture_output=True, text=True, check=False
    )
    assert r.returncode == 0, r.stdout + r.stderr
    for name in PART_SUITES:
        if name not in present:
            assert f"{name}: not built yet" in r.stdout
    strict = subprocess.run(
        [sys.executable, str(R6_EVALS), "--mock", "--require-all"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert strict.returncode == (0 if len(present) == len(PART_SUITES) else 1), strict.stdout


def test_the_r6_book_suite_is_gated_in_the_mock_run() -> None:
    src = (ROOT / "evals/run_all_mock.py").read_text(encoding="utf-8")
    line = next(ln for ln in src.splitlines() if '"r6_book (gated)"' in ln)
    assert 'HERE / "r6_book" / "run.py"' in line and line.rstrip().endswith("True),")


def test_the_r6_python_modules_keep_the_house_size_limits() -> None:
    files = [
        *sorted((ROOT / "src/jarvis/buildbook").rglob("*.py")),
        *(ROOT / "src/jarvis/api" / n for n in ("book.py", "book_show.py", "book_http.py")),
        ROOT / "src/jarvis/api/r6_wiring.py",
        ROOT / "src/jarvis/api/feature_wiring.py",
    ]
    for path in files:
        source = path.read_text(encoding="utf-8")
        assert len(source.splitlines()) <= 400, path.name
        for node in ast.walk(ast.parse(source)):
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                assert (node.end_lineno or 0) - node.lineno < 50, (path.name, node.name)
