# tests/test_r11_1_a_routes.py -- R11.1 Part A's routes on the real app (plan D5, D6, D21-A): the
# plans view, the two check-in buttons, the re-plan card in a conversation that can approve it,
# "Retry the N" through the same card path, and the owner's own "Undo all" press, which runs
# through the gateway without a second card while the model's own request stays a card.
from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from r11_1_fakes_a import Clock, PlanGoogle, connector, weekday_sessions

from jarvis.api import create_app
from jarvis.config import Settings
from jarvis.llm.base import ToolCall
from jarvis.llm.mock_provider import MockProvider
from jarvis.memory.inmemory import InMemorySessionStore
from jarvis.series.phrases import route
from jarvis.storage.docs import MemoryDocs
from jarvis.tools import calendar_batch as cb
from jarvis.tools.gateway import GatewayOutcome
from jarvis.tools.policy import Effect, Policy, PolicyRule
from jarvis.tools.provenance import OUTSIDE_KEY
from jarvis.tools.taint import context_trust
from jarvis.undo.service import UndoBin
from jarvis.undo.store import DeletedStore

IST = ZoneInfo("Asia/Kolkata")
OWNER = "owner"  # no owner e-mail is configured in tests: the single dev owner
T0 = datetime(2026, 11, 12, 9, 0, tzinfo=IST)
AFTER_1 = datetime(2026, 11, 16, 20, 20, tzinfo=IST)


def _marked(batch: str) -> dict[str, Any]:
    """An event that carries a batch's private marker (as a batch run leaves it)."""
    return {
        "id": f"x{batch}",
        "status": "confirmed",
        "summary": "Topic",
        "start": {"dateTime": "2026-12-01T19:00:00+05:30"},
        "end": {"dateTime": "2026-12-01T20:00:00+05:30"},
        "extendedProperties": {"private": {cb.BATCH_KEY: f"{batch}:1", cb.BATCH_ID_KEY: batch}},
    }


class App:
    def __init__(self, app: FastAPI, client: AsyncClient, fake: PlanGoogle, clock: Clock) -> None:
        self.app, self.c, self.fake, self.clock = app, client, fake, clock
        self.gw = app.state.gateway
        self.store: InMemorySessionStore = app.state.store

    async def batch(self, n: int, *, series: bool = True) -> dict[str, Any]:
        """An approved batch of `n` weekday sessions (a followed plan with `series`)."""
        args: dict[str, Any] = {"events": weekday_sessions(n)}
        if series:
            args |= {"title_prefix": "CCA", "series": {"name": "CCA"}}
        call = ToolCall(id="c", name=cb.CREATE, arguments=args)
        with context_trust(untrusted=False):
            asked = await self.gw.execute(call, scope=f"{OWNER}:setup")
        assert asked.pending is not None, asked.error
        done = await self.gw.execute(call, confirmation_id=asked.pending.id, scope=f"{OWNER}:setup")
        assert done.outcome is GatewayOutcome.EXECUTED, done.error
        return dict(done.result)


@pytest.fixture
async def site(settings: Settings) -> AsyncIterator[App]:
    fake, clock = PlanGoogle(), Clock(T0)
    app = create_app(settings, provider=MockProvider(), store=InMemorySessionStore())
    async with app.router.lifespan_context(app):
        # what the part reads late: the Google link, Recently deleted and the helpers' clock
        app.state.google = await connector(fake, uid=OWNER)
        app.state.undo = UndoBin(DeletedStore(MemoryDocs()))
        app.state.helpers_now = clock
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            yield App(app, c, fake, clock)


# ---- the view ----------------------------------------------------------------------------------
async def test_the_view_starts_empty_and_puts_the_phrases_into_no_ai_mode(site: App) -> None:
    assert route not in site.app.state.brain_mode.phrases
    r = await site.c.get("/v1/series")
    assert r.status_code == 200 and r.headers["cache-control"] == "no-store"
    assert r.json() == {"part": "plan", "ready": "ready", "plans": [], "waiting": []}
    assert site.app.state.brain_mode.phrases.count(route) == 1
    await site.c.get("/v1/series")
    assert site.app.state.brain_mode.phrases.count(route) == 1  # once


