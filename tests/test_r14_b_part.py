# tests/test_r14_b_part.py -- R14 Part B's join (`selfwatch.part.build`), its route
# `GET /v1/selfwatch` (names and counts only), its Vitals item `clocks` and its privacy row.
from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from r14_fakes_b import UID, BrokenDocs, FlakyJob, build_world

import jarvis.api.r14_wiring as wiring
from jarvis.api import create_app
from jarvis.config import Settings
from jarvis.hardening.ports import HardeningContext, HardeningPart
from jarvis.llm.mock_provider import MockProvider
from jarvis.memory.inmemory import InMemorySessionStore
from jarvis.privacy.ports import CategoryView, PrivacySource
from jarvis.selfwatch import part as part_mod
from jarvis.selfwatch.clocks import ClockState
from jarvis.selfwatch.errors import ErrorCounter
from jarvis.selfwatch.jobs import CLOCK_NAME, DAILY_NAME
from jarvis.selfwatch.status import READY, Status, ToldPrivacy
from jarvis.selfwatch.vitals import clocks_item
from jarvis.storage.docs import MemoryDocs

IST = ZoneInfo("Asia/Kolkata")


def ist(day: int, hh: int, mm: int = 0) -> datetime:
    return datetime(2026, 11, day, hh, mm, tzinfo=IST).astimezone(UTC)


def _ctx(s: Settings, docs: Any = None, state: dict[str, Any] | None = None) -> HardeningContext:
    st = state or {}
    return HardeningContext(s=s, docs=docs, audit=None, state=st.get)


# ---- the part ------------------------------------------------------------------------------------
def test_the_part_offers_its_two_jobs_its_two_services_and_passes_the_contract(
    settings: Settings,
) -> None:
    part = part_mod.build(_ctx(settings, MemoryDocs()))
    assert wiring.check_part("selfwatch", part) is part
    assert part.ready == READY and part.tools == ()
    assert [j.name for j in part.clock_jobs] == [CLOCK_NAME]
    assert [j.name for j in part.daily_jobs] == [DAILY_NAME]
    assert callable(part.services["tick_observer"])
    assert isinstance(part.services["log_handler"], ErrorCounter)
    assert isinstance(part.services["status"], Status)
    assert len(part.vitals) == 1 and len(part.privacy) == 1
    assert isinstance(part.privacy[0], PrivacySource)


def test_switched_off_it_offers_nothing(settings: Settings) -> None:
    part = part_mod.build(_ctx(settings.model_copy(update={"selfwatch_enabled": False})))
    assert part == HardeningPart("selfwatch", ready=part_mod.OFF)


def test_without_a_document_store_it_still_watches_in_memory(settings: Settings) -> None:
    part = part_mod.build(_ctx(settings, None))
    assert part.ready == READY and part.clock_jobs


async def test_it_reads_the_brief_billing_and_notifier_late(settings: Settings) -> None:
    state: dict[str, Any] = {}
    w = build_world()
    ctx = HardeningContext(
        s=settings, docs=MemoryDocs(), audit=None, state=state.get, notifier=lambda: w.ring
    )
    part = part_mod.build(ctx)
    state["brief"] = w.brief  # built after the part, read at run time
    local = datetime.now(IST)  # the part runs on the real clock
    w.brief.date, w.brief.due_at = local.date().isoformat(), local + timedelta(hours=2)
    job = part.clock_jobs[0]
    for _ in range(2):
        await job.run((UID,))
    assert w.brief.calls == 1  # read late, at run time, and once (its time is still ahead)


# ---- the status view -----------------------------------------------------------------------------
async def test_the_status_names_and_counts_only() -> None:
    w = build_world()
    await w.watchdog(FlakyJob("vault_reminders"))
    await w.watchdog(FlakyJob("vault_reminders"))
    logging.getLogger("jarvis.x")  # nothing logged: zero errors
    got = await Status(w.watch).view()
    assert set(got) == {"clocks", "jobs", "errors_today", "unrecorded", "deploy", "version"}
    assert got["unrecorded"] == {"errors": 0, "outcomes": 0}
    assert got["clocks"]["watchdog"] is not None and got["clocks"]["tick"] is None
    assert got["jobs"] == [
        {"name": "vault_reminders", "runs": 2, "since": got["jobs"][0]["since"], "told": False}
    ]
    assert got["errors_today"] == 0 and got["version"] == "14.0.0"
    assert "secret" not in str(got)


async def test_the_status_shows_what_the_handler_and_the_observer_could_not_count() -> None:
    w = build_world()
    rec = logging.LogRecord("jarvis.web", logging.ERROR, __file__, 1, "x", (), None)
    rec.created = float("nan")
    w.watch.errors.handle(rec)
    w.watch.observe(object())  # type: ignore[arg-type]
    got = await Status(w.watch).view()
    assert got["unrecorded"] == {"errors": 1, "outcomes": 1}  # silent review L1, L2


async def test_the_status_says_what_it_can_with_the_store_down() -> None:
    w = build_world(docs=BrokenDocs())
    got = await Status(w.watch).view()
    assert got["errors_today"] is None and got["deploy"] == {}


# ---- the Vitals item -----------------------------------------------------------------------------
def test_both_clocks_running_is_ok() -> None:
    now = ist(16, 9, 0)
    item = clocks_item(ClockState(tick=ist(16, 8, 30), watchdog=ist(16, 8, 57)), now, IST)
    assert item.provider.id == "clocks" and item.base == ("ok", "are running")
    assert "3 minutes ago" in item.provider.note and "08:30" in item.provider.note


