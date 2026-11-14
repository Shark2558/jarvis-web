# tests/test_r14_seams.py -- R14 I0 seams (docs/plans/r14-hardening.md "The I0 seam list", 1-11):
# the version and the book's release name, layers, the settings and the drill database lock, nine
# alert kinds and every table that names a kind (self-health's own soft cap), the key purpose, the
# permission rows' words, the parts' contract and ports (backup, selfwatch, skills), the tick
# observer's outcomes, the brain's two slots, the stub parts and routes, the shared 5-minute clock
# for the brief's owners (D7), the Vitals and privacy slots, the guide's planned cards, the eval
# runner and its gate, the set-up script's read-only status, the size guards and the persona.
from __future__ import annotations

import asyncio
import json
import os
import re
import stat
import subprocess
import sys
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any, get_args
from zoneinfo import ZoneInfo

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from pydantic import ValidationError
from r14_fakes import RecordingJob, fake_spec

import jarvis
import jarvis.api.r14_wiring as wiring
from jarvis import keyring, ticks
from jarvis.alerts import R14_ALERT_KINDS, AlertKind
from jarvis.api import create_app, tick_wiring
from jarvis.backup.ports import DRILL_DB, NOT_SET_UP, LiveTargetRefused, drill_target
from jarvis.buildbook.gen import plans
from jarvis.buildbook.gen.layers import LAYER_OF
from jarvis.buildbook.gen.repo import Repo
from jarvis.buildbook.plain import ALERT_WORDS
from jarvis.config import Settings
from jarvis.core.guardrails import ActionRisk
from jarvis.core.prompts import PERSONA_VERSION
from jarvis.hardening.ports import (
    COLLECTIONS,
    JOB_OWNER,
    PARTS,
    R14_JOB_NAMES,
    R14_STATUS_ROUTE,
    ROUTE_PREFIX,
    SERVICE_OWNER,
    STATUS_ROUTE,
    TOOL_FAMILIES,
    VITALS_IDS,
    HardeningPart,
    tool_allowed,
)
from jarvis.llm.mock_provider import MockProvider
from jarvis.memory.inmemory import InMemorySessionStore
from jarvis.notify.held import summary
from jarvis.notify.policy import DAYTIME_RING_KINDS, EPHEMERAL_KINDS
from jarvis.notify.ports import DEFAULT_URGENCY, Decision, Signal
from jarvis.notify.storm import MAX_SELF_PER_HOUR, SELF_KINDS, SOFT_URGENT_KINDS, Storm
from jarvis.permissions.groups import GROUPS, get_group, groups_for
from jarvis.skills.ids import SKILL_IDS, SKILL_LABELS
from jarvis.skills.offer import offer_all
from jarvis.skills.ports import BrainSlots, LedgerCall
from jarvis.webpush.service import TARGETS

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src" / "jarvis"
STATIC = SRC / "api" / "static"
GUIDE = ROOT / "docs" / "architecture" / "JARVIS-Architecture.md"
INTEG = ROOT / "docs" / "plans" / "r14-integration"
R1, R2, R3 = ActionRisk.READ_ONLY, ActionRisk.REVERSIBLE, ActionRisk.IRREVERSIBLE
SELF = ("job_failing", "clock_stopped", "brief_missed", "errors_piling", "spend_spike")
SELF += ("deploy_changed", "backup_problem")


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _lines(path: Path) -> int:
    return len(_text(path).splitlines())


@asynccontextmanager
async def running(s: Settings) -> AsyncIterator[tuple[FastAPI, AsyncClient]]:
    app = create_app(s, provider=MockProvider(), store=InMemorySessionStore())
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            yield app, c


# ---- 1 · the version and the book's release name -------------------------------------------------
def test_the_version_is_fourteen() -> None:
    assert jarvis.__version__ == "14.0.0"  # R14 I0 (was 7.0.0); nothing compares it


def test_the_real_repository_is_r14_and_its_plan_comes_first() -> None:
    repo = Repo.from_git(ROOT)
    assert plans.release_label(repo) == "R14"
    assert plans.plan_paths(repo)[0] == "docs/plans/r14-hardening.md"


# ---- 8 · layers ----------------------------------------------------------------------------------
def test_every_r14_package_has_its_layer() -> None:
    assert LAYER_OF["backup"] == "L7"
    assert LAYER_OF["skills"] == "L5"
    assert (LAYER_OF["selfwatch"], LAYER_OF["hardening"]) == ("X", "X")


