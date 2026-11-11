# tests/test_r11_c_api.py -- R11 Part C on the real app (plan D2, D6, D18, D19): the part is built
# by `wire_r11` with its jobs on the 5-minute clock, its tools on the gateway and its row on the
# privacy dashboard; its own routes under /v1/helpers/nudges (owner-only, no-store, rate-limited,
# plain words); snooze from the tab through I0's gate route reaches the same state the nudge job
# obeys; and with the AI off a phrase ("stop water", "had a glass of water") runs Part C's tool with
# no model.
from __future__ import annotations

import base64
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr
from r11_fakes import NOON_IST, Clock
from r11_fakes_c import FAKE_ROOT

from jarvis.api import create_app
from jarvis.api.r11_wiring import owners_of
from jarvis.api.scheduler_auth import WATCHDOG_PATH, require_scheduler
from jarvis.config import Settings
from jarvis.llm.mock_provider import MockProvider
from jarvis.memory.inmemory import InMemorySessionStore

CSRF = {"X-Requested-With": "JARVIS"}
BASE = "/v1/helpers/nudges"
KEY = SecretStr(base64.b64encode(FAKE_ROOT).decode())


@dataclass
class App:
    app: FastAPI
    client: AsyncClient
    provider: MockProvider

    @property
    def state(self) -> Any:
        return self.app.state


@asynccontextmanager
async def running(s: Settings, *, at: datetime | None = None) -> AsyncIterator[App]:
    provider = MockProvider()
    app = create_app(s, provider=provider, store=InMemorySessionStore())
    app.dependency_overrides[require_scheduler] = lambda: None
    if at is not None:
        app.state.helpers_now = Clock(at)  # wire_r11 keeps a clock that is already set
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            yield App(app, c, provider)


def sealed(settings: Settings) -> Settings:
    return settings.model_copy(update={"token_key": KEY})


async def test_part_c_is_wired_with_its_jobs_tools_row_and_phrases(settings: Settings) -> None:
    async with running(sealed(settings)) as a:
        st = a.state
        assert st.r11_parts["nudges"].ready == "ready"
        assert set(st.helpers_clock.job_names) >= {"nudges", "activity_check"}
        names = {s.name for s in st.gateway.registry.specs()}
        assert {"nudge_stop", "nudge_snooze", "freetime_suggest"} <= names
        assert "helpers_wellbeing" in st.privacy.registry.ids()
        assert st.brain_mode.phrases  # Part C's phrasebook joined the one BrainMode
        out = await a.client.post(WATCHDOG_PATH)
        assert out.status_code == 200 and out.json()["jobs"]["helpers_clock"] == "ok"


async def test_without_a_token_key_the_part_says_the_log_is_off(settings: Settings) -> None:
    async with running(settings) as a:
        assert "log is off" in a.state.r11_parts["nudges"].ready
        view = (await a.client.get(BASE)).json()
        assert view["sealed"] is False and view["today"] is None
        r = await a.client.post(f"{BASE}/water", json={"glasses": 1}, headers=CSRF)
        assert r.status_code == 409 and "token key" in r.json()["detail"]


async def test_the_view_lists_every_nudge_off_by_default(settings: Settings) -> None:
    async with running(sealed(settings)) as a:
        r = await a.client.get(BASE)
        assert r.status_code == 200 and r.headers["cache-control"] == "no-store"
        view = r.json()
        assert [n["name"] for n in view["nudges"]] == [
            "standup",
            "water",
            "activity",
            "free_time",
            "focus",
        ]
        assert not any(n["on"] for n in view["nudges"])
        water = view["nudges"][1]
        assert (water["every"], water["start"], water["end"]) == (90, "09:30", "18:30")
        assert water["when"] == "Every 90 minutes, 09:30-18:30, Monday to Saturday."
        assert view["today"] == {"water": 0, "stood": 0} and view["ideas"] == []


async def test_switch_change_and_log_from_the_tab(settings: Settings) -> None:
    async with running(sealed(settings)) as a:
        c = a.client
        r = await c.put(f"{BASE}/water", json={"on": True, "every": 60}, headers=CSRF)
        water = r.json()["nudges"][1]
        assert r.status_code == 200 and water["on"] is True and water["every"] == 60
        r = await c.put(
            f"{BASE}/standup", json={"meeting": True, "word": "daily sync"}, headers=CSRF
        )
        assert r.json()["nudges"][0]["meeting"] is True
        r = await c.post(f"{BASE}/water", json={"glasses": 2}, headers=CSRF)
        assert r.json()["today"]["water"] == 2
        r = await c.post(f"{BASE}/stood", headers=CSRF)
        assert r.json()["today"]["stood"] == 1


