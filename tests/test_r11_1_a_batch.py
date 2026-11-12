# tests/test_r11_1_a_batch.py -- R11.1 Part A, O2 (plan D4, D5, D21-A): sixty events are ONE
# approval card that lists them all; approved, they are created five at a time with a private
# marker; a failed create is reported by item and a retry creates nothing twice; one Undo removes
# them and leaves a changed event alone; an event with a guest is refused; many single calls of
# one round become one batch card.
from __future__ import annotations

import json
from datetime import date, timedelta
from typing import Any

import pytest
from r11_1_fakes_a import UID, PlanGoogle, Said, ScriptedBrain, call, connector

from jarvis.config import Settings
from jarvis.core.brain import Brain
from jarvis.core.guardrails import ActionRisk, ConfirmationGate
from jarvis.core.models import ChatRequest
from jarvis.llm.base import ToolCall
from jarvis.llm.router import ModelRouter, ModelTier
from jarvis.memory.inmemory import InMemorySessionStore
from jarvis.series import batch as sb
from jarvis.storage.docs import MemoryDocs
from jarvis.tools import calendar_batch as cb
from jarvis.tools.audit import AuditLog
from jarvis.tools.budget import turn_budget
from jarvis.tools.calendar_cards import batch_card, undo_card
from jarvis.tools.gateway import Gateway, GatewayOutcome, GatewayResult
from jarvis.tools.google_calendar import calendar_tools
from jarvis.tools.policy import Effect, Policy, PolicyRule
from jarvis.tools.provenance import OUTSIDE_KEY, OUTSIDE_VALUE
from jarvis.tools.registry import ToolRegistry
from jarvis.tools.reply_cards import AnyCard, BatchCard, collecting_cards
from jarvis.tools.taint import context_trust
from jarvis.undo.service import UndoBin
from jarvis.undo.store import DeletedStore

SCOPE = f"{UID}:sess_1"
START = date(2026, 11, 16)
TIERS = {t: f"mock-{t.value}" for t in ModelTier}


def sessions(n: int = 60, **extra: Any) -> list[dict[str, Any]]:
    """`n` one-hour evening sessions on consecutive days from 16 Nov 2026."""
    out = []
    for i in range(n):
        day = (START + timedelta(days=i)).isoformat()
        out.append(
            {
                "summary": f"Topic {i + 1}",
                "start": f"{day}T19:00:00+05:30",
                "end": f"{day}T20:00:00+05:30",
                **extra,
            }
        )
    return out


class Rig:
    def __init__(self, fake: PlanGoogle, conn: Any, *, allow: bool = False) -> None:
        self.fake = fake
        self.bin = UndoBin(DeletedStore(MemoryDocs()))
        self.api = sb.BatchAPI(lambda: conn, lambda: self.bin, limit=100, tz="Asia/Kolkata")
        reg = ToolRegistry()
        for t in calendar_tools(conn, undo=self.bin) + sb.batch_tools(self.api, limit=100):
            reg.register(t)
        rules = [PolicyRule(tool_pattern="calendar_*", effect=Effect.ALLOW)] if allow else []
        self.gw = Gateway(
            registry=reg, policy=Policy(rules), gate=ConfirmationGate(), audit=AuditLog()
        )

    async def run(self, name: str, args: dict[str, Any], **kw: Any) -> GatewayResult:
        return await self.gw.execute(ToolCall(id="c", name=name, arguments=args), scope=SCOPE, **kw)

    async def approved(self, name: str, args: dict[str, Any]) -> GatewayResult:
        asked = await self.run(name, args)
        assert asked.outcome is GatewayOutcome.AWAITING_CONFIRMATION, asked.error
        assert asked.pending is not None
        return await self.run(name, args, confirmation_id=asked.pending.id)

    def posts(self) -> list[dict[str, Any]]:
        return [json.loads(r.content) for r in self.fake.sent("POST", "/events")]


@pytest.fixture
async def rig() -> Rig:
    fake = PlanGoogle()
    return Rig(fake, await connector(fake))


# ---- one card ----------------------------------------------------------------------------------
async def test_sixty_events_are_one_card_and_nothing_is_created_before_the_approval(
    rig: Rig,
) -> None:
    args = {"events": sessions(60), "title_prefix": "CCA"}
    out = await rig.run(cb.CREATE, args)
    assert out.outcome is GatewayOutcome.AWAITING_CONFIRMATION and out.pending is not None
    assert rig.posts() == [] and len(await rig.gw.pending()) == 1
    card = out.pending
    assert card.tool_risk is ActionRisk.REVERSIBLE  # an R2 card: no passkey
    assert card.arguments == args and len(card.arguments["events"]) == 60  # the list is the card's
    assert "60 events" in card.summary
    assert "16 Nov 2026" in card.summary and "14 Jan 2027" in card.summary
    assert "CCA - " in card.summary and "Open JARVIS to see the full list" in card.summary
    assert card.bulk_ok is False  # its own card: never run by Approve all