# ---- 5 · settings and the drill database lock ----------------------------------------------------
def test_the_r14_settings_have_safe_defaults() -> None:
    s = Settings(_env_file=None)
    assert s.selfwatch_enabled is True
    assert (s.selfwatch_fail_streak, s.selfwatch_errors_per_hour) == (3, 30)
    assert (s.selfwatch_brief_grace_min, s.selfwatch_spike_factor) == (60, 3.0)
    assert s.selfwatch_spike_min_inr == 50 and s.cloud_run_revision is None
    assert s.backup_checks_enabled is True and s.backup_max_age_h == 36
    assert s.backup_drill_enabled is True and s.backup_drill_day == 1
    assert (s.backup_drill_max_inr, s.backup_drill_manual_per_month) == (100, 2)
    assert s.tool_offer == "by_skill" and s.tool_offer_sticky_s == 300
    assert s.history_tool_result_chars == 2_000
    assert s.cache_history is True and s.token_ledger_enabled is True
    assert s.bill_pay_cap_inr == 1_00_000


@pytest.mark.parametrize(
    ("field", "bad"),
    [
        ("selfwatch_fail_streak", 1),
        ("selfwatch_fail_streak", 11),
        ("selfwatch_errors_per_hour", 4),
        ("selfwatch_errors_per_hour", 501),
        ("selfwatch_brief_grace_min", 14),
        ("selfwatch_brief_grace_min", 241),
        ("selfwatch_spike_factor", 1.4),
        ("selfwatch_spike_factor", 10.5),
        ("selfwatch_spike_min_inr", 9),
        ("selfwatch_spike_min_inr", 1_001),
        ("backup_max_age_h", 24),
        ("backup_max_age_h", 201),
        ("backup_drill_day", 0),
        ("backup_drill_day", 29),
        ("backup_drill_max_inr", 9),
        ("backup_drill_max_inr", 1_001),
        ("backup_drill_manual_per_month", -1),
        ("backup_drill_manual_per_month", 5),
        ("tool_offer", "some"),
        ("tool_offer_sticky_s", -1),
        ("tool_offer_sticky_s", 3_601),
        ("history_tool_result_chars", 499),
        ("history_tool_result_chars", 12_001),
        ("bill_pay_cap_inr", 0),
        ("bill_pay_cap_inr", 1_00_001),
    ],
)
def test_an_r14_setting_outside_its_range_is_refused(field: str, bad: object) -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, **{field: bad})


def test_the_live_database_can_never_be_the_drill_copy() -> None:
    assert DRILL_DB == "jarvis-drill"
    with pytest.raises(ValidationError, match="jarvis-drill"):
        Settings(_env_file=None, firestore_database=DRILL_DB)  # D4 lock 5


def test_cloud_runs_revision_is_read_from_its_own_variable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("K_REVISION", "jarvis-00042-abc")
    assert Settings(_env_file=None).cloud_run_revision == "jarvis-00042-abc"


@pytest.mark.parametrize(
    ("database", "live"),
    [("(default)", "(default)"), ("jarvis", "jarvis"), ("other", "(default)"), ("", "(default)")],
)
def test_the_drill_adapters_refuse_any_database_but_the_drill_copy(
    database: str, live: str
) -> None:
    with pytest.raises(LiveTargetRefused):
        drill_target(database, live=live)


def test_the_drill_copy_is_the_one_target_and_never_the_live_one() -> None:
    assert drill_target(DRILL_DB, live="(default)") == DRILL_DB
    with pytest.raises(LiveTargetRefused):
        drill_target(DRILL_DB, live=DRILL_DB)  # a live database restored into that id
    assert NOT_SET_UP.set_up is False and NOT_SET_UP.size_bytes is None


# ---- 2 · alert kinds and every table that names one ----------------------------------------------
def test_nine_kinds_make_fifty_two() -> None:
    every = get_args(AlertKind)
    assert R14_ALERT_KINDS == (*SELF, "selfwatch_ok", "backup_ok")
    assert len(every) == len(set(every)) == 52 and set(DEFAULT_URGENCY) == set(every)
    assert all(DEFAULT_URGENCY[k] == "important" for k in SELF)
    assert DEFAULT_URGENCY["selfwatch_ok"] == DEFAULT_URGENCY["backup_ok"] == "info"
    assert set(SELF) <= DAYTIME_RING_KINDS  # held in quiet hours, never dropped like a nudge
    assert not set(SELF) & EPHEMERAL_KINDS
    assert SELF_KINDS == frozenset(SELF)
    assert SOFT_URGENT_KINDS == frozenset({"health_fault", "vitals_critical"})  # unchanged


