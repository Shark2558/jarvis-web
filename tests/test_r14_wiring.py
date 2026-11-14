# tests/test_r14_wiring.py -- R14 I0 (docs/plans/r14-hardening.md seam 7): the parts' one join,
# `api/r14_wiring.py`. A part that breaks its contract is left out ("setup failed") and the others
# still run; the services each part may offer (Part A's backup status, Part B's errors handler and
# tick observer, Part C's tool offer and token ledger, Part D's No-AI phrases) reach their one
# place; the logging handler is installed once and replaced, never stacked.
from __future__ import annotations

import logging
from collections.abc import Sequence
from typing import Any

import pytest
from fastapi import FastAPI
from r14_fakes import FakeBackupStatus, Outcomes, RecordingJob, facts

import jarvis.api.r14_wiring as wiring
from jarvis.config import Settings
from jarvis.core.guardrails import ActionRisk
from jarvis.hardening.ports import HardeningContext, HardeningPart
from jarvis.skills.ports import BrainSlots
from jarvis.ticks import JobOutcome
from jarvis.tools.base import Tool


def _tool(name: str) -> Tool:
    async def run(_: dict[str, object]) -> str:
        return "ok"

    return Tool(
        name, "a test tool", {"type": "object", "properties": {}}, ActionRisk.READ_ONLY, run
    )


def _ctx(app: FastAPI, s: Settings) -> HardeningContext:
    return HardeningContext(s=s, docs=None, audit=None, state=lambda n: getattr(app.state, n, None))


