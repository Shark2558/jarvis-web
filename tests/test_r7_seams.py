# tests/test_r7_seams.py -- R7 I0 seams (docs/plans/r7-mobile.md "The I0 seams", 1-27): the
# version and the build book's release name, layers and the snapshot's binary list, the settings,
# five alert kinds and the two delivery lists, three permission rows, three key purposes, the
# parts' contract and wiring (stub parts and routes, the door's handler registry, the app lock's
# slot, the body caps), the phone's signed request and its shared vectors, the console (the More
# sheet built by the dock, the Camera tab, the manifest link, one loader), the CSP and the vision
# route, the Helpers "Watch" tab, the voice phrases, the five 423 readers, the Telegram hook, the
# Android CI's first version, the guide's cards, the eval runner, the persona left alone, the
# private patterns, the brief's sleep line, the licences, the picture send door and the passkey
# purposes.
from __future__ import annotations

import hashlib
import importlib
import json
import re
import subprocess
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, get_args

import pytest
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from pydantic import ValidationError
from r7_fakes import FakeDoor, load_vectors, phone_key, sign_request

import jarvis
import jarvis.api.r7_wiring as wiring
from jarvis import keyring
from jarvis.alerts import R7_ALERT_KINDS, AlertKind
from jarvis.api import create_app
from jarvis.api.console import APP_ASSETS, CONSOLE_CSP
from jarvis.brief.models import BriefData, SleepLine
from jarvis.brief.render import render_text
from jarvis.buildbook.gen import fallback, plans, snapshot
from jarvis.buildbook.gen.layers import LAYER_OF
from jarvis.buildbook.gen.libs import VENDORED
from jarvis.buildbook.gen.repo import Repo
from jarvis.buildbook.plain import ALERT_WORDS
from jarvis.config import Settings
from jarvis.core.guardrails import ActionRisk
from jarvis.core.prompts import PERSONA_VERSION
from jarvis.fixes.ports import FixPart
from jarvis.helpers import kinds as helper_kinds
from jarvis.llm.mock_provider import MockProvider
from jarvis.memory.inmemory import InMemorySessionStore
from jarvis.mobile import contract
from jarvis.mobile.ports import (
    COLLECTIONS,
    DOOR_CAPS,
    DOOR_OWNER,
    DOOR_ROUTES,
    LAUNCH_WORDS,
    NEVER_LOCKED_PREFIXES,
    PACKAGE,
    PARTS,
    ROUTE_PREFIX,
    STATUS_ROUTE,
    TOOL_FAMILIES,
    MobileContext,
    MobilePart,
    PhoneReply,
    PhoneRequest,
    never_locked,
    tool_allowed,
)
from jarvis.notify.held import summary
from jarvis.notify.models import NO_SWITCH
from jarvis.notify.policy import DAYTIME_RING_KINDS, EPHEMERAL_KINDS
from jarvis.notify.ports import DEFAULT_URGENCY
from jarvis.notify.telegram_out import NO_CAP_KINDS
from jarvis.permissions.groups import GROUPS, get_group, groups_for
from jarvis.permissions.models import TARGETED_PURPOSES, Purpose
from jarvis.sos.hook import SOS_WORD_PREFIX, is_sos_word
from jarvis.telegram.rules import PRIVATE_PATTERNS
from jarvis.tools.base import Tool
from jarvis.vision.results import TASKS, Result, parse_result
from jarvis.voice.commands import COMMAND_HINTS, R7_PHRASES

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src" / "jarvis"
STATIC = SRC / "api" / "static"
GUIDE = ROOT / "docs" / "architecture" / "JARVIS-Architecture.md"
INTEG = ROOT / "docs" / "plans" / "r7-integration"
VECTORS = ROOT / "tests" / "fixtures" / "r7" / "phone_vectors.json"
R1, R2, R3 = ActionRisk.READ_ONLY, ActionRisk.REVERSIBLE, ActionRisk.IRREVERSIBLE
R7_JS = ("console-r7-links.js", "console-r7-share.js", "console-camera.js", "console-vision.js")
R7_JS += ("console-camera-panel.js", "console-r7-phone.js", "console-r7-lock.js")
R7_JS += ("console-r7-sos.js", "console-helpers-watch.js")
R7_CSS = ("console-r7-share.css", "console-camera.css", "console-r7-phone.css")
R7_CSS += ("console-r7-sos.css",)


def _lines(path: Path) -> int:
    return len(path.read_text(encoding="utf-8").splitlines())


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


# ---- 1, 2 · the version and the build book's release name --------------------------------------
def test_the_version_is_seven() -> None:
    assert jarvis.__version__ == "7.0.0"  # R7 I0 (was 11.1.1); nothing compares it (D26)


def _repo(tmp_path: Path, version: str | None) -> Repo:
    d = tmp_path / "docs" / "plans"
    d.mkdir(parents=True)
    for name in ("r11-1-observations.md", "r7-mobile.md", "r6-build-book.md", "r11-free.md"):
        (d / name).write_text(f"# {name}\n", encoding="utf-8")
    if version is not None:
        init = tmp_path / "src" / "jarvis" / "__init__.py"
        init.parent.mkdir(parents=True)
        init.write_text(f'__version__ = "{version}"\n', encoding="utf-8")
    return Repo.from_dir(tmp_path, sha="e" * 40, committed_at="2026-11-13T10:00:00+05:30")


@pytest.mark.parametrize(
    ("version", "label", "first"),
    [
        ("7.0.0", "R7", "r7-mobile.md"),
        ("11.1.0", "R11.1", "r11-1-observations.md"),
        ("11.0.2", "R11", "r11-free.md"),
        (None, "R11.1", "r11-1-observations.md"),  # no version file: the highest plan, as before
    ],
)
def test_the_book_names_the_release_from_the_repositorys_own_version(
    tmp_path: Path, version: str | None, label: str, first: str
) -> None:
    repo = _repo(tmp_path, version)
    assert plans.release_label(repo) == label
    assert plans.plan_paths(repo)[0] == f"docs/plans/{first}"  # this release's plan comes first
    rest = [p.rsplit("/", 1)[1] for p in plans.plan_paths(repo)[1:]]
    assert rest == sorted(rest, key=lambda n: plans._order(n), reverse=True)