def test_the_held_words_the_alerts_card_the_book_and_push_know_every_new_kind() -> None:
    js = _text(STATIC / "console-alerts.js")
    for kind in (*R14_ALERT_KINDS, "health_fault", "vitals_critical"):
        assert f"['{kind}'," in js, kind
        assert "(1 alert)" not in summary([{"kind": kind}]), kind  # its own held words
    for kind in R14_ALERT_KINDS:
        assert kind in ALERT_WORDS, kind
        assert TARGETS[kind] == "vitals", kind
    assert "backup" in summary([{"kind": "backup_problem"}]).lower()
    assert "system" in summary([{"kind": "health_fault"}]).lower()


def _ring(kind: str, subject: str | None = None) -> Signal:
    return Signal(source="system", kind=kind, subject=subject)  # type: ignore[arg-type]


def test_self_health_rings_have_their_own_soft_cap() -> None:
    storm, t0 = Storm(), datetime(2026, 11, 14, 10, 0, tzinfo=UTC)
    ring = Decision(action="ring", reason="daytime", urgency="important")
    got = [
        storm.admit("owner", _ring(kind), ring, t0 + timedelta(minutes=i)).admit
        for i, kind in enumerate(SELF)
    ]
    assert got == [True] * MAX_SELF_PER_HOUR + [False] * (len(SELF) - MAX_SELF_PER_HOUR)
    assert MAX_SELF_PER_HOUR == 3
    # one per kind and subject per 30 minutes, even under the hourly cap
    later = t0 + timedelta(hours=2)
    assert storm.admit("owner", _ring("clock_stopped", "w"), ring, later).admit
    assert not storm.admit(
        "owner", _ring("clock_stopped", "w"), ring, later + timedelta(minutes=29)
    ).admit
    assert storm.admit(
        "owner", _ring("clock_stopped", "t"), ring, later + timedelta(minutes=29)
    ).admit
    # their own table: a systems-check ring is still admitted after three self-health rings
    assert storm.admit(
        "owner", _ring("health_fault", "brain"), ring, t0 + timedelta(minutes=9)
    ).admit


def test_a_self_health_ring_that_reached_no_channel_gives_its_slot_back() -> None:
    storm, t0 = Storm(), datetime(2026, 11, 14, 10, 0, tzinfo=UTC)
    ring = Decision(action="ring", reason="daytime", urgency="important")
    sig = _ring("spend_spike", "day")
    assert storm.admit("owner", sig, ring, t0).admit
    storm.rollback("owner", sig, t0)
    assert storm.admit("owner", sig, ring, t0 + timedelta(minutes=1)).admit


# ---- 3 · the key purpose -------------------------------------------------------------------------
def test_one_key_purpose_makes_twenty_two() -> None:
    assert keyring.PURPOSES[-1] == "backup_probe"
    assert len(keyring.PURPOSES) == len(set(keyring.PURPOSES)) == 22


# ---- 4 · permissions: no new row, the new tools in their rows, the words ------------------------
def test_no_row_is_added_and_the_new_tools_fall_into_theirs() -> None:
    assert len({g.id for g in GROUPS}) == len(GROUPS) == 49
    assert {g.id for g in groups_for("vitals_backups", R1)} == {"vitals"}
    assert {g.id for g in groups_for("vitals_drill_start", R2)} == {"vitals_change"}
    assert {g.id for g in groups_for("maint_service_request", R1)} == {"household"}
    assert {g.id for g in groups_for("skills_open", R1)} == set()  # the risk default applies


@pytest.mark.parametrize(
    "tool", ["vitals_backups", "vitals_drill_start", "skills_open", "maint_service_request"]
)
def test_the_new_tools_are_open_on_telegram(tool: str) -> None:
    from fnmatch import fnmatchcase

    from jarvis.telegram import rules

    every = (*rules.PRIVATE_PATTERNS, *rules.PERSONAL_PATTERNS, *rules.HOME_PATTERNS)
    every += rules.BOTH_PATTERNS
    assert not any(fnmatchcase(tool, pattern) for pattern in every)  # "open" (D11's class)


def test_the_vitals_rows_name_the_backups_and_the_drill() -> None:
    show, change = get_group("vitals"), get_group("vitals_change")
    assert show is not None and change is not None
    assert "backups" in show.hint.lower()
    assert "drill" in change.hint.lower() and "₹" in change.hint