async def test_it_is_a_card_whatever_the_owner_s_row_says_and_costs_one_of_the_five() -> None:
    fake = PlanGoogle()
    rig = Rig(fake, await connector(fake), allow=True)
    with turn_budget() as budget, context_trust(untrusted=False):
        out = await rig.run(cb.CREATE, {"events": sessions(4)})
        assert out.outcome is GatewayOutcome.AWAITING_CONFIRMATION
        assert budget.cards == 4
    with context_trust(untrusted=True, spoken=True):  # spoken, after a file: still ONE card
        again = await rig.run(cb.CREATE, {"events": sessions(60)})
    assert again.outcome is GatewayOutcome.AWAITING_CONFIRMATION and rig.posts() == []


def test_the_card_text_is_written_by_code_from_the_arguments() -> None:
    text = batch_card(sessions(3), prefix="CCA", plan="CCA")
    assert text.splitlines()[0] == "Add 3 events to your calendar: 16 Nov 2026 to 18 Nov 2026."
    assert "Titles start with “CCA - ”." in text
    assert "A plan to follow: “CCA”" in text and "whether it happened" in text
    assert "No invitations" in text
    one = batch_card(sessions(1), prefix="", plan="")
    assert one.splitlines()[0] == "Add 1 event to your calendar: 16 Nov 2026."
    again = batch_card(sessions(60), prefix="", plan="", there=58)
    assert "2 events" in again and "58 of 60 are already there" in again
    assert "nothing will be added" in batch_card(sessions(2), prefix="", plan="", there=2)


# ---- approved ----------------------------------------------------------------------------------
async def test_approved_sixty_are_created_five_at_a_time_each_with_its_marker(rig: Rig) -> None:
    rig.fake.delay_s = 0.002
    out = await rig.approved(cb.CREATE, {"events": sessions(60), "title_prefix": "CCA"})
    assert out.outcome is GatewayOutcome.EXECUTED, out.error
    res = out.result
    assert (res["total"], res["created"], res["failed"]) == (60, 60, 0)
    assert res["message"] == "All 60 events are in your calendar, Sir."
    assert [i["n"] for i in res["items"]] == list(range(1, 61))
    assert all(i["status"] == "created" and i["id"] for i in res["items"])
    bodies = rig.posts()
    assert len(bodies) == 60 and rig.fake.most_at_once == sb.PARALLEL
    batch = res["batch"]
    marks = sorted(b["extendedProperties"]["private"][cb.BATCH_KEY] for b in bodies)
    assert marks == sorted(f"{batch}:{n}" for n in range(1, 61))
    assert {b["extendedProperties"]["private"][cb.BATCH_ID_KEY] for b in bodies} == {batch}
    first = next(
        b for b in bodies if b["extendedProperties"]["private"][cb.BATCH_KEY].endswith(":1")
    )
    assert first["summary"] == "CCA - Topic 1"
    assert first["start"] == {"dateTime": "2026-11-16T19:00:00+05:30", "timeZone": "Asia/Kolkata"}
    assert "attendees" not in first
    assert all(r.url.params["sendUpdates"] == "none" for r in rig.fake.sent("POST", "/events"))


async def test_a_failed_create_is_reported_by_item_and_a_retry_creates_nothing_twice(
    rig: Rig,
) -> None:
    rig.fake.fail_creates = {3: 400, 7: 403}
    args = {"events": sessions(10)}
    first = (await rig.approved(cb.CREATE, args)).result
    assert (first["created"], first["failed"]) == (8, 2)
    assert first["message"] == "8 events added, 2 failed, Sir."
    bad = [i for i in first["items"] if i["status"] == "failed"]
    assert len(bad) == 2 and all(i["why"] and "id" not in i for i in bad)
    assert len(rig.fake.live()) == 8

    rig.fake.fail_creates = {}
    again = (await rig.approved(cb.CREATE, args)).result  # the same list: the same batch
    assert again["batch"] == first["batch"]
    assert (again["created"], again["already_there"], again["failed"]) == (2, 8, 0)
    assert again["message"] == "2 events added, 8 already there, Sir."
    assert len(rig.fake.live()) == 10
    titles = sorted(e["summary"] for e in rig.fake.live())
    assert titles == sorted(f"Topic {i}" for i in range(1, 11))  # each once

    third = (await rig.approved(cb.CREATE, args)).result
    assert (third["created"], third["already_there"]) == (0, 10) and len(rig.fake.live()) == 10