async def test_the_view_lists_plans_and_the_check_ins_that_wait(site: App) -> None:
    await site.batch(60)
    site.clock.at = AFTER_1
    body = (await site.c.get("/v1/series")).json()
    [plan] = body["plans"]
    assert (plan["name"], plan["sessions"], plan["done"], plan["skipped"]) == ("CCA", 60, 0, 0)
    [waiting] = body["waiting"]
    assert (waiting["session"], waiting["of"], waiting["plan"]) == (1, 60, plan["id"])
    assert waiting["text"] == "Session 1 of 60 in your CCA plan (Mon 16 Nov 19:00): did it happen?"
    assert "Topic" not in str(body)  # titles stay in the calendar


# ---- the two buttons ---------------------------------------------------------------------------
async def test_done_marks_it_and_makes_no_conversation(site: App) -> None:
    await site.batch(5)
    site.clock.at = AFTER_1
    r = await site.c.post("/v1/series/answer", json={"answer": "done"})
    assert r.status_code == 200, r.text
    assert r.json()["message"] == "Session 1 of 5 in your CCA plan is marked done, Sir."
    assert r.json()["pending"] is False and r.json()["session_id"] is None
    assert await site.store.list_for_user(OWNER) == []
    assert (await site.c.get("/v1/series")).json()["waiting"] == []