# ---- 6 · the contract and the ports --------------------------------------------------------------
def test_the_four_parts_and_what_each_owns() -> None:
    assert PARTS == ("backup", "selfwatch", "skills", "noai")
    assert set(TOOL_FAMILIES) == set(ROUTE_PREFIX) == set(COLLECTIONS) == set(PARTS)
    assert tool_allowed("backup", "vitals_backups") and tool_allowed("backup", "vitals_drill_start")
    assert tool_allowed("skills", "skills_open")
    assert not tool_allowed("noai", "vitals_backups") and not tool_allowed("selfwatch", "x")
    assert R14_JOB_NAMES == ("backup_canary", "backup_drill", "selfwatch_daily", "selfwatch_clock")
    assert {JOB_OWNER[j] for j in R14_JOB_NAMES} == {"backup", "selfwatch"}
    assert set(STATUS_ROUTE) == {"backup", "selfwatch", "skills"} and R14_STATUS_ROUTE == "/v1/r14"
    every = [c for p in PARTS for c in COLLECTIONS[p]]
    assert len(every) == len(set(every))
    for name in ("backup_canary", "backup_status", "backup_drill", "backup_drills", "selfwatch"):
        assert name in COLLECTIONS["backup"] + COLLECTIONS["selfwatch"], name
    assert COLLECTIONS["skills"] == ("token_ledger",)
    assert SERVICE_OWNER["backup_status"] == "backup" and SERVICE_OWNER["offer"] == "skills"
    assert SERVICE_OWNER["log_handler"] == SERVICE_OWNER["tick_observer"] == "selfwatch"
    assert set(VITALS_IDS) == {"backups", "backup_drill", "db_size", "clocks", "ai_parts"}


def test_the_eleven_skills_have_ids_and_labels() -> None:
    assert len(SKILL_IDS) == len(set(SKILL_IDS)) == 11
    assert set(SKILL_LABELS) == set(SKILL_IDS)
    assert SKILL_LABELS["health"] == "Health & Wellbeing"
    assert "Knowledge Base & Memory" not in SKILL_LABELS.values()


# ---- 7 · the tick observer's outcomes ------------------------------------------------------------
class _Job:
    def __init__(self, name: str, how: str, budget_s: float = 5.0) -> None:
        self.name, self.how, self.budget_s = name, how, budget_s

    async def run(self, owners: Sequence[str]) -> dict[str, int]:
        if self.how == "boom":
            raise RuntimeError("never in a log")
        if self.how == "slow":
            await asyncio.sleep(1.0)
        return {"failed": 1} if self.how == "some" else {"done": 1}


async def test_the_observer_hears_every_outcome_with_its_reason() -> None:
    seen: list[ticks.JobOutcome] = []
    jobs = [_Job("a", "ok"), _Job("b", "boom"), _Job("c", "slow", 0.05), _Job("d", "some")]
    got = await ticks.run_jobs(jobs, (), observer=seen.append, clock="watchdog")
    assert got == {"a": "ok", "b": "failed", "c": "failed", "d": "failed"}
    assert [(o.clock, o.name, o.outcome) for o in seen] == [
        ("watchdog", "a", "ok"),
        ("watchdog", "b", "failed"),
        ("watchdog", "c", "timed_out"),
        ("watchdog", "d", "failed"),
    ]
    assert all(o.seconds >= 0 for o in seen)


async def test_a_job_the_tick_has_no_time_for_is_skipped_never_failed_to_the_observer() -> None:
    seen: list[ticks.JobOutcome] = []
    got = await ticks.run_jobs([_Job("late", "ok")], (), total_budget_s=0, observer=seen.append)
    assert got == {"late": "failed"}  # the tick answer is unchanged
    assert [(o.clock, o.outcome) for o in seen] == [("tick", "skipped")]


async def test_an_observer_that_raises_never_stops_the_jobs() -> None:
    def bad(_: ticks.JobOutcome) -> None:
        raise RuntimeError("observer")

    assert await ticks.run_jobs([_Job("a", "ok"), _Job("b", "ok")], (), observer=bad) == {
        "a": "ok",
        "b": "ok",
    }
    ticks.report(bad, ticks.JobOutcome("tick", "memory", "ok", 0.0))  # never raises


# ---- 7 · the brain's two slots -------------------------------------------------------------------
def _req(text: str = "hello") -> Any:
    return SimpleNamespace(user_id="owner", message=text)


def test_the_brain_offers_every_tool_until_part_c_fills_its_slot() -> None:
    specs = [fake_spec("a"), fake_spec("b")]
    assert BrainSlots().tools(_req(), [], specs) == specs
    assert offer_all(None, specs) == specs  # type: ignore[arg-type]