async def test_only_the_failed_items_can_be_retried_with_the_batch_id(rig: Rig) -> None:
    rig.fake.fail_creates = {2: 400}
    events = sessions(5)
    first = (await rig.approved(cb.CREATE, {"events": events})).result
    failed = [i["n"] for i in first["items"] if i["status"] != "created"]
    assert len(failed) == 1 and len(rig.fake.live()) == 4
    n = failed[0]
    retry = {"events": [{**events[n - 1], "n": n}], "batch": first["batch"]}
    rig.fake.fail_creates = {}
    out = await rig.run(cb.CREATE, retry)
    assert out.pending is not None and "1 event" in out.pending.summary  # the same card path
    done = (await rig.run(cb.CREATE, retry, confirmation_id=out.pending.id)).result
    assert (done["created"], done["failed"]) == (1, 0) and len(rig.fake.live()) == 5
    marks = {e["extendedProperties"]["private"][cb.BATCH_KEY] for e in rig.fake.live()}
    assert marks == {f"{first['batch']}:{i}" for i in range(1, 6)}


async def test_a_create_whose_answer_was_lost_is_found_by_its_marker(rig: Rig) -> None:
    rig.fake.lose_answers = {2}
    res = (await rig.approved(cb.CREATE, {"events": sessions(3)})).result
    assert (res["created"], res["failed"]) == (3, 0)
    assert len(rig.fake.live()) == 3 and len(rig.posts()) == 3  # looked up, not sent again


async def test_events_written_from_a_tainted_round_carry_the_outside_mark(rig: Rig) -> None:
    args = {"events": sessions(2)}
    with context_trust(untrusted=True):  # the round read an attached file
        asked = await rig.run(cb.CREATE, args)
    assert asked.pending is not None and asked.pending.outside is True
    out = await rig.run(cb.CREATE, args, confirmation_id=asked.pending.id)
    assert out.trusted is False
    for body in rig.posts():
        assert body["extendedProperties"]["private"][OUTSIDE_KEY] == OUTSIDE_VALUE


async def test_the_owner_s_own_batch_is_his_own(rig: Rig) -> None:
    args = {"events": sessions(2)}
    with context_trust(untrusted=False):
        asked = await rig.run(cb.CREATE, args)
    assert asked.pending is not None
    out = await rig.run(cb.CREATE, args, confirmation_id=asked.pending.id)
    assert out.trusted is True
    assert OUTSIDE_KEY not in rig.posts()[0]["extendedProperties"]["private"]


async def test_the_reply_carries_one_card_with_undo_and_what_to_retry(rig: Rig) -> None:
    rig.fake.fail_creates = {2: 400}
    args = {"events": sessions(3, description="Read chapter"), "series": {"name": "CCA"}}
    asked = await rig.run(cb.CREATE, args)
    assert asked.pending is not None
    cards: list[AnyCard] = []
    with collecting_cards(cards):
        out = await rig.run(cb.CREATE, args, confirmation_id=asked.pending.id)
    [card] = cards
    assert isinstance(card, BatchCard) and card.kind == "batch"
    assert (card.total, card.created, card.failed) == (3, 2, 1)
    assert card.batch == out.result["batch"] and card.name == "CCA"
    assert (card.first, card.last) == ("2026-11-16", "2026-11-18")
    assert card.words == "2 events added, 1 failed, Sir."
    [again] = card.retry
    assert again.n == 2 and again.summary == "Topic 2" and again.description == "Read chapter"
    assert again.start == "2026-11-17T19:00:00+05:30" and again.why
    assert "Undo all" in out.result["note"]


# ---- refused -----------------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("change", "words"),
    [
        ({"attendees": ["priya@example.com"]}, "guests"),
        ({"end": "2026-11-16T18:00:00+05:30"}, "end must be after start"),
        ({"summary": "  "}, "summary is required"),
        ({"colour": "red"}, "unknown field colour"),
        ({"n": 0}, "n must be"),
        ({"description": "x" * 2001}, "too long"),
    ],
)
async def test_a_bad_event_refuses_the_whole_batch_before_any_card(
    rig: Rig, change: dict[str, Any], words: str
) -> None:
    events = sessions(3)
    events[1] = {**events[1], **change}
    out = await rig.run(cb.CREATE, {"events": events})
    assert out.outcome is GatewayOutcome.ERROR and words in (out.error or "")
    assert "event 2" in (out.error or "")
    assert await rig.gw.pending() == [] and rig.posts() == []


