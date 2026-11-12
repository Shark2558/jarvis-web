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


# ---- code review L1: one phrase that will not go in never drops the others ----------------------
def _phrase(name: str) -> Any:
    def router(text: str, now: Any) -> None:
        return None

    router.__name__ = router.__qualname__ = name
    return router


class _Book:
    """A phrasebook that refuses `bad` (as a full one refuses: ValueError) and takes the rest."""

    def __init__(self, bad: Any) -> None:
        self.bad, self.phrases = bad, ()

    def add_phrases(self, routers: Any) -> None:
        if self.bad in routers:
            raise ValueError("too many No-AI phrase routers")
        self.phrases = (*self.phrases, *routers)


def _app_with(mode: Any, *routers: Any) -> FastAPI:
    from jarvis.fixes.ports import FixPart

    app = FastAPI()
    app.state.brain_mode = mode
    app.state.r111_parts = {"plan": FixPart("plan", services={"phrases": routers}, ready="ready")}
    return app


def test_a_phrase_that_does_not_fit_is_logged_as_an_error_and_the_others_still_go_in(
    caplog: pytest.LogCaptureFixture,
) -> None:
    import logging

    from jarvis.api.r11_1_wiring import install_fix_phrases

    first, bad, last = _phrase("session_done"), _phrase("session_moved"), _phrase("skipped")
    book = _Book(bad)
    caplog.set_level(logging.WARNING)
    install_fix_phrases(_app_with(book, first, bad, last))
    assert book.phrases == (first, last)
    [record] = [r for r in caplog.records if "No-AI" in r.getMessage()]
    assert record.levelno == logging.ERROR
    assert getattr(record, "phrase", None) == "session_moved" and getattr(record, "left", 0) == 1


def test_a_nearly_full_phrasebook_takes_as_many_as_fit(settings: Settings) -> None:
    from jarvis.api.r11_1_wiring import install_fix_phrases
    from jarvis.offline.mode import MAX_PHRASES, BrainMode

    mode = BrainMode(settings)
    mode.add_phrases([_phrase(f"other_{i}") for i in range(MAX_PHRASES - 1)])
    one, two = _phrase("session_done"), _phrase("session_skipped")
    install_fix_phrases(_app_with(mode, one, two))
    assert mode.phrases[-1] is one and two not in mode.phrases


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


# ---- INTEGRATION-A 3.8: Approve all says a batch's own count when no model can narrate -------
async def test_approve_all_without_a_narrator_says_the_batch_s_own_count(
    brain: Any, provider: MockProvider
) -> None:
    from jarvis.core.guardrails import ActionRisk
    from jarvis.core.models import ChatRequest
    from jarvis.llm.base import ToolCall
    from jarvis.tools import Tool

    said = "58 events added, 2 failed, Sir. Retry the 2 from the card under this reply."

    async def batch(_a: dict[str, Any]) -> dict[str, Any]:
        return {"added": 58, "failed": 2, "message": said}

    brain.gateway.registry.register(
        Tool(
            "calendar_create_events",
            "a batch",
            {"type": "object", "properties": {"plan": {"type": "string"}}},
            ActionRisk.REVERSIBLE,
            batch,
            summary_template="Add 60 events to your calendar: {plan}",
        )
    )
    call = ToolCall(id="b1", name="calendar_create_events", arguments={"plan": "CCA"})
    provider.script_tool_calls([call], "Waiting for you, Sir.")
    resp = await brain.chat(ChatRequest(message="add my plan", channel="voice"))
    [card] = resp.pending_approvals
    provider.fail_next = 5  # no model can narrate what happened
    out = await brain.approve_all([card.id], session_id=resp.session_id)
    assert said in out.reply
    assert "Done, Sir: Add 60 events" not in out.reply


# ---- INTEGRATION-A 3.9 (an R11 bug): a card proposed outside a conversation can be approved ---
CAL = "https://www.googleapis.com/calendar/v3"