def test_both_clocks_stopped_is_red_with_the_time() -> None:
    now = ist(16, 9, 0)
    item = clocks_item(ClockState(tick=ist(15, 11, 30), watchdog=ist(16, 2, 10)), now, IST)
    assert item.base == ("red", "have stopped")
    assert item.provider.note == "Clocks stopped since 16 Nov, 02:10."


def test_one_clock_stopped_is_amber() -> None:
    now = ist(16, 9, 0)
    dog = clocks_item(ClockState(tick=ist(16, 8, 30), watchdog=ist(16, 7, 0)), now, IST)
    tick = clocks_item(ClockState(tick=ist(15, 9, 0), watchdog=ist(16, 8, 58)), now, IST)
    assert dog.base[0] == tick.base[0] == "amber"
    assert "5-minute clock" in dog.provider.note and "morning clock" in tick.provider.note


def test_clocks_not_seen_yet_are_unknown_and_a_morning_before_the_first_tick_is_fine() -> None:
    now = ist(16, 14, 0)
    assert clocks_item(ClockState(), now, IST).base[0] == "unknown"
    fresh = clocks_item(ClockState(watchdog=ist(16, 13, 58)), now, IST)
    assert fresh.base[0] == "ok" and "hasn't run yet" in fresh.provider.note


def test_a_morning_clock_that_never_ran_by_its_time_is_amber_not_ok() -> None:
    s = ClockState(watchdog=ist(17, 8, 58), first_seen=ist(16, 14, 0))
    item = clocks_item(s, ist(17, 9, 0), IST)
    assert item.base == ("amber", "one has stopped")  # code review L1
    assert "morning clock" in item.provider.note


def test_a_five_minute_clock_that_never_ran_is_amber_after_an_hour() -> None:
    s = ClockState(tick=ist(16, 8, 30), first_seen=ist(16, 7, 0))
    item = clocks_item(s, ist(16, 9, 0), IST)
    assert item.base == ("amber", "one has stopped")
    assert "5-minute clock hasn't run" in item.provider.note
    fresh = clocks_item(ClockState(tick=ist(16, 8, 30), first_seen=ist(16, 8, 30)), ist(16, 9), IST)
    assert fresh.base[0] == "ok"


def test_clocks_with_only_a_first_seen_are_red_not_a_crash() -> None:
    item = clocks_item(ClockState(first_seen=ist(15, 9, 0)), ist(16, 9, 0), IST)
    assert item.base == ("red", "have stopped")


async def test_the_vitals_reader_reads_the_stored_clocks() -> None:
    w = build_world(now=ist(16, 9, 0))
    await w.watchdog()
    (read,) = part_mod.vitals_of(w.watch)
    (item,) = await read(UID, ist(16, 9, 1), IST)
    assert item.provider.id == "clocks" and item.base[0] == "ok"


# ---- the privacy row -----------------------------------------------------------------------------
async def test_the_privacy_row_counts_the_owners_claims_only() -> None:
    w = build_world()
    await w.watch.told.claim(UID, "brief_missed", "a", w.clock())
    await w.watch.told.claim("owner-2", "brief_missed", "a", w.clock())
    row = ToldPrivacy(w.watch)
    view = await row.describe(UID)
    assert isinstance(view, CategoryView) and view.id == "selfwatch_told"
    assert view.count == 1 and view.retention == "30 days"
    assert view.export is False and view.delete == "none"
    assert await row.export(UID) is None and await row.delete(UID) == 0


# ---- the app: the real wiring, the route ---------------------------------------------------------
@asynccontextmanager
async def running(s: Settings) -> AsyncIterator[tuple[FastAPI, AsyncClient]]:
    app = create_app(s, provider=MockProvider(), store=InMemorySessionStore())
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            yield app, c
    wiring.install_log_handler(None)  # leave the root logger as it was


async def test_in_the_app_the_route_answers_and_the_services_are_installed(
    settings: Settings,
) -> None:
    async with running(settings) as (app, client):
        part = app.state.r14_parts["selfwatch"]
        assert part.ready == READY
        assert app.state.tick_observer == part.services["tick_observer"]
        assert part.services["log_handler"] in logging.getLogger().handlers
        assert app.state.clock_jobs[0].name == CLOCK_NAME
        r = await client.get("/v1/selfwatch")
        assert r.status_code == 200 and r.headers["cache-control"] == "no-store"
        body = r.json()
        assert body["part"] == "selfwatch" and body["ready"] == READY
        assert {"clocks", "jobs", "errors_today", "deploy", "version"} <= set(body)
        assert "selfwatch_told" in app.state.privacy.registry.ids()


async def test_the_route_needs_the_owner(settings: Settings) -> None:
    s = settings.model_copy(update={"env": "prod"})
    s = s.model_copy(update={"api_token": __import__("pydantic").SecretStr("t" * 32)})
    async with running(s) as (_, client):
        assert (await client.get("/v1/selfwatch")).status_code == 401


async def test_the_route_without_the_part_says_only_its_word(settings: Settings) -> None:
    async with running(settings.model_copy(update={"selfwatch_enabled": False})) as (_, client):
        body = (await client.get("/v1/selfwatch")).json()
    assert body == {"part": "selfwatch", "ready": part_mod.OFF}


async def test_a_status_that_fails_is_a_plain_unavailable(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def broken(self: Status) -> dict[str, Any]:
        raise RuntimeError("secret words")

    monkeypatch.setattr(Status, "view", broken)
    async with running(settings) as (_, client):
        r = await client.get("/v1/selfwatch")
    assert r.status_code == 200 and r.json()["unavailable"] is True
    assert "secret" not in r.text


def test_every_selfwatch_module_stays_small() -> None:
    from pathlib import Path

    root = Path(part_mod.__file__).parent
    for py in root.glob("*.py"):
        assert len(py.read_text(encoding="utf-8").splitlines()) <= 400, py.name