def test_the_label_rule_reads_major_and_minor_only() -> None:
    assert fallback.label_from_version("v7.0.0") == "R7"
    assert fallback.label_from_version("v11.1.1") == "R11.1"
    assert fallback.label_from_version(None) is None
    assert fallback.label_from_version("nonsense") is None


def test_the_fallback_label_reads_the_checkouts_version_file(tmp_path: Path) -> None:
    (tmp_path / "src" / "jarvis").mkdir(parents=True)
    (tmp_path / "src" / "jarvis" / "__init__.py").write_text('__version__ = "7.0.0"\n', "utf-8")
    assert fallback._label(tmp_path) == "R7"  # no git here: the version file decides alone


def test_the_real_repository_is_r7_and_its_plan_comes_first() -> None:
    repo = Repo.from_git(ROOT)
    assert plans.release_label(repo) == "R7"
    assert plans.plan_paths(repo)[0] == "docs/plans/r7-mobile.md"


# ---- 3 · layers and the snapshot ----------------------------------------------------------------
def test_every_r7_package_has_its_layer() -> None:
    assert (LAYER_OF["mobile"], LAYER_OF["phone"]) == ("L1", "L1")
    assert LAYER_OF["vision"] == "L2"
    assert (LAYER_OF["watch"], LAYER_OF["sos"]) == ("L5", "L5")


def test_the_snapshot_leaves_out_android_builds_and_the_new_binaries(tmp_path: Path) -> None:
    for suffix in (".jar", ".ttf", ".task", ".tflite", ".gz", ".webp"):
        assert suffix in snapshot.BINARY_SUFFIXES
    repo = Repo.from_dir(tmp_path, sha="f" * 40, committed_at="2026-11-13T10:00:00+05:30")
    assert snapshot.left_out(repo, "android/app/build/outputs/x.txt") == "build output"
    assert snapshot.left_out(repo, "android/core/build/tmp/y.kt") == "build output"
    assert snapshot.left_out(repo, "android/gradle/wrapper/gradle-wrapper.jar") == "binary"


# ---- 4 · settings -------------------------------------------------------------------------------
def test_the_r7_settings_have_safe_defaults() -> None:
    s = Settings(_env_file=None)
    assert s.mobile_enabled is True and s.app_share_enabled is True
    assert (s.phone_link_max, s.phone_clock_skew_s) == (3, 120)
    assert s.watch_enabled is True and s.watch_keep_days == 400
    assert s.sos_enabled is True and s.sos_max_contacts == 5
    assert (s.sos_per_hour, s.sos_per_day) == (3, 10)  # a real SOS only
    assert (s.sos_test_per_hour, s.sos_test_per_day) == (3, 10)  # tests and "I'm safe"
    assert s.sos_countdown_s == 10
    assert s.vision_enabled is True and s.vision_keep_days == 90
    assert s.app_lock_minutes == 5


@pytest.mark.parametrize(
    ("field", "bad"),
    [
        ("phone_link_max", 0),
        ("phone_link_max", 4),
        ("phone_clock_skew_s", 29),
        ("phone_clock_skew_s", 301),
        ("watch_keep_days", 29),
        ("watch_keep_days", 801),
        ("sos_max_contacts", 6),
        ("sos_per_hour", 0),
        ("sos_per_hour", 11),
        ("sos_per_day", 51),
        ("sos_test_per_hour", 11),
        ("sos_test_per_day", 51),
        ("sos_countdown_s", 4),
        ("sos_countdown_s", 31),
        ("vision_keep_days", 0),
        ("vision_keep_days", 366),
        ("app_lock_minutes", 0),
        ("app_lock_minutes", 61),
    ],
)
def test_an_r7_setting_outside_its_range_is_refused(field: str, bad: int) -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, **{field: bad})


# ---- 5 · alert kinds and the two delivery lists -------------------------------------------------
def test_five_kinds_make_forty_three() -> None:
    every = get_args(AlertKind)
    assert R7_ALERT_KINDS == (
        "sos_sent",
        "phone_linked",
        "sos_contact_left",
        "phone_unlinked",
        "watch_stale",
    )
    assert len(every) == len(set(every)) == 43 and set(DEFAULT_URGENCY) == set(every)
    assert DEFAULT_URGENCY["sos_sent"] == DEFAULT_URGENCY["phone_linked"] == "urgent"
    assert DEFAULT_URGENCY["sos_contact_left"] == "important"
    assert DEFAULT_URGENCY["phone_unlinked"] == DEFAULT_URGENCY["watch_stale"] == "info"
    # urgent kinds ring at night; "a contact left" rings by day and is held at night
    assert "sos_contact_left" in DAYTIME_RING_KINDS and "sos_contact_left" not in EPHEMERAL_KINDS
    assert not {"sos_sent", "phone_linked"} & DAYTIME_RING_KINDS


def test_no_switch_turns_off_an_sos_or_a_new_phone_and_no_cap_drops_an_sos() -> None:
    assert {"sos_sent", "phone_linked"} <= NO_SWITCH
    assert {"sos_contact_left", "phone_unlinked", "watch_stale"}.isdisjoint(NO_SWITCH)
    assert NO_CAP_KINDS == frozenset({"home_hazard", "sos_sent"})


def test_the_held_summary_the_alerts_card_and_the_book_know_every_new_kind() -> None:
    words = summary([{"kind": "sos_contact_left"}])
    assert "emergency contact" in words.lower()
    js = _text(STATIC / "console-alerts.js")
    for kind in R7_ALERT_KINDS:
        assert f"['{kind}'," in js, kind
        assert kind in ALERT_WORDS, kind