async def test_bad_changes_are_refused_in_plain_words(settings: Settings) -> None:
    async with running(sealed(settings)) as a:
        c = a.client
        for path, body in (
            (f"{BASE}/coffee", {"on": True}),
            (f"{BASE}/water", {"every": 5}),
            (f"{BASE}/water", {"start": "20:00", "end": "08:00"}),
        ):
            r = await c.put(path, json=body, headers=CSRF)
            assert r.status_code == 422 and r.json()["error"] == "invalid", (path, r.text)
        r = await c.put(f"{BASE}/water", json={"colour": "red"}, headers=CSRF)
        assert r.status_code == 422  # the app's schema answer (no input echoed)
        r = await c.post(f"{BASE}/water", json={"glasses": 50}, headers=CSRF)
        assert r.status_code == 422


async def test_the_free_time_list_from_the_tab(settings: Settings) -> None:
    async with running(sealed(settings)) as a:
        c = a.client
        r = await c.post(
            f"{BASE}/ideas",
            json={"text": "Sketch the garden", "minutes": 30, "place": "outdoor"},
            headers=CSRF,
        )
        idea = r.json()["ideas"][0]
        assert r.status_code == 200 and idea["text"] == "Sketch the garden"
        r = await c.post(f"{BASE}/ideas/{idea['id']}/done", headers=CSRF)
        assert r.json()["ideas"][0]["last_done"] is not None
        r = await c.delete(f"{BASE}/ideas/{idea['id']}", headers=CSRF)
        assert r.json()["ideas"] == []
        r = await c.delete(f"{BASE}/ideas/{idea['id']}", headers=CSRF)
        assert r.status_code == 404
        r = await c.post(f"{BASE}/ideas", json={"text": "", "minutes": 30}, headers=CSRF)
        assert r.status_code == 422


async def test_snooze_from_the_tab_holds_the_nudge_the_job_would_send(settings: Settings) -> None:
    async with running(sealed(settings), at=NOON_IST) as a:
        c, uid = a.client, owners_of(settings)[0]
        await c.put(f"{BASE}/water", json={"on": True, "every": 30}, headers=CSRF)  # 12:00 is due
        r = await c.post(
            "/v1/helpers/gate/nudge_hydrate/snooze", json={"minutes": 60}, headers=CSRF
        )
        assert r.status_code == 200
        assert "nudge_hydrate" in (await c.get(BASE)).json()["gate"]["snoozed"]
        await c.post(WATCHDOG_PATH)
        days = await a.state.helpers_sender.store.days(uid)
        assert [e["o"] for _, sends in days for e in sends] == ["snoozed"]


async def test_with_the_ai_off_a_phrase_runs_part_cs_tool_and_no_model(settings: Settings) -> None:
    async with running(sealed(settings), at=NOON_IST) as a:
        c = a.client
        r = await c.post("/v1/settings/brain-mode", json={"mode": "none"}, headers=CSRF)
        assert r.status_code == 200
        r = await c.post("/v1/chat", json={"message": "stop water"})
        assert r.status_code == 200, r.text
        assert r.json()["reply"].startswith("Stopped the drink water nudge for today, Sir.")
        r = await c.post("/v1/chat", json={"message": "don't remind me to stand up"})
        assert r.json()["reply"].startswith("Stopped the stand up and move nudge for today")
        r = await c.post("/v1/chat", json={"message": "had a glass of water"})
        assert r.json()["reply"] == "Logged, Sir: 1 glasses of water today."
        tail = await a.state.gateway.audit.tail(50)
        tools = [e.tool for e in tail.entries]
        assert "nudge_stop" in tools and "nudge_water_log" in tools
        assert "reminder_add" not in tools  # "don't remind me" never sets a reminder


async def test_routes_answer_404_when_the_helpers_are_off(settings: Settings) -> None:
    async with running(settings.model_copy(update={"helpers_enabled": False})) as a:
        r = await a.client.get(BASE)
        assert r.status_code == 404 and r.json()["error"] == "helpers_off"