def test_a_part_that_breaks_its_contract_is_left_out_and_the_rest_stay(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    def build(name: str, ctx: HardeningContext) -> HardeningPart:
        if name == "backup":
            return HardeningPart("backup", tools=(_tool("skills_open"),))  # C's tool
        if name == "selfwatch":
            raise RuntimeError("boom")
        if name == "skills":
            return HardeningPart("skills", services={"backup_status": FakeBackupStatus()})
        return HardeningPart("noai", daily_jobs=(RecordingJob("backup_drill"),))  # A's job

    monkeypatch.setattr(wiring, "_build", build)
    parts = wiring.build_parts(_ctx(FastAPI(), settings))
    assert [p.ready for p in parts.values()] == [wiring.SETUP_FAILED] * 4
    assert wiring.r14_tools(parts) == () and wiring.r14_tools(None) == ()


@pytest.mark.parametrize(
    "part",
    [
        HardeningPart("selfwatch", clock_jobs=(RecordingJob("helpers_clock"),)),  # not R14's
        HardeningPart("backup", clock_jobs=(RecordingJob("backup_canary"),)),  # daily, not clock
        HardeningPart("selfwatch", daily_jobs=(RecordingJob("selfwatch_clock"),)),  # clock only
    ],
)
def test_jobs_are_named_and_placed_as_the_plan_says(part: HardeningPart) -> None:
    with pytest.raises(ValueError, match="job"):
        wiring.check_part(part.name, part)


def test_a_part_must_return_its_own_name() -> None:
    with pytest.raises(ValueError, match="must return"):
        wiring.check_part("backup", HardeningPart("skills"))
    with pytest.raises(ValueError, match="must return"):
        wiring.check_part("backup", object())


def test_a_good_part_keeps_its_tools_jobs_and_services(settings: Settings) -> None:
    status = FakeBackupStatus(facts(set_up=True, size_bytes=10))
    part = HardeningPart(
        "backup",
        tools=(_tool("vitals_backups"), _tool("vitals_drill_start")),
        daily_jobs=(RecordingJob("backup_canary"), RecordingJob("backup_drill")),
        services={"backup_status": status},
        ready="ok",
    )
    assert wiring.check_part("backup", part) is part
    app = FastAPI()
    app.state.r14_parts = {"backup": part}
    assert [t.name for t in wiring.r14_tools(app.state.r14_parts)] == [
        "vitals_backups",
        "vitals_drill_start",
    ]
    assert [j.name for j in wiring.r14_tick_jobs(app)] == ["backup_canary", "backup_drill"]
    assert wiring.backup_status(app) is status


def test_without_part_a_there_is_no_backup_status() -> None:
    app = FastAPI()
    assert wiring.backup_status(app) is None
    app.state.r14_parts = {"backup": HardeningPart("backup")}
    assert wiring.backup_status(app) is None


async def test_the_observer_reaches_the_tick_and_the_watchdog(settings: Settings) -> None:
    heard = Outcomes()
    app = FastAPI()
    app.state.r14_parts = {
        "selfwatch": HardeningPart("selfwatch", services={"tick_observer": heard})
    }
    wiring.install_services(app)
    assert app.state.tick_observer is heard
    app.state.tick_observer(JobOutcome("tick", "memory", "ok", 0.0))
    assert heard.names() == ["memory"]


def test_the_errors_handler_is_installed_once_and_replaced_never_stacked() -> None:
    root = logging.getLogger()
    before = list(root.handlers)
    first, second = logging.NullHandler(), logging.NullHandler()
    try:
        for handler in (first, first, second):
            app = FastAPI()
            app.state.r14_parts = {
                "selfwatch": HardeningPart("selfwatch", services={"log_handler": handler})
            }
            wiring.install_services(app)
        assert second in root.handlers and first not in root.handlers
        assert len(root.handlers) == len(before) + 1
    finally:
        wiring.install_log_handler(None)
    assert root.handlers == before


async def test_the_brain_gets_part_cs_offer_unless_the_kill_switch_says_all(
    settings: Settings,
) -> None:
    def offer(ctx: Any, specs: Sequence[Any]) -> list[Any]:
        return list(specs)[:1]

    class Ledger:
        async def record(self, call: Any) -> None:
            return None

    ledger = Ledger()
    for setting, want in (("by_skill", offer), ("all", None)):
        app = FastAPI()
        app.state.settings = settings.model_copy(update={"tool_offer": setting})
        app.state.brain = type("B", (), {"slots": BrainSlots()})()
        app.state.r14_parts = {
            "skills": HardeningPart("skills", services={"offer": offer, "ledger": ledger})
        }
        wiring.bind_brain(app)
        assert app.state.brain.slots.offer is want, setting
        assert app.state.brain.slots.ledger is ledger


def test_the_ledger_is_left_off_when_its_setting_is(settings: Settings) -> None:
    class Ledger:
        async def record(self, call: Any) -> None:
            return None

    app = FastAPI()
    app.state.settings = settings.model_copy(update={"token_ledger_enabled": False})
    app.state.brain = type("B", (), {"slots": BrainSlots()})()
    app.state.r14_parts = {"skills": HardeningPart("skills", services={"ledger": Ledger()})}
    wiring.bind_brain(app)
    assert app.state.brain.slots.ledger is None


def test_part_ds_phrases_go_into_no_ai_mode_one_at_a_time(settings: Settings) -> None:
    class Mode:
        def __init__(self) -> None:
            self.phrases: list[Any] = []

        def add_phrases(self, routers: Sequence[Any]) -> None:
            for r in routers:
                if r is bad:
                    raise ValueError("does not fit")
                self.phrases.append(r)

    def good(text: str) -> None:
        return None

    def bad(text: str) -> None:
        return None

    app = FastAPI()
    app.state.brain_mode = Mode()
    app.state.r14_parts = {"noai": HardeningPart("noai", services={"phrases": (bad, good)})}
    wiring.install_r14_phrases(app)
    wiring.install_r14_phrases(app)  # twice: never added again
    assert app.state.brain_mode.phrases == [good]


async def test_the_vitals_reader_asks_every_part_and_survives_one_that_breaks() -> None:
    from datetime import UTC, datetime
    from zoneinfo import ZoneInfo

    from jarvis.vitals.own import own_item

    async def good(uid: str, now: datetime, tz: ZoneInfo) -> list[Any]:
        return [own_item("clocks", "ok", "", note="Both clocks are running.")]

    async def broken(uid: str, now: datetime, tz: ZoneInfo) -> list[Any]:
        raise RuntimeError("vitals")

    parts = {
        "backup": HardeningPart("backup", vitals=(broken,)),
        "selfwatch": HardeningPart("selfwatch", vitals=(good,)),
    }
    got = await wiring.R14Vitals(parts).items(
        "owner", datetime(2026, 11, 14, tzinfo=UTC), ZoneInfo("Asia/Kolkata")
    )
    assert [i.provider.id for i in got] == ["clocks"]