# ---- 6 · permission rows ------------------------------------------------------------------------
def test_three_rows_make_forty_nine_and_sit_after_the_camera() -> None:
    ids = [g.id for g in GROUPS]
    assert len(ids) == len(set(ids)) == 49
    # I0 places them after Camera (the end of R3's block) and before Vitals (R4's first row):
    # R11.1 pins Plans and Pictures between Kitchen and Maps; Maps and YouTube stay last
    at = ids.index("camera")
    assert ids[at + 1 : at + 5] == ["vision", "watch", "sos", "vitals"]
    assert ids[-2:] == ["maps", "youtube"]
    vision, watch, sos = get_group("vision"), get_group("watch"), get_group("sos")
    assert vision is not None and watch is not None and sos is not None
    assert (vision.section, vision.risk) == ("Camera results", R1)
    assert (watch.section, watch.risk) == ("Watch and sleep", R2)
    assert (sos.section, sos.risk) == ("Emergency SOS", R1)


@pytest.mark.parametrize(
    ("tool", "risk", "row"),
    [
        ("sleep_last_night", R1, "watch"),
        ("sleep_week", R1, "watch"),
        ("watch_today", R1, "watch"),
        ("sleep_note", R2, "watch"),
        ("vision_results", R1, "vision"),
        ("sos_status", R1, "sos"),
    ],
)
def test_the_new_tools_fall_into_their_rows(tool: str, risk: ActionRisk, row: str) -> None:
    assert {g.id for g in groups_for(tool, risk)} == {row}


def test_no_row_lets_a_tool_send_an_sos() -> None:
    assert {g.id for g in groups_for("sos_send", R3)} == set()  # no tool sends (D19)


# ---- 7 · key purposes ---------------------------------------------------------------------------
def test_three_key_purposes_make_twenty_one() -> None:
    assert keyring.PURPOSES[-3:] == ("watch", "sos", "vision")
    assert len(keyring.PURPOSES) == len(set(keyring.PURPOSES)) == 21


# ---- 8, 20 · the parts' contract and wiring -----------------------------------------------------
def test_the_four_server_parts_and_what_each_owns() -> None:
    assert PARTS == ("shell", "vision", "phone", "body")
    assert set(TOOL_FAMILIES) == set(ROUTE_PREFIX) == set(COLLECTIONS) == set(STATUS_ROUTE)
    assert tool_allowed("body", "sleep_last_night") and tool_allowed("body", "sos_status")
    assert tool_allowed("vision", "vision_results") and not tool_allowed("vision", "sos_status")
    assert not tool_allowed("body", "sos_send")  # the brain's only SOS tool is the read
    assert not tool_allowed("phone", "phone_link") and not tool_allowed("shell", "vision_x")
    assert COLLECTIONS["body"] == ("watch_days", "watch_state", "sos", "sos_join", "sos_log")
    assert COLLECTIONS["phone"] == ("phone_link", "phone_devices")
    assert COLLECTIONS["vision"] == ("vision_results",) and COLLECTIONS["shell"] == ()
    assert PACKAGE == "io.github.shark2558.jarvis"
    assert LAUNCH_WORDS == ("talk", "look", "sos", "shared")
    for name in PARTS:
        assert callable(importlib.import_module(wiring.PART_MODULES[name]).build), name


def test_a_mobile_part_carries_r11_1s_part_fields() -> None:
    fix = set(FixPart.__dataclass_fields__)
    assert fix <= set(MobilePart.__dataclass_fields__)  # tools, jobs, privacy, services, ready
    part = MobilePart("body")
    assert part.services == {} and part.tools == () and part.ready == "not built yet"
    with pytest.raises(AttributeError):
        part.ready = "x"  # type: ignore[misc]


def test_the_door_has_four_routes_each_owned_by_one_part() -> None:
    assert DOOR_ROUTES == ("hello", "health", "inbox", "sos")
    assert DOOR_OWNER == {"hello": "phone", "health": "body", "inbox": "phone", "sos": "body"}
    assert DOOR_CAPS["inbox"] == 10 * 1024 * 1024 + 64 * 1024
    assert max(v for k, v in DOOR_CAPS.items() if k != "inbox") <= 256 * 1024


@asynccontextmanager
async def running(s: Settings) -> AsyncIterator[tuple[FastAPI, AsyncClient]]:
    app = create_app(s, provider=MockProvider(), store=InMemorySessionStore())
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            yield app, c


async def test_the_app_starts_with_four_built_parts_and_their_status_routes(
    settings: Settings,
) -> None:
    async with running(settings) as (app, client):
        parts = app.state.r7_parts
        assert list(parts) == list(PARTS)
        assert all(isinstance(p, MobilePart) and p.name == n for n, p in parts.items())
        assert all(p.ready != wiring.SETUP_FAILED for p in parts.values())  # I1: none left out
        for name in PARTS:
            r = await client.get(STATUS_ROUTE[name])
            assert r.status_code == 200, name
            assert r.json()["part"] == name and "ready" in r.json()
            assert r.headers["cache-control"] == "no-store"
        assert (await client.get("/v1/sos")).json()["part"] == "body"
        # I1: every part is built: C's hello and inbox, D's health and sos (DOOR_OWNER)
        handlers = wiring.door_handlers(app)
        assert set(handlers) == {"hello", "inbox", "health", "sos"}
        assert all(callable(h) for h in handlers.values())
        for route in handlers:
            assert route in (parts[DOOR_OWNER[route]].services.get("door") or {}), route


# ---- I1 · the one name of the SOS contacts seam (Part D offers it, Part C's hello reads it) -----
async def test_the_sos_contacts_seam_has_one_name_one_owner_and_one_reader(
    settings: Settings,
) -> None:
    from jarvis.phone.handlers import SOS_SEAM

    assert SOS_SEAM == "sos_contacts"  # what Part C's hello reads
    assert wiring.SERVICE_OWNER["sos_contacts"] == "body"  # only Part D may offer it
    async with running(settings) as (app, _):
        parts = app.state.r7_parts
        assert callable(parts["body"].services["sos_contacts"])
        assert all("sos_contacts" not in p.services for n, p in parts.items() if n != "body")
    stray = MobilePart("vision", services={"sos_contacts": _reply})
    with pytest.raises(ValueError, match="services it doesn't own"):
        wiring.check_part("vision", stray)