@pytest.mark.parametrize(
    ("args", "words"),
    [
        ({"events": []}, "1 to 100"),
        ({"events": "all of them"}, "1 to 100"),
        ({"events": sessions(101)}, "at most 100"),
        ({"events": sessions(1), "series": {"name": ""}}, "series name"),
        ({"events": sessions(1), "series": {"name": "x", "id": 1}}, "series must be"),
        ({"events": sessions(1), "batch": "nope"}, "batch id"),
        ({"events": sessions(1), "title_prefix": "p" * 41}, "too long"),
    ],
)
async def test_arguments_outside_the_limits_are_refused(
    rig: Rig, args: dict[str, Any], words: str
) -> None:
    out = await rig.run(cb.CREATE, args)
    assert out.outcome is GatewayOutcome.ERROR and words in (out.error or "")
    assert await rig.gw.pending() == []


async def test_without_google_nothing_is_proposed() -> None:
    api = sb.BatchAPI(lambda: None, lambda: None, limit=100, tz="Asia/Kolkata")
    reg = ToolRegistry()
    for t in sb.batch_tools(api, limit=100):
        reg.register(t)
    gw = Gateway(registry=reg, policy=Policy(), gate=ConfirmationGate(), audit=AuditLog())
    out = await gw.execute(
        ToolCall(id="c", name=cb.CREATE, arguments={"events": sessions(2)}), scope=SCOPE
    )
    assert out.outcome is GatewayOutcome.ERROR and "Google is not linked" in (out.error or "")
    assert await gw.pending() == []


def test_a_prefix_is_put_once() -> None:
    assert cb.title_of("CCA", "Tool use") == "CCA - Tool use"
    assert cb.title_of("CCA", "cca - Tool use") == "cca - Tool use"
    assert cb.title_of("", "  Tool   use ") == "Tool use"


# ---- undo --------------------------------------------------------------------------------------
async def test_one_undo_removes_sixty_and_leaves_a_changed_event_alone(rig: Rig) -> None:
    made = (await rig.approved(cb.CREATE, {"events": sessions(60)})).result
    changed = made["items"][9]["id"]
    rig.fake.owner_edits(changed, summary="Topic 10 (moved to the library)")
    asked = await rig.run(cb.UNDO, {"batch": made["batch"]})
    assert asked.outcome is GatewayOutcome.AWAITING_CONFIRMATION and asked.pending is not None
    assert "Remove 59 events" in asked.pending.summary
    assert "1 that you changed since is left alone" in asked.pending.summary
    assert len(rig.fake.live()) == 60  # the model asking is a card: nothing removed yet
    out = await rig.run(cb.UNDO, {"batch": made["batch"]}, confirmation_id=asked.pending.id)
    res = out.result
    assert (res["removed"], res["kept"], res["failed"]) == (59, 1, 0)
    assert res["message"] == (
        "Removed 59 events, Sir. Each is in Recently deleted for 30 days. "
        "1 event you changed since was left alone."
    )
    assert [e["id"] for e in rig.fake.live()] == [changed]
    kept = await rig.bin.store.recent(UID, limit=100)  # the panel itself lists the newest 50
    assert len(kept) == 59 and all(i.kind == "event" for i in kept)  # each can come back
    assert all(r.url.params["sendUpdates"] == "none" for r in rig.fake.sent("DELETE"))


async def test_undo_of_an_unknown_batch_proposes_nothing(rig: Rig) -> None:
    out = await rig.run(cb.UNDO, {"batch": "b" + "0" * 16})
    assert out.outcome is GatewayOutcome.ERROR and "no events of that batch" in (out.error or "")
    bad = await rig.run(cb.UNDO, {"batch": "../x"})
    assert bad.outcome is GatewayOutcome.ERROR and await rig.gw.pending() == []


async def test_without_recently_deleted_nothing_is_removed() -> None:
    fake = PlanGoogle()
    conn = await connector(fake)
    rig = Rig(fake, conn)
    made = (await rig.approved(cb.CREATE, {"events": sessions(2)})).result
    rig.api._undo = lambda: None  # noqa: SLF001 - a server without persistent storage
    out = await rig.approved(cb.UNDO, {"batch": made["batch"]})
    assert out.result["unavailable"] is True and "Recently deleted" in out.result["message"]
    assert len(fake.live()) == 2


