# tests/test_r51_wiring.py -- R5.1 I1 (docs/plans/r5-1-observations.md D2-D8): the app wires
# Vitals' own sources (built after the systems check and GitHub), the systems check's briefing
# over Vitals, Telegram checked only for a paired owner, the streamed check and the reminder
# route, ONE shared health job on the tick AND the 5-minute home watchdog, and the watchdog's
# idle-offline setting.
from __future__ import annotations

import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from httpx import ASGITransport, AsyncClient
from r3_app import H, r3_app, r3_settings

from jarvis.api import create_app
from jarvis.config import Settings
from jarvis.health.tick import HealthTickJob
from jarvis.llm.mock_provider import MockProvider
from jarvis.memory.inmemory import InMemorySessionStore
from jarvis.vitals.own import OwnSources


@asynccontextmanager
async def plain(s: Settings) -> AsyncIterator[tuple[Any, AsyncClient]]:
    app = create_app(s, provider=MockProvider(), store=InMemorySessionStore())
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            yield app, c


# ---- Vitals' own sources (D2) ------------------------------------------------------------------
async def test_vitals_reads_the_live_health_github_and_home_and_the_default_brain() -> None:
    async with r3_app() as w:
        st = w.state
        own: OwnSources = st.vitals._own._src  # noqa: SLF001
        assert own.health is st.health and own.github is st.github and own.home is st.home_store
        assert own.default_brain == st.brains.default.id
        assert own.claude is None and own.gemini is None  # the mock brain is neither
        r = await w.client.get("/v1/vitals")
        assert r.status_code == 200, r.text
        ids = {i["id"] for i in r.json()["items"]}
        assert "home_link" in ids  # a linked home is on the board with no typing


async def test_a_vitals_failure_never_stops_the_systems_check(settings: Settings) -> None:
    async with plain(settings.model_copy(update={"vitals_enabled": False})) as (app, c):
        assert app.state.vitals is None and app.state.health is not None
        r = await c.post("/v1/health/run", headers=H)
        assert r.status_code == 200, r.text
        assert "Vitals" not in " ".join(r.json()["briefing"]["lines"])  # off: nothing said


# ---- the briefing reads Vitals (D5) and the stream is mounted (D7) -----------------------------
async def test_the_briefing_reads_this_months_spend_from_vitals(settings: Settings) -> None:
    async with plain(settings) as (_, c):
        r = await c.post("/v1/health/run", json={"force": True}, headers=H)
        assert r.status_code == 200, r.text
        briefing = r.json()["briefing"]
        assert briefing["spend"].startswith("AI spend is ")
        assert "Vitals can't be read" not in briefing["spoken"]


async def test_the_streamed_check_answers_ndjson(settings: Settings) -> None:
    async with plain(settings) as (_, c):
        r = await c.post("/v1/health/run/stream", json={"force": True}, headers=H)
        assert r.status_code == 200, r.text
        assert r.headers["content-type"].startswith("application/x-ndjson")
        events = [json.loads(line) for line in r.text.splitlines() if line]
        assert events[0]["type"] == "plan" and events[-1]["type"] == "done"
        assert {e["key"] for e in events if e["type"] == "result"} == {"brain", "docs"}
        assert events[-1]["briefing"]["spend"].startswith("AI spend is ")


# ---- Telegram only for a paired owner (D4) ------------------------------------------------------
async def test_telegram_is_checked_for_the_paired_owner_and_left_out_for_another() -> None:
    async with r3_app() as w:
        r = await w.client.post("/v1/health/run", json={"force": True}, headers=H)
        assert "telegram" in {s["key"] for s in r.json()["systems"]}
        report = await w.state.health.check("u_somebody_else", force=True)
        assert "telegram" not in {res.key for res in report.results}  # not set up: left out


# ---- one shared health job (D4) and the idle-offline setting (D3) -------------------------------
async def test_the_tick_and_the_home_watchdog_share_one_health_job() -> None:
    async with r3_app() as w:
        st = w.state
        job = st.health_job
        assert isinstance(job, HealthTickJob)
        assert [j for j in st.tick_jobs if j.name == "health_check"] == [job]
        assert [j for j in st.home_watchdog._extra if j.name == "health_check"] == [job]  # noqa: SLF001
        out = await st.home_watchdog.run()
        assert out["jobs"]["health_check"] == "ok"


async def test_without_a_home_the_health_job_rides_the_tick_only(settings: Settings) -> None:
    async with plain(settings) as (app, _):
        assert app.state.home_watchdog is None
        assert [j.name for j in app.state.tick_jobs] == [
            "vitals_poll",
            "health_check",
            "helpers_clock",  # R11 I0
            "helpers_daily",
        ]
        assert app.state.health_job is app.state.tick_jobs[1]


async def test_the_watchdog_takes_the_idle_offline_setting() -> None:
    async with r3_app() as w:
        assert w.state.home_watchdog._offline._alert_when == "always"  # noqa: SLF001
    async with r3_app(r3_settings(home_offline_alert="armed_only")) as w:
        assert w.state.home_watchdog._offline._alert_when == "armed_only"  # noqa: SLF001


async def test_a_reminder_for_an_unknown_concern_is_refused_not_run(settings: Settings) -> None:
    async with plain(settings) as (_, c):
        r = await c.post(
            "/v1/health/remind", json={"key": "telegram", "when": "1h"}, headers=H
        )  # nothing failed in the last check: not one of its concerns
        assert r.status_code == 422, r.text