def _tool(name: str, risk: ActionRisk = R1) -> Tool:
    async def run(_: dict[str, object]) -> str:
        return "ok"

    return Tool(name, "a test tool", {"type": "object", "properties": {}}, risk, run)


async def _reply(_: PhoneRequest) -> PhoneReply:
    return PhoneReply(200, {"ok": True})


def _ctx(app: FastAPI, s: Settings) -> MobileContext:
    return MobileContext(s=s, docs=None, audit=None, state=lambda n: getattr(app.state, n, None))


def test_a_part_that_breaks_its_contract_is_left_out_and_the_rest_stay(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    app = FastAPI()

    def build(name: str, ctx: MobileContext) -> MobilePart:
        if name == "shell":
            return MobilePart("shell", tools=(_tool("vision_results"),))  # another part's tool
        if name == "vision":
            raise RuntimeError("boom")
        if name == "phone":
            return MobilePart("phone", services={"door": {"health": _reply}})  # D's route
        return MobilePart("body", tools=(_tool("sleep_week"),), services={"door": {"sos": _reply}})

    monkeypatch.setattr(wiring, "_build", build)
    parts = wiring.build_parts(_ctx(app, settings))
    assert [parts[n].ready for n in ("shell", "vision", "phone")] == [wiring.SETUP_FAILED] * 3
    assert parts["body"].ready == "not built yet"
    assert [t.name for t in wiring.mobile_tools(parts)] == ["sleep_week"]
    assert wiring.mobile_tools(None) == ()
    app.state.r7_parts = parts
    assert list(wiring.door_handlers(app)) == ["sos"]


def test_the_wiring_files_have_their_slots() -> None:
    app_py = _text(SRC / "api" / "app.py")
    for needle in (
        "import jarvis.api.r7_wiring as r7",
        "await r7.wire_r7(app, s, docs, audit)",
        "r7.install_r7_routes(app)",
        "r7=r7.mobile_tools(app.state.r7_parts)",
        "**r7.BODY_CAPS",
        "r7.install_app_lock(app)",
    ):
        assert needle in app_py, needle
    # the app lock is added BEFORE R6's show lock, so it runs inside it (both inside the session)
    assert app_py.index("r7.install_app_lock(app)") < app_py.index("install_show_lock(app, s)")
    assert app_py.index("await r7.wire_r7(") < app_py.index("await wire_r11(")
    setup = _text(SRC / "tools" / "setup.py")
    assert "r7: Sequence[Tool] = ()" in setup
    assert "mobile_privacy_sources(app)" in _text(SRC / "api" / "personal.py")
    r11 = _text(SRC / "api" / "r11_wiring.py")
    for needle in ("mobile_clock_jobs(app)", "mobile_daily_jobs(app)", "mobile_brief(app)"):
        assert needle in r11, needle
    assert "install_mobile_phrases(app)" in r11


def test_the_body_caps_name_the_inbox_and_the_share_target() -> None:
    assert wiring.BODY_CAPS == {
        "/phone/v1/inbox": DOOR_CAPS["inbox"],
        "/app/share/in": 5 * 10 * 1024 * 1024 + 64 * 1024,
    }


def test_the_never_locked_list_is_d21s() -> None:
    for method, path in [
        ("GET", "/"),
        ("GET", "/static/console.js"),
        ("GET", "/console/config"),
        ("GET", "/auth/me"),
        ("GET", "/auth/login"),
        ("POST", "/v1/passkeys/challenge"),
        ("POST", "/v1/session/unlock"),
        ("GET", "/manifest.webmanifest"),
        ("GET", "/.well-known/assetlinks.json"),
        ("POST", "/app/share/in"),
        ("POST", "/v1/sos/send"),
        ("POST", "/phone/v1/sos"),
    ]:
        assert never_locked(method, path), (method, path)
    for method, path in [
        ("GET", "/v1/vault"),
        ("POST", "/v1/chat"),
        ("GET", "/v1/passkeys/challenge"),  # only the POST that starts a check
        ("GET", "/v1/sessions"),
        ("GET", "/staticx"),
        ("GET", "/auth"),
    ]:
        assert not never_locked(method, path), (method, path)
    assert all(p.endswith("/") for p in NEVER_LOCKED_PREFIXES)


async def test_the_app_lock_slot_passes_until_part_c_fills_it_then_answers_423() -> None:
    app = FastAPI()
    calls: list[str] = []

    @app.get("/v1/vault")
    async def vault() -> dict[str, str]:
        calls.append("vault")
        return {"ok": "yes"}

    @app.get("/auth/me")
    async def me() -> dict[str, str]:
        return {"email": "x"}

    wiring.install_app_lock(app)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        assert (await c.get("/v1/vault")).status_code == 200  # no checker yet: a pass-through

        async def locked(scope: dict[str, Any]) -> bool:
            return True

        app.state.r7_parts = {"phone": MobilePart("phone", services={"app_lock": locked})}
        r = await c.get("/v1/vault")
        assert r.status_code == 423 and r.json()["error"] == "device_locked"
        assert (await c.get("/auth/me")).status_code == 200  # never locked
        assert calls == ["vault"]

        async def broken(scope: dict[str, Any]) -> bool:
            raise RuntimeError("store down")

        app.state.r7_parts = {"phone": MobilePart("phone", services={"app_lock": broken})}
        r = await c.get("/v1/vault")
        assert r.status_code == 503 and r.json()["error"] == "lock_unreadable"


# ---- 9 · the phone's signed request and the shared vectors --------------------------------------
def _public(v: dict[str, Any]) -> ec.EllipticCurvePublicKey:
    der = bytes.fromhex(v["public_key_spki_der_hex"])
    key = serialization.load_der_public_key(der)
    assert isinstance(key, ec.EllipticCurvePublicKey) and key.curve.name == "secp256r1"
    return key


def test_the_vectors_hold_no_private_key_and_every_case_is_exact() -> None:
    raw = _text(VECTORS)
    assert "BEGIN" not in raw and '"private' not in raw  # a public key only
    v = load_vectors()
    assert v["scheme"] == contract.SCHEME and v["header"] == contract.HEADER
    assert v["package"] == PACKAGE and len(bytes.fromhex(v["signing_fingerprint_hex"])) == 32
    key = _public(v)
    for case in v["cases"]:
        body = case["body"].encode("utf-8")
        assert hashlib.sha256(body).hexdigest() == case["body_sha256_hex"], case["name"]
        string = contract.signing_string(
            v["device_id"], case["t"], case["nonce"], case["method"], case["path"], body
        )
        assert string.decode("ascii") == case["string"], case["name"]
        auth = contract.parse_header(case["header"])
        assert auth is not None and auth.device_id == v["device_id"], case["name"]
        assert (auth.t, auth.nonce) == (case["t"], case["nonce"]), case["name"]
        try:
            key.verify(auth.signature, string, ec.ECDSA(hashes.SHA256()))
            ok = True
        except InvalidSignature:
            ok = False
        assert ok is case["verifies"], case["name"]
        assert case["door"] == "accept" or case["door"].startswith("401 "), case["name"]
        if "payload" in case:  # the app's tiny JSON writer must give these exact bytes
            assert contract.canonical_json(case["payload"]) == body, case["name"]
        if "first_line" in case:
            assert body.split(b"\n", 1)[0] == contract.canonical_json(case["first_line"])
    for path in v["refused_paths"]:
        with pytest.raises(ValueError):
            contract.signing_string(v["device_id"], 1, "a" * 32, "POST", path, b"")


def test_the_vectors_cover_every_door_route_and_the_bad_cases() -> None:
    names = {c["name"] for c in load_vectors()["cases"]}
    assert {"hello", "health", "inbox", "sos", "sos_no_location"} <= names
    assert {"changed_body", "other_key", "changed_path", "stale_time_shape"} <= names


def test_the_header_shape_and_the_signing_string_refuse_what_is_not_v1() -> None:
    sig = contract.b64url(b"\x30" * 70)
    good = f"v1;d=ph_0123456789ab;t=1763000000;n={'a' * 32};s={sig}"
    assert contract.parse_header(good) is not None
    for bad in (
        None,
        "",
        good.replace("v1;", "v2;"),
        good.replace("ph_0123456789ab", "ph_XYZ"),
        good + ";x=1",
        good.replace(";n=", ";nonce="),
        good.replace("a" * 32, "a" * 31),
    ):
        assert contract.parse_header(bad) is None, bad
    with pytest.raises(ValueError):
        contract.signing_string("ph_0123456789ab", 1, "a" * 32, "POST", "/phone/v1/sos?x=1", b"")
    with pytest.raises(ValueError):
        contract.signing_string("ph_0123456789ab", 1, "a" * 32, "PUT", "/phone/v1/sos", b"")


def test_canonical_json_is_one_byte_form_and_refuses_floats() -> None:
    got = contract.canonical_json({"b": 1, "a": ["x\n", "é", True, None]})
    assert got == '{"b":1,"a":["x\\n","é",true,null]}'.encode()
    with pytest.raises(TypeError):
        contract.canonical_json({"lat": 12.5})


async def test_the_fake_door_hands_a_verified_request_to_its_handler() -> None:
    seen: list[PhoneRequest] = []

    async def health(req: PhoneRequest) -> PhoneReply:
        seen.append(req)
        return PhoneReply(200, {"stored": 1})

    door = FakeDoor({"health": health})
    reply = await door.call("health", b'{"v":1,"days":[]}')
    assert reply == PhoneReply(200, {"stored": 1})
    assert seen[0].route == "health" and seen[0].device_id == door.device_id
    assert (await door.call("sos", b"{}")).status == 404  # no handler: the route is not there
    key = phone_key()
    headers, body = sign_request(key, "ph_0123456789ab", "POST", "/phone/v1/hello", {"v": 1})
    auth = contract.parse_header(headers[contract.HEADER])
    assert auth is not None and body == b'{"v":1}'


# ---- 10 · the console ---------------------------------------------------------------------------
def test_the_more_sheet_is_built_by_the_dock_and_the_page_keeps_its_budget() -> None:
    html = _text(STATIC / "console.html")
    assert "sheet-item" not in html and "data-sheet-open" not in html  # console-dock.js builds them
    assert '<dialog class="sheet" id="moreSheet"' in html and 'id="moreClose"' in html
    assert _lines(STATIC / "console.html") <= 782  # 795 at R11.1; 19 entries out, 6 lines in
    dock_js = _text(STATIC / "console-dock.js")
    assert "innerHTML" not in dock_js and "DESCRIBE" in dock_js
    names = re.findall(r'data-open="(\w+)"', html[html.index('id="dock"') :])
    for name in names[2:]:
        assert re.search(rf"\b{name}: '", dock_js), name  # every folding tab has its description


def test_the_camera_is_the_twenty_second_tab_with_its_panel() -> None:
    html = _text(STATIC / "console.html")
    dock = html[html.index('id="dock"') : html.index("</nav>")]
    names = re.findall(r'data-open="(\w+)"', dock)
    assert len(names) == 22 and names[-1] == "camera" and names[-2] == "helpers"
    assert 'id="p-camera" data-panel="camera" aria-labelledby="t-camera"' in html
    assert '<h2 id="t-camera">Camera</h2>' in html


def test_one_manifest_link_and_one_loader_line() -> None:
    html = _text(STATIC / "console.html")
    assert html.count('<link rel="manifest" href="/manifest.webmanifest">') == 1
    assert html.count('<script type="module" src="/static/console-r7.js"></script>') == 1
    loader = _text(STATIC / "console-r7.js")
    for js in ("console-r7-send.js", "console-vision.js", *R7_JS):
        if js in ("console-helpers-watch.js", "console-vision.js"):
            continue  # loaded by the Helpers frame / imported by the camera panel
        assert f"./{js}" in loader, js
    for css in R7_CSS:
        assert f"/static/{css}" in loader, css
    for name in ("console-r7.js", "console-r7-send.js", *R7_JS, *R7_CSS):
        assert name in APP_ASSETS, name
        assert (STATIC / name).is_file(), name
        assert name not in html or name == "console-r7.js"
        if name.endswith(".js"):
            assert "innerHTML" not in _text(STATIC / name), name
    assert "window.JarvisMobile" in loader and "innerHTML" not in loader


def test_new_css_stays_small() -> None:
    for name in R7_CSS:
        assert _lines(STATIC / name) <= 150, name


def test_the_line_budgets_hold() -> None:
    assert _lines(SRC / "tools" / "gateway.py") <= 760
    assert _lines(SRC / "api" / "app.py") <= 735
    for path in STATIC.glob("console*.js"):
        assert _lines(path) <= 800, path.name


# ---- 11 · the CSP, the vision route, launch words on a cross-site visit -------------------------
def test_the_csp_gains_exactly_manifest_src_self() -> None:
    assert CONSOLE_CSP.endswith("; worker-src 'self'; manifest-src 'self'")
    assert CONSOLE_CSP.count("manifest-src") == 1


async def test_a_cross_site_visit_loses_do_and_open_and_keeps_reauth(settings: Settings) -> None:
    async with running(settings) as (_, client):
        r = await client.get(
            "/?do=talk&open=home&reauth=1", headers={"Sec-Fetch-Site": "cross-site"}
        )
        assert r.status_code == 302 and r.headers["location"] == "/?reauth=1"
        r = await client.get("/?do=talk", headers={"Sec-Fetch-Site": "cross-site"})
        assert r.status_code == 302 and r.headers["location"] == "/"
        for site in ("none", "same-origin"):
            r = await client.get("/?do=talk", headers={"Sec-Fetch-Site": site})
            assert r.status_code == 200, site
        r = await client.get("/?reauth=1", headers={"Sec-Fetch-Site": "cross-site"})
        assert r.status_code == 200  # Google's return keeps working


async def test_the_vision_route_serves_only_what_a_manifest_lists(
    settings: Settings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import jarvis.api.console as console

    rel = tmp_path / "vision-test"
    rel.mkdir()
    (rel / "engine.js").write_text("export const x = 1;\n", encoding="utf-8")
    (rel / "model.task").write_bytes(b"\x00\x01")
    (rel / "other.js").write_text("x", encoding="utf-8")
    good = hashlib.sha256(b"export const x = 1;\n").hexdigest()
    files = {
        "engine.js": {"sha256": good, "type": "application/javascript"},
        "model.task": {"sha256": "0" * 64, "type": "application/octet-stream"},  # a wrong sum
    }
    (rel / "MANIFEST.json").write_text(json.dumps({"files": files}), encoding="utf-8")
    monkeypatch.setattr(console, "_VISION", tmp_path)
    console.vision_files.cache_clear()
    try:
        async with running(settings) as (_, client):
            r = await client.get("/static/vendor/vision/vision-test/engine.js")
            assert r.status_code == 200 and r.headers["cache-control"].startswith("public")
            assert r.headers["content-security-policy"] == CONSOLE_CSP  # worker scripts too
            for bad in ("other.js", "MANIFEST.json", "model.task", "..%2Fx"):
                got = await client.get(f"/static/vendor/vision/vision-test/{bad}")
                assert got.status_code == 404, bad
            assert (await client.get("/static/vendor/vision/nope/engine.js")).status_code == 404
    finally:
        console.vision_files.cache_clear()


# ---- 12 · Helpers' Watch tab --------------------------------------------------------------------
def test_helpers_gains_a_watch_tab_that_is_not_an_r11_part() -> None:
    assert list(helper_kinds.TABS) == [*helper_kinds.PARTS, "watch"]
    assert "watch" not in helper_kinds.PARTS
    js = _text(STATIC / "console-helpers.js")
    assert "['watch', 'Watch']" in js and "import('./console-helpers-watch.js')" in js


# ---- 13 · voice ---------------------------------------------------------------------------------
def test_the_camera_and_sos_phrases_are_speech_hints() -> None:
    assert set(R7_PHRASES) == {"camera.off", "sos.open"}
    assert len(R7_PHRASES["camera.off"]) >= 20 and "cameras off" in R7_PHRASES["camera.off"]
    hints = {h.lower() for h in COMMAND_HINTS}
    for phrases in R7_PHRASES.values():
        for p in phrases:
            assert " " in p and p in hints, p
    assert not any("on" in p.split() for p in R7_PHRASES["camera.off"])  # nothing turns it on


def test_the_voice_loop_gains_no_way_to_start_a_turn() -> None:
    mic = _text(STATIC / "console-voice-mic.js")
    frozen = mic[mic.index("window.JarvisVoiceLoop = Object.freeze({") :]
    frozen = frozen[: frozen.index("});")]
    assert "press" not in frozen and "start" not in frozen


# ---- 14 · the five 423 readers ------------------------------------------------------------------
def test_every_423_reader_tells_the_show_from_the_device_lock() -> None:
    js = _text(STATIC / "console.js")
    assert "'device_locked'" in js and "function deviceLocked(" in js
    assert js.count("lockedBy(") >= 3  # api(), raw() and the two /auth/me reads share one reader
    for line in js.splitlines():
        if "423" in line and "location.replace('/book/show')" in line:
            pytest.fail(f"a 423 still goes straight to the show: {line.strip()}")
    talk = _text(STATIC / "console-book-talk.js")
    assert "e.code !== 'device_locked'" in talk


# ---- 15 · the Telegram hook ---------------------------------------------------------------------
def test_sos_words_have_their_own_prefix() -> None:
    assert SOS_WORD_PREFIX == "sos-"
    assert is_sos_word("sos-" + "a" * 22) and not is_sos_word("ABCD2345")
    assert not is_sos_word("sos-") and not is_sos_word("sos-" + "!" * 22)


# (the hook's behaviour: tests/test_r7_telegram_hook.py)


# ---- 16 · the Android CI's first version and the ignore list ------------------------------------
def test_the_ignore_list_keeps_android_secrets_and_builds_out() -> None:
    ignored = set(_text(ROOT / ".gitignore").split())
    for entry in (
        "android/local.properties",
        "*.jks",
        "*.keystore",
        "android/**/build/",
        ".gradle/",
        "android/.idea/",
        "android/.kotlin/",
        "*.iml",
        "*.apk",
        "*.aab",
        "captures/",
    ):
        assert entry in ignored, entry


def test_the_android_workflow_proves_without_secrets() -> None:
    wf = _text(ROOT / ".github" / "workflows" / "android.yml")
    assert "android/**" in wf and "jarvis.invalid" in wf
    assert "gradle/actions/wrapper-validation" in wf
    assert "secrets." not in wf and "not for installing" in wf
    assert "retention-days: 7" in wf
    assert "resolveDependencies" in wf  # every dependency is resolved first
    assert "java-version: '17'" in wf  # D23: CI runs Gradle on JDK 17
    props = _text(ROOT / "android" / "gradle" / "wrapper" / "gradle-wrapper.properties")
    assert "gradle-9.6.0-bin.zip" in props
    assert re.search(r"^distributionSha256Sum=[0-9a-f]{64}$", props, re.M)  # CI's first run read it
    for name in ("gradlew", "gradlew.bat", "gradle/wrapper/gradle-wrapper.jar"):
        assert (ROOT / "android" / name).is_file(), name


def test_one_kotlin_pin_and_the_agp_pin() -> None:
    toml = _text(ROOT / "android" / "gradle" / "libs.versions.toml")
    assert re.search(r'^agp = "9\.5\.1"$', toml, re.M)
    assert re.search(r'^kotlin = "2\.4\.10"$', toml, re.M)
    assert toml.count("2.4.10") == 1


# ---- 17 · the guide -----------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("card", "layer", "needles"),
    [
        (
            "C62",
            "### Layer 2",
            ("`src/jarvis/mobile/`", "`src/jarvis/phone/`", "`phone_devices/{uid}`"),
        ),
        (
            "C63",
            "### Layer 3",
            ("`src/jarvis/vision/`", "`console-vision.js`", "`vision_results/{uid}_{date}`"),
        ),
        ("C64", "### Layer 6", ("`src/jarvis/watch/`", "`watch_days/{uid}_{date}`")),
        ("C65", "### Layer 6", ("`src/jarvis/sos/`", "`sos/{uid}`", "`sos_log/{uid}_{id}`")),
    ],
)
def test_the_guide_has_the_four_planned_r7_cards(
    card: str, layer: str, needles: tuple[str, ...]
) -> None:
    guide = _text(GUIDE)
    body = guide[guide.index(f"#### {card} · ") :]
    body = body[: body.index(layer)]
    body = body[: body.index("\n#### ", 10)] if "\n#### " in body[10:] else body
    assert "PLANNED" in body and "R7" in body
    for needle in needles:
        assert needle in body, (card, needle)


def test_the_guide_no_longer_names_capacitor_or_ml_kit_as_the_plan() -> None:
    guide = _text(GUIDE)
    for line in guide.splitlines():
        low = line.lower()
        if "capacitor" in low:
            assert "not capacitor" in low or "instead of capacitor" in low, line
        if "ml kit" in low:
            assert "not ml kit" in low or "no ml kit" in low, line
    assert "Trusted Web Activity" in guide


# ---- 18 · the eval runner -----------------------------------------------------------------------
def test_the_r7_runner_passes_with_every_server_and_app_part_built() -> None:
    run = subprocess.run(
        [sys.executable, str(ROOT / "evals" / "r7" / "run.py"), "--mock"],
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )
    assert run.returncode == 0, run.stdout[-4000:] + run.stderr[-4000:]
    report = json.loads((ROOT / "evals" / "r7" / "report.json").read_text(encoding="utf-8"))
    ids = {r["id"] for r in report["results"]}
    built = ("shell", "vision", "phone", "body", "needles", "contract")  # I1: every part built
    for part in built:
        assert f"{part}:not_built_yet" not in ids, part
        assert any(i.startswith(f"{part}:") for i in ids), part
    control = report["negative_control"]
    assert control["suite_failed"] is True
    for part in built:
        assert control["failed_cases"][part], part  # each part's own control fails it
    assert control["parts_not_built"] == []
    needles = control["failed_cases"]["needles"]  # I1's three controls, each failing its scan
    assert needles["coordinate_in_address"] == ["needles:coordinates"]
    assert "needles:read_text" in needles["seal_off"] and "needles:heart" in needles["seal_off"]
    assert needles["fence_off"] == ["needles:read_text"]


def test_the_r7_suite_is_gated_in_run_all_mock() -> None:
    text = _text(ROOT / "evals" / "run_all_mock.py")
    line = next(x for x in text.splitlines() if '"r7 (gated)"' in x)
    assert 'HERE / "r7" / "run.py"' in line and line.rstrip().endswith("True),")


# ---- 19 · the persona: I1 made it p7.0 (D26; tests/test_r7_i1_persona.py) ----------------------
def test_the_persona_version_is_r7s_after_i1() -> None:
    assert PERSONA_VERSION == "p7.0"  # I1 (D26); nothing compares it


# ---- 21 · Telegram's private patterns -----------------------------------------------------------
def test_watch_sleep_and_vision_reads_are_private_on_telegram() -> None:
    for pattern in ("watch_*", "sleep_*", "vision_*"):
        assert pattern in PRIVATE_PATTERNS, pattern
    assert "sos_*" not in PRIVATE_PATTERNS  # sos_status names no one's number: an open read


# (the built-registry guard: tests/test_r7_telegram_hook.py)


# ---- 23 · the brief's sleep line ----------------------------------------------------------------
def test_the_brief_carries_one_pinned_sleep_line() -> None:
    assert set(SleepLine.model_fields) == {"minutes", "start", "end", "source"}
    line = SleepLine(minutes=400, start="23:50", end="06:30", source="watch")
    assert BriefData.model_fields["sleep"].default is None
    data = BriefData(date="2026-11-13", tz="Asia/Kolkata", sleep=line)
    assert data.model_dump(mode="json")["sleep"] == {
        "minutes": 400,
        "start": "23:50",
        "end": "06:30",
        "source": "watch",
    }
    # I1 (Workshop decision): "app" names a night from another health app honestly
    assert set(get_args(SleepLine.model_fields["source"].annotation)) == {
        "watch",
        "phone",
        "app",
        "typed",
    }
    for bad in (
        {"minutes": -1},
        {"minutes": 24 * 60 + 1},
        {"start": "25:00"},
        {"source": "guess"},
    ):
        with pytest.raises(ValidationError):
            SleepLine(
                **{"minutes": 400, "start": "23:50", "end": "06:30", "source": "watch", **bad}
            )


def test_the_emailed_brief_leaves_the_sleep_line_out() -> None:
    line = SleepLine(minutes=400, start="23:50", end="06:30", source="watch")
    with_sleep = render_text(BriefData(date="2026-11-13", tz="Asia/Kolkata", sleep=line))
    without = render_text(BriefData(date="2026-11-13", tz="Asia/Kolkata"))
    assert with_sleep == without and "sleep" not in with_sleep.lower()


# ---- 24 · licences ------------------------------------------------------------------------------
def test_the_vision_licences_are_known_to_the_book() -> None:
    libs = {v[0] for k, v in VENDORED.items() if k.startswith("vendor/vision/")}
    assert {"MediaPipe Tasks Vision", "tesseract.js", "tesseract.js-core", "zxing-wasm"} <= libs
    assert any("English" in lib for lib in libs) and any("model" in lib for lib in libs)


# ---- 25 · the picture send door -----------------------------------------------------------------
def test_one_door_sends_pictures_through_the_attach_path() -> None:
    attach = _text(STATIC / "console-attach.js")
    head = attach[attach.index("window.JarvisAttach = Object.freeze({") :]
    assert "add," in head[: head.index("});")] or "add:" in head[: head.index("});")]
    send = _text(STATIC / "console-r7-send.js")
    for needle in (
        "JarvisAttach",
        ".add(",
        "shrink",
        "cost",
        "Pictures sent from this device today",
    ):
        assert needle in send, needle
    assert "fetch(" not in send and "XMLHttpRequest" not in send  # the console's own transport
    files = _text(STATIC / "console-r111-files.js")
    assert "const PICTURE = /\\.(png|jpe?g|webp)$/i;" in files
    js = _text(STATIC / "console.js")
    assert "sees: b.sees_pictures === true" in js


async def test_the_brain_list_says_which_brain_sees_pictures(settings: Settings) -> None:
    async with running(settings) as (_, client):
        brains = (await client.get("/v1/brains")).json()
        assert brains and all(b["sees_pictures"] is False for b in brains)  # the mock has no eyes


# ---- 26 · the builders' common brief ------------------------------------------------------------
def test_the_common_brief_carries_the_ask_nothing_before_sign_in_rule() -> None:
    brief = _text(INTEG / "BRIEF-COMMON.md")
    assert "test_before_sign_in_the_block_asks_the_server_nothing" in brief
    assert "do=shared" in brief and "phone-contract.md" in brief
    for part in ("A", "B", "C", "D", "E"):
        assert f"INTEGRATION-{part}.md" in brief, part
    contract_md = _text(INTEG / "phone-contract.md")
    for needle in (contract.HEADER, contract.SCHEME, "tag: kind", PACKAGE, "do=talk"):
        assert needle in contract_md, needle


# ---- 27 · passkey purposes ----------------------------------------------------------------------
def test_two_passkey_purposes_join_with_their_exact_targets() -> None:
    from jarvis.permissions.service import purpose_binding

    assert {"phone_link", "device_unlock"} <= set(get_args(Purpose))
    assert {"phone_link", "device_unlock"} <= set(TARGETED_PURPOSES)
    assert purpose_binding("u", "phone_link", "pl_0123456789ab")
    assert purpose_binding("u", "device_unlock", "ss_" + "a" * 24)
    from jarvis.permissions.groups import PermissionRejected

    for purpose, target in (
        ("phone_link", None),
        ("phone_link", "x"),
        ("device_unlock", None),
        ("device_unlock", "pl_0123456789ab"),
    ):
        with pytest.raises(PermissionRejected):
            purpose_binding("u", purpose, target)
    js = _text(STATIC / "console-permissions.js")
    assert "'phone_link', 'device_unlock'].includes(purpose)" in js


# ---- the guide-coverage cards and the result schema (seams 8, 17) -------------------------------
def test_a_result_outside_its_schema_is_dropped() -> None:
    assert TASKS == ("text", "code", "objects", "pose", "quality")
    base = {"v": 1, "at": 1763000000, "ms": 40, "device": "phone", "ok": True}
    base["quality"] = {"light": 0.5, "sharp": 0.7}
    good = parse_result({**base, "task": "text", "data": {"text": "MRP 40"}})
    assert isinstance(good, Result) and good.data == {"text": "MRP 40"}
    assert parse_result({**base, "task": "text", "data": {"text": "x" * 2001}}) is None
    assert (
        parse_result({**base, "task": "objects", "data": {"objects": [{"label": "unicorn"}]}})
        is None
    )
    assert parse_result({**base, "task": "quality", "data": {"light": 2.0, "sharp": 0.1}}) is None
    assert parse_result({**base, "task": "face", "data": {}}) is None  # never a task R7 has
    assert parse_result({**base, "task": "text", "data": {"text": "a", "pixels": [1, 2]}}) is None
    assert parse_result("not a dict") is None