async def test_skipped_leaves_a_card_that_the_approvals_panel_can_approve(site: App) -> None:
    await site.batch(60)
    site.clock.at = AFTER_1
    r = await site.c.post("/v1/series/answer", json={"answer": "skipped"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["pending"] is True and "marked skipped" in body["message"]
    sid = body["session_id"]
    assert sid and (await site.store.get(sid)) is not None  # a real conversation holds the card
    [card] = (await site.c.get("/v1/approvals")).json()
    assert card["tool"] == "series_reschedule" and card["session_id"] == sid
    assert "60 sessions before, 60 after" in card["summary"]
    assert site.fake.sent("PATCH") == []
    ok = await site.c.post(f"/v1/approvals/{card['id']}/approve", json={"session_id": sid})
    assert ok.status_code == 200, ok.text
    assert len(site.fake.sent("PATCH")) == 60 and ok.json()["tool_calls"] == 1
    assert (await site.c.get("/v1/approvals")).json() == []


async def test_a_card_goes_into_the_open_conversation_when_there_is_one(site: App) -> None:
    await site.batch(10)
    site.clock.at = AFTER_1
    sid = (await site.c.post("/v1/chat", json={"message": "hello"})).json()["session_id"]
    r = await site.c.post("/v1/series/answer", json={"answer": "skipped", "session_id": sid})
    assert r.json()["session_id"] == sid and len(await site.store.list_for_user(OWNER)) == 1
    gone = await site.c.post("/v1/series/replan", json={"session_id": "sess_nope"})
    assert gone.status_code == 404
    again = await site.c.post("/v1/series/replan", json={"session_id": sid})
    assert again.status_code == 200 and again.json()["pending"] is True
    assert len((await site.c.get("/v1/approvals")).json()) == 1  # the same card, not a second


async def test_an_answer_with_nothing_waiting_says_so(site: App) -> None:
    r = await site.c.post("/v1/series/answer", json={"answer": "done"})
    assert r.status_code == 200 and r.json()["refused"] is True
    assert r.json()["message"] == "No session is waiting for an answer, Sir."
    bad = await site.c.post("/v1/series/answer", json={"answer": "later"})
    assert bad.status_code == 422
    extra = await site.c.post("/v1/series/answer", json={"answer": "done", "user_id": "x"})
    assert extra.status_code == 422


async def test_a_re_plan_with_nothing_skipped_says_so_and_makes_nothing(site: App) -> None:
    await site.batch(5)
    r = await site.c.post("/v1/series/replan", json={})
    assert r.status_code == 200 and r.json()["refused"] is True
    assert r.json()["message"] == "No skipped session is waiting for new dates, Sir."
    assert r.json()["pending"] is False and await site.gw.pending() == []
    assert await site.store.list_for_user(OWNER) == []  # no conversation for a card never made
    other = await site.c.post("/v1/series/replan", json={"series": "Nope"})
    assert other.json()["message"] == "You have no plan by that name, Sir."


# ---- Undo all ----------------------------------------------------------------------------------
async def test_the_owner_s_undo_all_runs_through_the_gateway_without_a_second_card(
    site: App,
) -> None:
    made = await site.batch(60)
    r = await site.c.post(f"/v1/series/batches/{made['batch']}/undo", json={})
    assert r.status_code == 200, r.text
    body = r.json()
    assert (body["removed"], body["kept"], body["failed"]) == (60, 0, 0)
    assert body["message"].startswith("Removed 60 events, Sir.")
    assert site.fake.live() == [] and await site.gw.pending() == []
    assert (await site.c.get("/v1/series")).json()["plans"] == []  # the plan went with them
    trail = [e for e in (await site.gw.audit.tail(20)).entries if e.tool == cb.UNDO]
    assert [e.outcome for e in trail] == ["awaiting_confirmation", "executing", "executed"]
    assert trail[1].detail == "confirmed; owner: Undo all"  # audited as his own press


async def test_the_model_s_own_undo_is_still_a_card(site: App) -> None:
    made = await site.batch(3, series=False)
    call = ToolCall(id="m", name=cb.UNDO, arguments={"batch": made["batch"]})
    with context_trust(untrusted=False):
        out = await site.gw.execute(call, scope=f"{OWNER}:sess")
    assert out.outcome is GatewayOutcome.AWAITING_CONFIRMATION and len(site.fake.live()) == 3


async def test_his_press_never_approves_a_conversation_s_card_and_then_withdraws_it(
    site: App,
) -> None:
    made, other = await site.batch(3, series=False), "b" + "9" * 16
    site.fake.events[f"x{other}"] = _marked(other)  # another batch's event, still there
    asked = []
    for batch in (made["batch"], other):
        call = ToolCall(id="m", name=cb.UNDO, arguments={"batch": batch})
        with context_trust(untrusted=False):
            asked.append((await site.gw.execute(call, scope=f"{OWNER}:sess")).pending)
    assert all(asked)
    r = await site.c.post(f"/v1/series/batches/{made['batch']}/undo", json={})
    assert r.status_code == 200 and r.json()["removed"] == 3
    assert [e["id"] for e in site.fake.live()] == [f"x{other}"]
    left = await site.gw.pending()
    assert [c.id for c in left] == [asked[1].id]  # the other batch's card is not touched
    trail = [e for e in (await site.gw.audit.tail(20)).entries if e.outcome == "executing"]
    assert trail[-1].detail == "confirmed; owner: Undo all"


async def test_never_on_the_calendar_row_stops_the_press_too(site: App) -> None:
    made = await site.batch(3, series=False)
    site.gw.policy = Policy([PolicyRule(tool_pattern="calendar_*", effect=Effect.DENY)])
    r = await site.c.post(f"/v1/series/batches/{made['batch']}/undo", json={})
    assert r.status_code == 403 and r.json()["error"] == "not_allowed"
    assert len(site.fake.live()) == 3 and await site.gw.pending() == []


async def test_undo_of_what_is_gone_or_not_a_batch_is_refused_plainly(site: App) -> None:
    gone = await site.c.post(f"/v1/series/batches/b{'0' * 16}/undo", json={})
    assert gone.status_code == 409
    assert gone.json()["detail"] == "Those events are no longer in your calendar, Sir."
    bad = await site.c.post("/v1/series/batches/not-a-batch/undo", json={})
    assert bad.status_code == 422 and await site.gw.pending() == []


async def test_without_recently_deleted_undo_says_so_and_removes_nothing(site: App) -> None:
    made = await site.batch(2, series=False)
    site.app.state.undo = None
    r = await site.c.post(f"/v1/series/batches/{made['batch']}/undo", json={})
    assert r.status_code == 200 and r.json()["unavailable"] is True
    assert "Recently deleted" in r.json()["message"] and len(site.fake.live()) == 2


# ---- Retry -------------------------------------------------------------------------------------
async def test_retry_is_a_card_through_the_same_path_and_marks_the_events_outside(
    site: App,
) -> None:
    site.fake.fail_creates = {2: 400}
    made = await site.batch(3, series=False)
    assert made["failed"] == 1
    n = next(i["n"] for i in made["items"] if i["status"] == "failed")
    again = {**weekday_sessions(3)[n - 1], "n": n, "why": "it could not be added"}
    site.fake.fail_creates = {}
    r = await site.c.post(
        "/v1/series/batches/retry", json={"batch": made["batch"], "events": [again]}
    )
    assert r.status_code == 200, r.text
    assert r.json()["pending"] is True and "1 event" in r.json()["message"]
    assert len(site.fake.live()) == 2  # a card: nothing is added by the press itself
    [card] = await site.gw.pending()
    assert card.tool == cb.CREATE and card.outside is True
    call = ToolCall(id="a", name=card.tool, arguments=card.arguments)
    done = await site.gw.execute(call, confirmation_id=card.id, scope=card.scope)
    assert done.result["created"] == 1 and len(site.fake.live()) == 3
    marks = {e["extendedProperties"]["private"][cb.BATCH_KEY] for e in site.fake.live()}
    assert marks == {f"{made['batch']}:{i}" for i in (1, 2, 3)}
    newest = next(e for e in site.fake.live() if cb.number_of(e, made["batch"]) == n)
    assert OUTSIDE_KEY in newest["extendedProperties"]["private"]


async def test_a_retry_with_a_guest_or_a_bad_batch_is_refused(site: App) -> None:
    event = {**weekday_sessions(1)[0], "n": 1}
    bad = await site.c.post("/v1/series/batches/retry", json={"batch": "x", "events": [event]})
    assert bad.status_code == 422
    guest = await site.c.post(
        "/v1/series/batches/retry",
        json={"batch": "b" + "1" * 16, "events": [{**event, "attendees": ["a@example.com"]}]},
    )
    assert guest.status_code == 422 and await site.gw.pending() == []


# ---- limits and off ----------------------------------------------------------------------------
async def test_too_many_changes_are_slowed_down(site: App) -> None:
    codes = [
        (await site.c.post("/v1/series/answer", json={"answer": "done"})).status_code
        for _ in range(31)
    ]
    assert codes[:30] == [200] * 30 and codes[30] == 429


async def test_with_plans_off_batches_still_undo_and_answers_say_off(settings: Settings) -> None:
    off = settings.model_copy(update={"series_enabled": False})
    fake = PlanGoogle()
    app = create_app(off, provider=MockProvider(), store=InMemorySessionStore())
    async with app.router.lifespan_context(app):
        app.state.google = await connector(fake, uid=OWNER)
        app.state.undo = UndoBin(DeletedStore(MemoryDocs()))
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            site = App(app, c, fake, Clock(T0))
            view = (await c.get("/v1/series")).json()
            assert "plans are off" in view["ready"] and view["plans"] == []
            r = await c.post("/v1/series/answer", json={"answer": "done"})
            assert r.status_code == 404 and r.json()["error"] == "plans_off"
            made = await site.batch(2, series=False)
            undone = await c.post(f"/v1/series/batches/{made['batch']}/undo", json={})
            assert undone.status_code == 200 and undone.json()["removed"] == 2