def test_an_offer_that_breaks_gives_every_tool_and_one_never_adds_an_unknown_tool() -> None:
    specs = [fake_spec("a"), fake_spec("b")]

    def boom(ctx: Any, given: Sequence[Any]) -> list[Any]:
        raise RuntimeError("offer")

    assert BrainSlots(offer=boom).tools(_req(), [], specs) == specs
    narrow = BrainSlots(offer=lambda ctx, given: [fake_spec("zzz"), given[1]])
    assert [s.name for s in narrow.tools(_req("x"), [], specs)] == ["b"]
    empty = BrainSlots(offer=lambda ctx, given: [])
    assert empty.tools(_req(), [], specs) == specs  # never a turn with no tools by mistake


async def test_the_ledger_slot_never_breaks_a_reply() -> None:
    class Bad:
        async def record(self, call: LedgerCall) -> None:
            raise RuntimeError("ledger")

    seen: list[LedgerCall] = []

    class Good:
        async def record(self, call: LedgerCall) -> None:
            seen.append(call)

    call = LedgerCall("owner", "mock", "sys", "trailer", (), (), completion=None)
    await BrainSlots().record(call)
    await BrainSlots(ledger=Bad()).record(call)
    await BrainSlots(ledger=Good()).record(call)
    assert seen == [call]


def test_the_brain_has_its_two_slots_and_no_third() -> None:
    brain = _text(SRC / "core" / "brain.py")
    assert "self.slots.tools(" in brain and "await self.slots.record(" in brain
    assert "cache_hint" not in brain  # A1: the provider applies `cache_history` itself
    assert _lines(SRC / "core" / "brain.py") <= 741


# ---- 6, 7 · the stub parts, their routes and the wiring ------------------------------------------
async def test_the_app_starts_with_four_parts_and_their_status_routes(settings: Settings) -> None:
    async with running(settings) as (app, client):
        parts = app.state.r14_parts
        assert list(parts) == list(PARTS)
        assert all(isinstance(p, HardeningPart) and p.name == n for n, p in parts.items())
        # I1: all four parts are built; their words in the dev app (MemoryDocs, no Firestore)
        built = {
            "backup": "off: not on Firestore",  # A: the real adapters only on Firestore
            "selfwatch": "on",  # B
            "skills": "ready",  # C
            "noai": "ready",  # D
        }
        assert {n: p.ready for n, p in parts.items()} == built
        for name, route in STATUS_ROUTE.items():
            r = await client.get(route)
            assert r.status_code == 200, name
            assert {k: r.json()[k] for k in ("part", "ready")} == {
                "part": name,
                "ready": built[name],
            }
            assert r.headers["cache-control"] == "no-store"
        r = await client.get(R14_STATUS_ROUTE)
        assert r.json() == {"parts": built}
        ledger = await client.get("/v1/costs/ledger")
        assert ledger.status_code == 200 and ledger.json()["part"] == "skills"
        drill = await client.post("/v1/backup/drill", json={}, headers={"X-Requested-With": "x"})
        assert drill.status_code == 409 and drill.json()["error"] == "no_conversation"
        assert isinstance(app.state.brain.slots, BrainSlots)


async def test_the_new_routes_need_the_owner(settings: Settings) -> None:
    s = settings.model_copy(update={"env": "prod"})
    s = s.model_copy(update={"api_token": __import__("pydantic").SecretStr("t" * 32)})
    async with running(s) as (_, client):
        for route in (*STATUS_ROUTE.values(), R14_STATUS_ROUTE, "/v1/costs/ledger"):
            assert (await client.get(route)).status_code == 401, route


def test_the_wiring_files_have_their_slots() -> None:
    app_py = _text(SRC / "api" / "app.py")
    for needle in (
        "import jarvis.api.r14_wiring as r14",
        "await r14.wire_r14(app, s, docs, audit)",
        "r14.install_r14_routes(app)",
        "r14=r14.r14_tools(app.state.r14_parts)",
        "finish_wiring(app)",
    ):
        assert needle in app_py, needle
    assert "def _tick_jobs" not in app_py  # moved to api/tick_wiring.py
    assert app_py.index("await wire_r11(") < app_py.index("await r14.wire_r14(")
    assert app_py.index("await r14.wire_r14(") < app_py.index("_wire_gateway(app, s, inj")
    assert "r14: Sequence[Tool] = ()" in _text(SRC / "tools" / "setup.py")
    assert "r14_privacy_sources(app)" in _text(SRC / "api" / "personal.py")
    assert "r14=" in _text(SRC / "api" / "selfcheck_wiring.py")
    ticks_py = _text(SRC / "api" / "tick_wiring.py")
    assert "*r14.r14_tick_jobs(app)" in ticks_py
    assert "observer=" in _text(SRC / "api" / "brief.py")
    guard = _text(ROOT / "tests" / "test_telegram_tool_guard.py")
    assert "r14=r14_tools(" in guard


