# tests/test_r11_1_i1_plan.py -- R11.1 I1: Part A's plan part joined to the app's No-AI phrases
# and the morning brief (INTEGRATION-A 3.2, 3.3). "session done" is a No-AI phrase from the first
# message after a start (with the helpers on or off), and the brief's Helpers lines carry the
# plan's "N planned sessions have no check-in" line.
from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import date
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from fastapi import FastAPI

from jarvis.api import create_app
from jarvis.api.r11_1_wiring import fix_phrases
from jarvis.config import Settings
from jarvis.llm.mock_provider import MockProvider
from jarvis.memory.inmemory import InMemorySessionStore
from jarvis.series.phrases import route

UID = "owner"


@asynccontextmanager
async def running(s: Settings) -> AsyncIterator[FastAPI]:
    app = create_app(s, provider=MockProvider(), store=InMemorySessionStore())
    async with app.router.lifespan_context(app):
        yield app


@pytest.mark.parametrize("helpers", [True, False])
async def test_the_plan_phrases_are_in_no_ai_mode_from_the_start(
    settings: Settings, helpers: bool
) -> None:
    async with running(settings.model_copy(update={"helpers_enabled": helpers})) as app:
        assert fix_phrases(app) == (route,)
        phrases = app.state.brain_mode.phrases
        assert phrases.count(route) == 1  # once, whoever else adds it later (the lazy ensure)
        assert app.state.r111_parts["plan"].services["ensure"]() is True
        assert app.state.brain_mode.phrases.count(route) == 1


async def test_the_plan_phrases_come_after_the_helpers_own(settings: Settings) -> None:
    async with running(settings) as app:
        phrases = list(app.state.brain_mode.phrases)
        helpers = [r for p in app.state.r11_parts.values() for r in p.phrases]
        assert helpers and all(phrases.index(r) < phrases.index(route) for r in helpers)


class _Waiting:
    def __init__(self, n: int) -> None:
        self.n = n

    async def lines(self, uid: str, tz: Any, day: date) -> list[str]:
        return [f"{self.n} planned sessions have no check-in."]


async def test_the_brief_s_helpers_lines_carry_the_plan_s_open_check_ins(
    settings: Settings,
) -> None:
    async with running(settings) as app:
        plan = app.state.r111_parts["plan"]
        brief = plan.services["brief"]
        assert brief is not None and brief.name == "plans"
        helpers = app.state.brief._helpers  # noqa: SLF001 - the wiring itself is under test
        everyone = list(helpers._contributors())  # noqa: SLF001
        assert brief in everyone
        plan.services["brief"] = _Waiting(2)  # what the plan's own contributor would say
        section = await helpers.section(UID, ZoneInfo("Asia/Kolkata"), date(2027, 1, 15))
    assert section is not None
    assert "2 planned sessions have no check-in." in [line for line in section.lines]


# ---- INTEGRATION-A 3.7: an "Undo all" of a full batch is listed whole in Recently deleted ------
async def test_recently_deleted_lists_a_whole_batch_and_the_model_still_sees_at_most_50() -> None:
    from jarvis.storage.docs import MemoryDocs
    from jarvis.undo.service import UndoBin
    from jarvis.undo.store import MAX_LISTED, PANEL_LISTED, DeletedStore

    assert PANEL_LISTED == 100 and MAX_LISTED == 50  # a batch holds at most 100 events
    b = UndoBin(DeletedStore(MemoryDocs()))
    for n in range(60):
        await b.keep(UID, "event", f"Session {n + 1}", {"summary": f"Session {n + 1}"})
    assert len(await b.recent(UID, limit=PANEL_LISTED)) == 60  # the panel: every one of the 60
    assert len(await b.recent(UID)) == 50  # the model's deleted_list: its result stays small


async def test_the_recently_deleted_panel_lists_up_to_a_whole_batch(settings: Settings) -> None:
    from httpx import ASGITransport, AsyncClient

    from jarvis.storage.docs import MemoryDocs
    from jarvis.undo.service import UndoBin
    from jarvis.undo.store import DeletedStore

    b = UndoBin(DeletedStore(MemoryDocs()))
    for n in range(60):
        await b.keep(UID, "event", f"Session {n + 1}", {"summary": f"Session {n + 1}"})
    app = create_app(settings, provider=MockProvider(), store=InMemorySessionStore(), undo=b)
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.get("/v1/deleted")
    assert r.status_code == 200 and len(r.json()["items"]) == 60