def _kitchen_app(settings: Settings, rules: Any = None) -> Any:
    """The kitchen part on the fake Google, its routes on a small app with a real gateway and a
    conversation store, as the app wires them; `rules`: his rows (None: none, a card is made)."""
    import httpx
    from fastapi import FastAPI
    from google_fakes import FakeGoogle
    from r11_fakes_d import Rules, connector, kctx

    from jarvis.api.auth import require_auth
    from jarvis.api.helpers import change_limiter
    from jarvis.api.helpers_kitchen import router
    from jarvis.api.identity import current_user
    from jarvis.core.guardrails import ConfirmationGate
    from jarvis.helpers.kitchen import part as kitchen_part
    from jarvis.tools.audit import AuditLog
    from jarvis.tools.gateway import Gateway
    from jarvis.tools.policy import Policy
    from jarvis.tools.registry import ToolRegistry

    async def build() -> tuple[FastAPI, Any, Any]:
        from r11_fakes import UID as KUID

        fake = FakeGoogle()
        fake.on(
            "GET",
            f"{CAL}/users/me/calendarList/primary",
            httpx.Response(200, json={"timeZone": "Asia/Kolkata"}),
        )
        me = {"email": "owner@example.com", "self": True}
        made = {"start": {"dateTime": "2026-11-11T19:00:00+05:30"}, "organizer": me}
        fake.on(
            "POST",
            f"{CAL}/calendars/primary/events",
            httpx.Response(200, json={"id": "evcooking", "summary": "Cooking", **made}),
            httpx.Response(200, json={"id": "evwashing", "summary": "Washing-up", **made}),
        )
        c, _, _, _ = kctx(google=await connector(fake.client()), rules=Rules())
        built = kitchen_part.build(c)
        reg = ToolRegistry()
        for t in built.tools:
            reg.register(t)
        gw = Gateway(
            registry=reg, policy=Policy(), gate=ConfirmationGate(), audit=AuditLog(), rules=rules
        )
        app = FastAPI()
        app.include_router(router)
        app.dependency_overrides[require_auth] = lambda: None
        app.dependency_overrides[current_user] = lambda: KUID
        app.state.r11_parts, app.state.helpers_limit = {"kitchen": built}, change_limiter()
        app.state.gateway, app.state.store = gw, InMemorySessionStore()
        app.state.settings = settings
        return app, gw, fake

    return build()


async def _press(app: Any) -> Any:
    from httpx import ASGITransport, AsyncClient

    from jarvis.api.helpers_kitchen import PREFIX

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        return await client.post(f"{PREFIX}/blocks/propose")


async def test_the_kitchen_s_calendar_card_waits_in_a_real_conversation_and_can_be_approved(
    settings: Settings,
) -> None:
    """INTEGRATION-A 3.9 and code review M2: the card waits in a stored conversation of his
    own, ONE a day however often he presses, and approving it runs the calendar tool through
    the gateway with the confirmation token (the events reach Google); a second card there can
    still be declined."""
    from r11_fakes import UID as KUID

    from jarvis.core.brain import Brain
    from jarvis.llm.router import ModelRouter, ModelTier

    app, gw, fake = await _kitchen_app(settings)
    store = app.state.store
    r = await _press(app)
    assert r.status_code == 200 and r.json()["pending"] is True, r.text
    sid = r.json()["session_id"]
    [card] = await gw.pending()
    session = await store.get(sid)
    assert session is not None and session.user_id == KUID and card.scope == f"{KUID}:{sid}"
    again = await _press(app)  # the same card again: the same conversation, the same card
    assert again.status_code == 200 and again.json()["session_id"] == sid  # the day's one
    assert [x.id for x in await store.list_for_user(KUID)] == [sid]
    assert [c.id for c in await gw.pending()] == [card.id]

    provider = MockProvider()
    tiers = {t: "m" for t in ModelTier}
    brain = Brain(router=ModelRouter(provider, tiers), store=store, settings=settings, gateway=gw)
    provider.script("Added, Sir.")
    out = await brain.approve(card.id, session_id=sid, user_id=KUID)  # decided in Approvals
    posted = fake.sent("POST", "/calendars/primary/events")
    assert out.session_id == sid and len(posted) == 2, [r.url for r in fake.requests]
    ran = [e for e in gw.audit._entries if e.tool == "calendar_kitchen_blocks"]  # noqa: SLF001
    # run with the approval's one-use confirmation token, audited as confirmed
    assert ran and ran[-1].outcome == "executed" and ran[-1].detail.startswith("confirmed")
    assert await gw.pending() == []
    later = await _press(app)  # a new card after the approval: still the day's conversation
    assert later.status_code == 200 and later.json()["session_id"] == sid
    [second] = await gw.pending()
    provider.script("Left it, Sir.")
    out = await brain.decline(second.id, session_id=sid, user_id=KUID)
    assert out.session_id == sid and await gw.pending() == []
    assert len(fake.sent("POST", "/calendars/primary/events")) == 2  # nothing more was added


async def test_a_kitchen_card_that_could_not_be_made_leaves_no_conversation_behind(
    settings: Settings,
) -> None:
    """Code review M2 / security L2: a refused press (his Calendar row on Never) answers 409
    and deletes the conversation it made; nothing reached Google."""
    from r11_fakes import UID as KUID

    from jarvis.tools.policy import Effect, PolicyRule

    class Never:
        async def rules_for(self, user_id: str) -> list[PolicyRule]:
            return [PolicyRule(tool_pattern="calendar_*", effect=Effect.DENY, source="owner")]

    app, gw, fake = await _kitchen_app(settings, rules=Never())
    r = await _press(app)
    assert r.status_code == 409 and r.json()["error"] == "not_proposed", r.text
    assert await app.state.store.list_for_user(KUID) == [] and await gw.pending() == []
    assert fake.sent("POST", "/calendars/primary/events") == []