def test_the_line_budgets_hold() -> None:
    assert _lines(SRC / "api" / "app.py") <= 735
    assert _lines(SRC / "tools" / "gateway.py") <= 760
    assert _lines(STATIC / "console.html") <= 782
    assert _lines(SRC / "config.py") < 800
    for js in STATIC.glob("console*.js"):
        assert _lines(js) <= 800, js.name
    for path in (SRC / "hardening", SRC / "backup", SRC / "selfwatch", SRC / "skills"):
        for py in path.glob("*.py"):
            assert _lines(py) <= 400, py


# ---- D7 · one 5-minute clock, for the brief's owners, selfwatch first ----------------------------
async def test_the_clock_jobs_run_for_the_briefs_owners_with_selfwatch_first(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    watch = RecordingJob("selfwatch_clock")
    real = wiring._build

    def build(name: str, ctx: Any) -> HardeningPart:
        if name == "selfwatch":
            return HardeningPart("selfwatch", clock_jobs=(watch,))
        return real(name, ctx)

    monkeypatch.setattr(wiring, "_build", build)
    s = settings.model_copy(update={"owner_emails": ["owner@example.com"], "vitals_enabled": True})
    async with running(s) as (app, _):
        jobs = app.state.clock_jobs
        assert jobs[0].name == "selfwatch_clock"
        names = [j.name for j in jobs]
        assert "health_check" in names and len(names) == len(set(names))
        assert getattr(app.state, "home_watchdog", None) is None  # Home is off here
        request = SimpleNamespace(app=app)
        from jarvis.api.home import _clock_only

        out = await _clock_only(request)  # type: ignore[arg-type]
        assert out["jobs"]["selfwatch_clock"] == "ok"
        owners = tuple(app.state.brief.owners)
        assert watch.owners == [owners] and owners and owners != ("",)


async def test_with_home_on_the_watchdog_runs_selfwatch_before_the_laptop_check() -> None:
    from jarvis.home.watchdog import ADVISORY_JOBS, Watchdog

    assert "selfwatch_clock" in ADVISORY_JOBS
    first, later = RecordingJob("selfwatch_clock"), RecordingJob("health_check")
    order: list[str] = []
    first.order = later.order = order

    class Store:
        async def linked_uids(self) -> list[str]:
            return ["laptop-owner"]

    dog = Watchdog.__new__(Watchdog)
    dog._store = Store()  # type: ignore[attr-defined]
    dog._offline = RecordingJob("home_offline", order=order)  # type: ignore[attr-defined]
    dog._offline.last = {}  # type: ignore[attr-defined]
    dog._claims = RecordingJob("home_claims_sweep", order=order)  # type: ignore[attr-defined]
    dog._codes = RecordingJob("home_link_sweep", order=order)  # type: ignore[attr-defined]
    dog._claims.last = dog._codes.last = {}  # type: ignore[attr-defined]
    dog._extra, dog._first, dog._budget_s, dog.observer = (), (), 50.0, None  # type: ignore[attr-defined]
    dog.extend(later)
    dog.prepend(first)
    await dog.run()
    assert order[:2] == ["selfwatch_clock", "home_offline"] and order[-1] == "health_check"


def test_the_shared_clock_wrapper_serves_its_own_owners() -> None:
    inner = RecordingJob("health_check")
    job = tick_wiring.ForOwners(inner, lambda: ("owner",))
    assert (job.name, job.budget_s) == ("health_check", inner.budget_s)
    asyncio.run(job.run(("someone-else",)))
    assert inner.owners == [("owner",)]


# ---- 7 · the Vitals slot and the privacy slot ----------------------------------------------------
async def test_r14s_vitals_items_join_the_board_and_a_stray_id_is_dropped() -> None:
    from jarvis.vitals.own import Own, OwnSources, own_item

    async def items(uid: str, now: datetime, tz: ZoneInfo) -> list[Any]:
        return [
            own_item("backups", "ok", "", note="Last copy today at 03:12."),
            own_item("brain_claude", "red", "was refused"),  # not R14's: dropped
        ]

    reader = SimpleNamespace(items=items)
    own = Own(OwnSources(r14=lambda: reader), Settings(_env_file=None))
    got = await own.items("owner", datetime(2026, 11, 14, tzinfo=UTC), ZoneInfo("Asia/Kolkata"))
    assert [i.provider.id for i in got] == ["backups"]
    assert {"backups", "backup_drill", "clocks", "ai_parts"} <= own.quiet_ids()
    assert "db_size" not in own.quiet_ids()  # the size item alerts through Vitals (D5)


@pytest.mark.parametrize("pid", sorted(VITALS_IDS))
def test_every_r14_vitals_item_has_fixed_words(pid: str) -> None:
    from jarvis.vitals.own import LABELS
    from jarvis.vitals.words import words_for

    impact, fix = words_for(pid, LABELS[pid])
    assert impact.startswith("If this ") and fix, pid


async def test_the_parts_privacy_rows_reach_the_dashboard(settings: Settings) -> None:
    async with running(settings) as (app, _):
        # I1: A's "Backups" row, B's once-only claims, C's token ledger (D keeps nothing new)
        ids = [s.id for s in wiring.r14_privacy_sources(app)]
        assert ids == ["backups", "selfwatch_told", "token_ledger"]
        assert set(ids) <= set(app.state.privacy.registry.ids())


# ---- 8 · the guide's cards, built at I1 ----------------------------------------------------------
def _card(guide: str, card: str) -> str:
    start = guide.index(f"#### {card} · ")
    ends = [guide.find(mark, start + 1) for mark in ("\n#### ", "\n## ")]
    return guide[start : min(e for e in ends if e > 0)]


@pytest.mark.parametrize(
    ("card", "needles"),
    [
        (
            "C66",
            (
                "`src/jarvis/backup/`",
                "storage/firestore_admin.py`",
                "storage/firestore_walk.py`",
                "`GET /v1/backup`",
                "`vitals_drill_start`",
                "never with Approve all",
                "≈ ₹3.8 at 100 MB",
                "`backup_drills/{yyyymm}`",
            ),
        ),
        (
            "C67",
            (
                "`src/jarvis/selfwatch/`",
                "`GET /v1/selfwatch`",
                "`selfwatch_clock`",
                "`selfwatch_daily`",
                "`home_offline_idle`",
                "every 30 minutes, 6 times",
            ),
        ),
        (
            "C68",
            (
                "`catalogue.json` the data, shipped as package data",
                "`skills_open`",
                "`GET /v1/skills`",
                "`scripts/skill_coverage.py`",
                "chat replies",
                "`src/jarvis/offline/said.py`",
                "p14.0",
            ),
        ),
    ],
)
def test_the_guide_has_the_three_r14_cards_built_after_i1(
    card: str, needles: tuple[str, ...]
) -> None:
    body = _card(_text(GUIDE), card)
    assert "Built in R14" in body and "PLANNED" not in body  # I1 (was PLANNED at I0)
    for needle in needles:
        assert needle in body, (card, needle)


def test_the_guide_names_every_r14_collection_and_says_backups_exist() -> None:
    guide = _text(GUIDE)
    for name in (*COLLECTIONS["backup"], *COLLECTIONS["selfwatch"], *COLLECTIONS["skills"]):
        assert f"`{name}" in guide, name
    assert "**No backups.**" not in guide and "Firestore has no backups" not in guide  # D15
    assert "Restoring for real" in guide  # D4, the guide's section 8
    assert "within 7 days" in guide  # D3: a deleted thing leaves the copies within 7 days
    assert "| Skill | Knowledge Base & Memory |" not in guide  # D11: no such skill in the project


# ---- 9 · the eval runner and its gate ------------------------------------------------------------
def test_the_r14_runner_passes_and_its_contract_control_fails_it() -> None:
    env = {**os.environ, "PYTHONPATH": str(ROOT / "src")}
    run = subprocess.run(
        [sys.executable, str(ROOT / "evals" / "r14" / "run.py"), "--mock"],
        capture_output=True, text=True, env=env, timeout=300, check=False,
    )  # fmt: skip
    assert run.returncode == 0, run.stdout + run.stderr
    report = json.loads((ROOT / "evals" / "r14" / "report.json").read_text(encoding="utf-8"))
    ids = {r["id"] for r in report["results"]}
    # I1: A, B, C and D are built, each with its cases and a control that fails it
    for case in (
        "backup:drill_passes_on_fakes",
        "selfwatch:three_failures_one_alert",
        "offer:recall",
        "noai:row01_grocery_add",
    ):
        assert case in ids, case
    assert not any(i.endswith(":not_built_yet") for i in ids if not i.startswith("needles:"))
    assert all(r["passed"] for r in report["results"])
    control = report["negative_control"]
    assert control["suite_failed"] is True
    for part in ("contract", "backup", "selfwatch", "offer", "noai"):
        assert control["failed_cases"][part], part


def test_the_r14_suite_is_gated_in_run_all_mock() -> None:
    text = _text(ROOT / "evals" / "run_all_mock.py")
    line = next(x for x in text.splitlines() if '"r14 (gated)"' in x)
    assert 'HERE / "r14" / "run.py"' in line and line.rstrip().endswith("True),")


# ---- 6 · the set-up script: --status only reads -----------------------------------------------
def _fake_gcloud(tmp_path: Path) -> tuple[Path, Path]:
    log = tmp_path / "calls.log"
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    gcloud = bin_dir / "gcloud"
    gcloud.write_text(f'#!/bin/sh\necho "$@" >> "{log}"\nexit 0\n', encoding="utf-8")
    gcloud.chmod(gcloud.stat().st_mode | stat.S_IEXEC)
    return bin_dir, log


def test_the_status_mode_only_reads_and_always_succeeds(tmp_path: Path) -> None:
    bin_dir, log = _fake_gcloud(tmp_path)
    env = {**os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}"}
    script = ROOT / "deploy" / "backup_setup.sh"
    run = subprocess.run(
        ["bash", str(script), "--status"], capture_output=True, text=True, env=env, check=False
    )
    assert run.returncode == 0, run.stderr
    assert "Backups" in run.stdout
    calls = log.read_text(encoding="utf-8") if log.exists() else ""
    for verb in ("create", "update", "delete", "add-iam-policy-binding", "remove-iam-policy"):
        assert verb not in calls, verb
    body = _text(script)
    status = body[body.index("status() {") : body.index("\n}\n", body.index("status() {"))]
    for verb in ("create", "update", "delete", "add-iam-policy-binding"):
        assert verb not in status, verb


def test_the_set_up_waits_for_yes(tmp_path: Path) -> None:
    bin_dir, log = _fake_gcloud(tmp_path)
    env = {**os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}"}
    run = subprocess.run(
        ["bash", str(ROOT / "deploy" / "backup_setup.sh")],
        input="no\n", capture_output=True, text=True, env=env, check=False,
    )  # fmt: skip
    assert run.returncode == 0
    assert not log.exists() or "create" not in log.read_text(encoding="utf-8")


# ---- the persona waits for I1; the brief for the builders ----------------------------------------
def _offer_bullets(prompt: str) -> list[str]:
    """Each persona bullet ("- ..." to the next bullet or a blank line) about an offered tool."""
    bullets = re.findall(r"^- .*?(?=^- |^\s*$|\Z)", prompt, flags=re.M | re.S)
    return [" ".join(b.split()) for b in bullets if "offered" in b]


def test_the_persona_opens_a_skill_while_the_offer_is_on_by_default() -> None:
    """R14 C code review MEDIUM-2 (INTEGRATION-C "Needs I1" A4): with `tool_offer` "by_skill" by
    default, every persona bullet about a tool that isn't offered sends the model to skills_open
    first (persona p14.0, D14)."""
    from jarvis.core.prompts import WIT_IDS, build_system_prompt

    if Settings.model_fields["tool_offer"].default != "by_skill":
        return  # the kill switch is the default: nothing to keep in step
    for wit in WIT_IDS:
        bullets = _offer_bullets(build_system_prompt(honorific="Sir", wit=wit))
        assert len(bullets) >= 5, bullets  # the rules, web, Drive, the tools rule, Maps/YouTube
        stale = [b[:70] for b in bullets if "skills_open" not in b]
        assert not stale, f"{wit}: {stale}"
    assert PERSONA_VERSION == "p14.0"


def test_the_common_brief_names_the_contract_the_guards_and_the_hook() -> None:
    brief = _text(INTEG / "BRIEF-COMMON.md")
    for needle in ("HardeningPart", "never `from tests.", "app.py", "760", "782", "guard.py"):
        assert needle in brief, needle
    assert "JARVIS-Version: v14.0.0" in brief and "JARVIS-Mark: XVIII" in brief
    assert (INTEG / "I0-NOTES.md").is_file()