def test_the_undo_card_says_what_goes_and_what_stays() -> None:
    events = [
        {"start": {"dateTime": "2026-11-16T19:00:00+05:30"}},
        {"start": {"dateTime": "2026-11-20T19:00:00+05:30"}},
    ]
    text = undo_card(events, kept=0)
    assert text.splitlines()[0] == (
        "Remove 2 events of one batch from your calendar: 16 Nov 2026 to 20 Nov 2026."
    )
    assert "Recently deleted for 30 days" in text
    assert "nothing will be removed" in undo_card(events, kept=2)


def test_a_change_by_the_owner_is_seen_and_jarvis_s_own_stamp_is_not() -> None:
    body = {
        "summary": "Topic 1",
        "start": {"dateTime": "2026-11-16T19:00:00+05:30"},
        "end": {"dateTime": "2026-11-16T20:00:00+05:30"},
    }
    event = cb.stamped(body, "b" + "1" * 16, 4)
    assert cb.number_of(event, "b" + "1" * 16) == 4 and cb.number_of(event, "b" + "2" * 16) is None
    assert cb.changed_by_owner(event) is False
    # Google answers in another offset and with tidy spaces: still JARVIS's own
    same = {**event, "summary": "Topic  1 ", "start": {"dateTime": "2026-11-16T13:30:00Z"}}
    assert cb.changed_by_owner(same) is False
    assert cb.changed_by_owner({**event, "location": "Library"}) is True
    assert cb.changed_by_owner({**event, "end": {"dateTime": "2026-11-16T21:00:00+05:30"}}) is True


# ---- many single calls -------------------------------------------------------------------------
def _singles(n: int, **extra: Any) -> list[ToolCall]:
    return [call(cb.SINGLE, i, **e, **extra) for i, e in enumerate(sessions(n))]


def test_more_than_three_single_creates_become_one_batch_call(rig: Rig) -> None:
    calls = [call("calendar_list_events", 99, start="a", end="b"), *_singles(60)]
    run, spread = cb.gathered(calls, rig.gw.registry, 100)
    assert [c.name for c in run] == ["calendar_list_events", cb.CREATE]
    assert run[1].id == calls[1].id and len(run[1].arguments["events"]) == 60
    read = GatewayResult(GatewayOutcome.EXECUTED, result={})
    card = GatewayResult(GatewayOutcome.AWAITING_CONFIRMATION)
    back = spread([read, card])
    assert len(back) == 61 and back[0] is read and back[1] is card
    assert all(r.outcome is GatewayOutcome.DENIED and r.error == cb.MERGED for r in back[2:])
    assert all(not r.ran for r in back[2:])


def test_three_singles_a_guest_or_a_bad_call_are_left_as_they_are(rig: Rig) -> None:
    three = _singles(3)
    run, spread = cb.gathered(three, rig.gw.registry, 100)
    assert run == three and spread([1, 2, 3]) == [1, 2, 3]  # type: ignore[list-item]
    mixed = _singles(4)
    mixed[0] = call(cb.SINGLE, 0, **{**sessions(1)[0], "attendees": ["a@example.com"]})
    mixed[1] = call(cb.SINGLE, 1, summary="no times")
    assert cb.gathered(mixed, rig.gw.registry, 100)[0] == mixed  # only two could merge
    many, _ = cb.gathered(_singles(7), rig.gw.registry, 3)  # more than a batch holds: batches
    assert [len(c.arguments["events"]) for c in many] == [3, 3, 1]


async def test_a_brain_that_makes_sixty_single_calls_still_ends_in_one_card(
    rig: Rig, settings: Settings
) -> None:
    mind = ScriptedBrain()
    brain = Brain(
        router=ModelRouter(mind, TIERS),
        store=InMemorySessionStore(),
        settings=settings,
        gateway=rig.gw,
    )
    mind.say(Said(calls=tuple(_singles(60))), Said("All sixty are on one card for you, Sir."))
    resp = await brain.chat(ChatRequest(message="add these sixty sessions", user_id=UID))
    assert resp.reply == "All sixty are on one card for you, Sir."
    [card] = resp.pending_approvals
    assert card.tool == cb.CREATE and len(card.arguments["events"]) == 60
    assert rig.posts() == [] and len(await rig.gw.pending()) == 1
    told = [
        b for b in mind.calls[1].messages[-1].content if getattr(b, "type", "") == "tool_result"
    ]
    assert len(told) == 60  # every call got its answer back
    assert (
        "awaiting_owner_approval" in told[0].content and "single approval card" in told[1].content
    )
