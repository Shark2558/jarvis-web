# tests/test_trust_outside.py — slice 11 D8 (security review of A+B): what JARVIS writes from other
# people's words stays theirs. A write whose card was proposed in a round that had read outside
# content (or that runs inside such a round) marks the event / reminder (extendedProperties) or the
# to-do (the owner's outside set on the Docs port); a marked item is never the owner's own, so a
# later look-up of it is untrusted. Restores keep the item's verdict. Plus the undo bin's results.
from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
from google_fakes import GOOGLE_NOW, FakeGoogle
from tasks_fakes import FakeTasks, tasks_connector

from jarvis.core.guardrails import ActionRisk, ConfirmationGate, PendingAction
from jarvis.integrations.google import GoogleConnector
from jarvis.llm.base import ToolCall
from jarvis.storage.docs import MemoryDocs
from jarvis.tools import task_marks
from jarvis.tools.audit import AuditLog
from jarvis.tools.base import Tool
from jarvis.tools.calendar_undo import owner_authored as calendar_owner_authored
from jarvis.tools.context import require_tool_context
from jarvis.tools.gateway import Gateway, GatewayOutcome, GatewayResult
from jarvis.tools.google_calendar import calendar_tools
from jarvis.tools.google_tasks import tasks_tools
from jarvis.tools.policy import Policy
from jarvis.tools.provenance import (
    OUTSIDE_KEY,
    OUTSIDE_VALUE,
    is_marked_outside,
    is_owner_authored_event,
    is_owner_authored_task,
    mark_outside,
)
from jarvis.tools.registry import ToolRegistry
from jarvis.tools.reminders import reminder_tools
from jarvis.tools.taint import content_tainted, context_trust
from jarvis.tools.task_marks import OutsideSet, OutsideTasks, owner_authored_task
from jarvis.undo.service import UndoBin
from jarvis.undo.store import DeletedStore
from jarvis.undo.tools import undo_tools

UID = "u_owner"
SCOPE = f"{UID}:sess_1"
NOW = datetime.fromtimestamp(GOOGLE_NOW, UTC)
CAL = "https://www.googleapis.com/calendar/v3"
EVENTS = f"{CAL}/calendars/primary/events"
TZ_URL = f"{CAL}/users/me/calendarList/primary"
ME = {"email": "akash@example.com", "self": True}
MARK = {OUTSIDE_KEY: OUTSIDE_VALUE}
GMAIL_LINK = [{"type": "email", "link": "https://mail.google.com/mail/#all/1"}]


class FailingDocs(MemoryDocs):
    async def write(self, ops: Any) -> None:
        raise RuntimeError("store down")

    async def transaction(self, fn: Any) -> Any:
        raise RuntimeError("store down")


class UnreadableDocs(MemoryDocs):
    async def get(self, path: str) -> Any:
        raise RuntimeError("store down")


def _event(eid: str = "evdentist1", **over: Any) -> dict[str, Any]:
    e: dict[str, Any] = {
        "id": eid,
        "summary": "Dentist",
        "eventType": "default",
        "start": {"dateTime": "2027-01-15T16:00:00+05:30", "timeZone": "Asia/Kolkata"},
        "end": {"dateTime": "2027-01-15T16:30:00+05:30", "timeZone": "Asia/Kolkata"},
        "organizer": dict(ME),
        "creator": dict(ME),
        "htmlLink": f"https://calendar.google.com/event?eid={eid}",
    }
    e.update(over)
    return e


async def _approve(gw: Gateway, call: ToolCall, *, spoken: bool = False) -> GatewayResult:
    """Propose `call` in a round that read outside content (or only a spoken one), then run it
    as the owner's approval does: outside any turn, with the card's token."""
    with context_trust(untrusted=not spoken, spoken=spoken):
        card = await gw.execute(call, scope=SCOPE)
    assert card.outcome is GatewayOutcome.AWAITING_CONFIRMATION and card.pending is not None
    return await gw.execute(call, scope=SCOPE, confirmation_id=card.pending.id)


# ---- the rule -----------------------------------------------------------------------------------


def test_a_marked_event_is_never_the_owners_own() -> None:
    own = _event()
    assert is_owner_authored_event(own) and not is_marked_outside(own)
    marked = mark_outside(own)
    assert is_marked_outside(marked) and not is_owner_authored_event(marked)
    assert own.get("extendedProperties") is None  # a new body, the old one untouched


def test_mark_outside_keeps_every_extended_property_the_event_has() -> None:
    current = _event(
        extendedProperties={"private": {"jarvis": "reminder", "x": "1"}, "shared": {"s": "2"}}
    )
    body = mark_outside({"summary": "New"}, current)
    assert body["summary"] == "New"
    assert body["extendedProperties"] == {
        "private": {"jarvis": "reminder", "x": "1", **MARK},
        "shared": {"s": "2"},
    }
    sent = mark_outside({"extendedProperties": {"private": {"jarvis": "reminder"}}})
    assert sent["extendedProperties"]["private"] == {"jarvis": "reminder", **MARK}


def test_a_todo_in_the_outside_set_or_with_an_unreadable_set_is_not_his_own() -> None:
    t = {"id": "t1", "title": "Pay"}
    assert is_owner_authored_task(t)
    assert not is_owner_authored_task(t, outside={"t1"})
    assert not is_owner_authored_task(t, outside=None)
    assert not owner_authored_task(t, None)


def test_the_calendar_undo_rule_is_the_provenance_rule() -> None:
    for e in (_event(), _event(eventType="birthday"), mark_outside(_event()), _event(creator={})):
        assert calendar_owner_authored(e) is is_owner_authored_event(e)


# ---- the outside set --------------------------------------------------------------------------


async def test_the_outside_set_marks_existing_and_new_todos() -> None:
    marks = OutsideTasks(MemoryDocs(), clock=lambda: NOW)
    assert await marks.read(UID) == OutsideSet(frozenset(), None)
    await marks.add(UID, ["t1"])
    token = await marks.begin(UID)
    pending = await marks.read(UID)
    assert pending is not None and pending.pending_since == NOW - task_marks.PENDING_MARGIN
    await marks.finish(UID, token, ["t2"])
    done = await marks.read(UID)
    assert done == OutsideSet(frozenset({"t1", "t2"}), None)
    assert not done.owner_authored({"id": "t2"}) and done.owner_authored({"id": "t3"})


async def test_an_unfinished_mark_makes_every_recently_changed_todo_outside() -> None:
    docs = MemoryDocs()
    marks = OutsideTasks(docs, clock=lambda: NOW)
    await marks.begin(UID)
    # the id never arrives (the second write failed): fail closed on read
    broken = OutsideTasks(FailingDocs(), clock=lambda: NOW)
    await broken.finish(UID, "nope", ["t9"])  # logged, never raised
    got = await marks.read(UID)
    assert got is not None
    late = (NOW - timedelta(minutes=1)).isoformat()
    early = (NOW - timedelta(days=1)).isoformat()
    assert not got.owner_authored({"id": "t9", "updated": late})
    assert not got.owner_authored({"id": "t9"})  # no readable `updated`: outside
    assert got.owner_authored({"id": "t0", "updated": early})


async def test_an_unreadable_or_malformed_set_reads_as_none() -> None:
    assert await OutsideTasks(UnreadableDocs()).read(UID) is None
    docs = MemoryDocs()
    docs._data["jarvis_outside_tasks/u_owner"] = {"ids": "t1", "pending": {}}
    assert await OutsideTasks(docs).read(UID) is None
    docs._data["jarvis_outside_tasks/u_owner"] = {"ids": [], "pending": {"x": "not a time"}}
    odd = await OutsideTasks(docs).read(UID)
    assert odd is not None and not odd.owner_authored({"id": "t0", "updated": "2001-01-01"})
    assert await OutsideTasks(MemoryDocs()).read("../x") is None


async def test_marks_fail_loudly_when_they_cannot_be_kept(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(RuntimeError):
        await OutsideTasks(FailingDocs()).add(UID, ["t1"])
    with pytest.raises(RuntimeError):
        await OutsideTasks(FailingDocs()).begin(UID)
    with pytest.raises(ValueError):
        await OutsideTasks(MemoryDocs()).add("", ["t1"])
    monkeypatch.setattr(task_marks, "MAX_IDS", 2)
    full = OutsideTasks(MemoryDocs())
    await full.add(UID, ["a", "b"])
    with pytest.raises(RuntimeError, match="too many"):
        await full.add(UID, ["c"])


# ---- which rounds count -----------------------------------------------------------------------


def test_content_taint_is_other_peoples_content_only() -> None:
    assert content_tainted() is False  # outside any turn
    with context_trust(untrusted=True):
        assert content_tainted() is True
    with context_trust(untrusted=False, spoken=True):
        assert content_tainted() is False  # the owner said it; a card still asks
    with context_trust(untrusted=True, spoken=True):
        assert content_tainted() is True


def _recording_gateway() -> tuple[Gateway, list[bool]]:
    seen: list[bool] = []

    def note_add(a: dict[str, Any]) -> dict[str, Any]:
        seen.append(require_tool_context().outside)
        return {"added": a["text"]}

    schema = {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]}
    reg = ToolRegistry()
    reg.register(Tool("note_add", "Add a note.", schema, ActionRisk.REVERSIBLE, note_add))
    return Gateway(registry=reg, policy=Policy(), gate=ConfirmationGate(), audit=AuditLog()), seen


ADD = ToolCall(id="n", name="note_add", arguments={"text": "from the mail"})


async def test_an_approved_card_writes_as_its_proposing_round_would() -> None:
    gw, seen = _recording_gateway()
    with context_trust(untrusted=False):
        await gw.execute(ADD, scope=SCOPE)  # a clean round: runs, nothing outside
    assert (await _approve(gw, ADD)).outcome is GatewayOutcome.EXECUTED
    assert (await _approve(gw, ADD, spoken=True)).outcome is GatewayOutcome.EXECUTED
    assert seen == [False, True, False]  # clean · read a mail · spoken only


async def test_a_card_records_the_outside_flag_and_a_duplicate_never_forgets_it() -> None:
    gw, seen = _recording_gateway()
    with context_trust(untrusted=False, spoken=True):
        first = await gw.execute(ADD, scope=SCOPE)
    assert first.pending is not None and first.pending.outside is False
    with context_trust(untrusted=True):
        again = await gw.execute(ADD, scope=SCOPE)
    assert again.pending is not None and again.pending.id == first.pending.id
    stored = await gw.gate.get(first.pending.id)
    assert stored is not None and stored.outside is True
    await gw.execute(ADD, scope=SCOPE, confirmation_id=first.pending.id)
    assert seen == [True]


async def test_a_card_re_proposed_because_it_changed_keeps_its_outside_flag() -> None:
    from jarvis.tools.base import Preview

    title = {"now": "Pay invoice"}

    async def preview(a: dict[str, Any]) -> Preview:
        return Preview(f"Add note under “{title['now']}”")

    schema = {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]}
    tool = Tool("note_add", "Add.", schema, ActionRisk.REVERSIBLE, lambda a: a, preview=preview)
    reg = ToolRegistry()
    reg.register(tool)
    gw = Gateway(registry=reg, policy=Policy(), gate=ConfirmationGate(), audit=AuditLog())
    with context_trust(untrusted=True):
        card = (await gw.execute(ADD, scope=SCOPE)).pending
    assert card is not None and card.outside is True
    title["now"] = "Pay invoice (edited)"  # the card no longer reads as the owner saw it
    again = await gw.execute(ADD, scope=SCOPE, confirmation_id=card.id)
    assert again.outcome is GatewayOutcome.AWAITING_CONFIRMATION and again.pending is not None
    assert again.pending.id != card.id and again.pending.outside is True


async def test_a_card_stored_before_the_flag_existed_counts_as_outside() -> None:
    gw, seen = _recording_gateway()
    legacy = PendingAction(
        tool="note_add",
        arguments=dict(ADD.arguments),
        risk=ActionRisk.IRREVERSIBLE,
        summary=gw.registry.get("note_add").summary(ADD.arguments),  # type: ignore[union-attr]
        scope=SCOPE,
        tool_risk=ActionRisk.REVERSIBLE,
    )
    assert legacy.outside is None
    await gw.gate.store.put(legacy)
    out = await gw.execute(ADD, scope=SCOPE, confirmation_id=legacy.id)
    assert out.outcome is GatewayOutcome.EXECUTED and seen == [True]


# ---- events and reminders -----------------------------------------------------------------------


@pytest.fixture
def cal(connected: GoogleConnector, fake_google: FakeGoogle) -> Gateway:
    fake_google.on("GET", TZ_URL, httpx.Response(200, json={"timeZone": "Asia/Kolkata"}))
    reg = ToolRegistry()
    for t in calendar_tools(connected) + reminder_tools(connected, clock=lambda: NOW):
        reg.register(t)
    return Gateway(registry=reg, policy=Policy(), gate=ConfirmationGate(), audit=AuditLog())


def _body(fake: FakeGoogle, method: str, suffix: str) -> dict[str, Any]:
    return json.loads(fake.sent(method, suffix)[-1].content)  # type: ignore[no-any-return]


async def test_an_event_made_from_outside_content_is_marked_and_untrusted(
    cal: Gateway, fake_google: FakeGoogle
) -> None:
    fake_google.on("POST", EVENTS, httpx.Response(200, json=mark_outside(_event())))
    args = {"summary": "Dentist", "start": "2027-01-15T16:00:00", "end": "2027-01-15T16:30:00"}
    out = await _approve(cal, ToolCall(id="c", name="calendar_create_event", arguments=args))
    assert out.outcome is GatewayOutcome.EXECUTED and out.trusted is False
    sent = _body(fake_google, "POST", "/calendars/primary/events")
    assert sent["extendedProperties"]["private"] == MARK
    fake_google.on("GET", EVENTS, httpx.Response(200, json={"items": [mark_outside(_event())]}))
    listed = await cal.execute(
        ToolCall(id="l", name="calendar_list_events",
                 arguments={"start": "2027-01-15T00:00:00", "end": "2027-01-16T00:00:00"}),
        scope=SCOPE,
    )  # fmt: skip
    assert listed.outcome is GatewayOutcome.EXECUTED and listed.trusted is False


async def test_an_event_changed_from_outside_content_keeps_its_properties_and_is_marked(
    cal: Gateway, fake_google: FakeGoogle
) -> None:
    current = _event(extendedProperties={"private": {"note": "x"}, "shared": {"s": "1"}})
    fake_google.on("GET", f"{EVENTS}/evdentist1", httpx.Response(200, json=current))
    fake_google.on("PATCH", f"{EVENTS}/evdentist1", httpx.Response(200, json=mark_outside(current)))
    call = ToolCall(id="c", name="calendar_update_event",
                    arguments={"event_id": "evdentist1", "location": "Smile Clinic"})  # fmt: skip
    out = await _approve(cal, call)
    assert out.outcome is GatewayOutcome.EXECUTED and out.trusted is False
    sent = _body(fake_google, "PATCH", "/events/evdentist1")
    assert sent["location"] == "Smile Clinic"
    assert sent["extendedProperties"] == {"private": {"note": "x", **MARK}, "shared": {"s": "1"}}


async def test_a_change_from_a_clean_round_is_not_marked(
    cal: Gateway, fake_google: FakeGoogle
) -> None:
    fake_google.on("GET", f"{EVENTS}/evdentist1", httpx.Response(200, json=_event()))
    fake_google.on("PATCH", f"{EVENTS}/evdentist1", httpx.Response(200, json=_event()))
    call = ToolCall(id="c", name="calendar_update_event",
                    arguments={"event_id": "evdentist1", "location": "x"})  # fmt: skip
    with context_trust(untrusted=False):
        out = await cal.execute(call, scope=SCOPE)
    assert out.outcome is GatewayOutcome.EXECUTED and out.trusted is True
    assert "extendedProperties" not in _body(fake_google, "PATCH", "/events/evdentist1")


async def test_reminders_from_outside_content_keep_their_tag_and_are_marked(
    cal: Gateway, fake_google: FakeGoogle
) -> None:
    tag = {"private": {"jarvis": "reminder"}}
    made = mark_outside(_event("remnew001", extendedProperties=tag))
    fake_google.on("POST", EVENTS, httpx.Response(200, json=made))
    add = ToolCall(id="a", name="reminder_add",
                   arguments={"text": "wire money", "when": "2027-01-15T18:00:00"})  # fmt: skip
    out = await _approve(cal, add)
    assert out.outcome is GatewayOutcome.EXECUTED and out.trusted is False
    assert _body(fake_google, "POST", "/calendars/primary/events")["extendedProperties"] == {
        "private": {"jarvis": "reminder", **MARK}
    }
    rem = _event("remravi01", summary="⏰ call Ravi", extendedProperties=tag)
    fake_google.on("GET", f"{EVENTS}/remravi01", httpx.Response(200, json=rem))
    fake_google.on("PATCH", f"{EVENTS}/remravi01", httpx.Response(200, json=mark_outside(rem)))
    upd = ToolCall(id="u", name="reminder_update",
                   arguments={"event_id": "remravi01", "text": "call Ravi now"})  # fmt: skip
    changed = await _approve(cal, upd)
    assert changed.outcome is GatewayOutcome.EXECUTED and changed.trusted is False
    assert _body(fake_google, "PATCH", "/events/remravi01")["extendedProperties"]["private"] == {
        "jarvis": "reminder",
        **MARK,
    }


# ---- to-dos -------------------------------------------------------------------------------------


def _todos() -> FakeTasks:
    fake = FakeTasks(lists=[{"id": "L1", "title": "My Tasks"}])
    fake.add("L1", "Call plumber", id="t_plumb", notes="Leak under the sink")
    return fake


async def _tgw(fake: FakeTasks, marks: OutsideTasks, undo: UndoBin | None = None) -> Gateway:
    reg = ToolRegistry()
    conn = await tasks_connector(fake)
    for t in tasks_tools(conn, default_tz="Asia/Kolkata", clock=lambda: NOW, undo=undo,
                         marks=marks):  # fmt: skip
        reg.register(t)
    for t in undo_tools(undo) if undo is not None else []:
        reg.register(t)
    return Gateway(registry=reg, policy=Policy(), gate=ConfirmationGate(), audit=AuditLog())


LIST = ToolCall(id="l", name="tasks_list", arguments={})
ADD_TODO = ToolCall(id="a", name="task_add",
                    arguments={"title": "Pay invoice", "notes": "to account 0000"})  # fmt: skip


async def _list(gw: Gateway) -> GatewayResult:
    with context_trust(untrusted=False):
        return await gw.execute(LIST, scope=SCOPE)


async def test_a_todo_added_from_a_mail_is_marked_and_its_list_is_untrusted() -> None:
    fake, marks = _todos(), OutsideTasks(MemoryDocs(), clock=lambda: NOW)
    gw = await _tgw(fake, marks)
    assert (await _list(gw)).trusted is True
    out = await _approve(gw, ADD_TODO)
    assert out.outcome is GatewayOutcome.EXECUTED and out.trusted is False
    new_id = fake.changes("insert")[0].task_id
    got = await marks.read(UID)
    assert got is not None and new_id in got.ids and got.pending_since is None
    assert (await _list(gw)).trusted is False


async def test_a_todo_added_in_a_clean_round_stays_the_owners_own() -> None:
    fake, marks = _todos(), OutsideTasks(MemoryDocs(), clock=lambda: NOW)
    gw = await _tgw(fake, marks)
    with context_trust(untrusted=False):
        out = await gw.execute(ADD_TODO, scope=SCOPE)
    assert out.outcome is GatewayOutcome.EXECUTED and out.trusted is True
    assert (await _list(gw)).trusted is True


async def test_no_pending_mark_no_new_todo() -> None:
    fake = _todos()
    gw = await _tgw(fake, OutsideTasks(FailingDocs()))
    out = await _approve(gw, ADD_TODO)
    assert out.outcome is GatewayOutcome.ERROR and fake.changes("insert") == []


async def test_a_lost_mark_after_the_add_keeps_recent_todos_outside() -> None:
    class SecondWriteFails(MemoryDocs):
        calls = 0

        async def transaction(self, fn: Any) -> Any:
            SecondWriteFails.calls += 1
            if SecondWriteFails.calls > 1:
                raise RuntimeError("store down")
            return await super().transaction(fn)

    fake, docs = _todos(), SecondWriteFails()
    marks = OutsideTasks(docs, clock=lambda: NOW)
    gw = await _tgw(fake, marks)
    out = await _approve(gw, ADD_TODO)
    assert out.outcome is GatewayOutcome.EXECUTED and out.trusted is False
    got = await marks.read(UID)
    assert got is not None and got.ids == frozenset() and got.pending_since is not None
    assert (await _list(gw)).trusted is False  # the fake keeps no `updated`: all outside


async def test_a_todo_changed_from_a_mail_is_marked_before_it_changes() -> None:
    fake, marks = _todos(), OutsideTasks(MemoryDocs(), clock=lambda: NOW)
    gw = await _tgw(fake, marks)
    upd = ToolCall(id="u", name="task_update",
                   arguments={"task_id": "L1:t_plumb", "notes": "call +1-900"})  # fmt: skip
    out = await _approve(gw, upd)
    assert out.outcome is GatewayOutcome.EXECUTED and out.trusted is False
    got = await marks.read(UID)
    assert got is not None and "t_plumb" in got.ids
    blocked = await _tgw(_todos(), OutsideTasks(FailingDocs()))
    failed = await _approve(blocked, upd)
    assert failed.outcome is GatewayOutcome.ERROR


async def test_an_unreadable_set_makes_every_todo_untrusted() -> None:
    gw = await _tgw(_todos(), OutsideTasks(UnreadableDocs()))
    out = await _list(gw)
    assert out.outcome is GatewayOutcome.EXECUTED and out.trusted is False


# ---- Recently deleted -------------------------------------------------------------------------


async def test_todo_delete_list_and_restore_are_trusted_by_the_kept_flag() -> None:
    fake, marks = _todos(), OutsideTasks(MemoryDocs(), clock=lambda: NOW)
    fake.add("L1", "Invoice from vendor", id="t_mail", links=GMAIL_LINK)
    undo = UndoBin(DeletedStore(MemoryDocs()), clock=lambda: NOW)
    gw = await _tgw(fake, marks, undo)

    async def run(name: str, args: dict[str, Any]) -> GatewayResult:
        with context_trust(untrusted=False):
            return await gw.execute(ToolCall(id="x", name=name, arguments=args), scope=SCOPE)

    own = await run("task_delete", {"task_id": "L1:t_plumb"})
    assert own.outcome is GatewayOutcome.EXECUTED and own.trusted is True
    assert (await run("deleted_list", {})).trusted is True
    back = await run("deleted_restore", {"undo_id": own.result["undo_id"]})
    assert back.outcome is GatewayOutcome.EXECUTED and back.trusted is True
    got = await marks.read(UID)
    assert got is not None and got.ids == frozenset()  # the owner's own: nothing marked

    mail = await run("task_delete", {"task_id": "L1:t_mail"})
    assert mail.outcome is GatewayOutcome.EXECUTED and mail.trusted is False
    assert (await run("deleted_list", {})).trusted is False
    again = await run("deleted_restore", {"undo_id": mail.result["undo_id"]})
    assert again.outcome is GatewayOutcome.EXECUTED and again.trusted is False
    got = await marks.read(UID)
    restored_id = fake.changes("insert")[-1].task_id
    assert got is not None and restored_id in got.ids  # Google won't recreate its link: marked
    assert (await _list(gw)).trusted is False


async def test_event_delete_and_restore_keep_the_events_verdict(
    connected: GoogleConnector, fake_google: FakeGoogle
) -> None:
    fake_google.on("GET", TZ_URL, httpx.Response(200, json={"timeZone": "Asia/Kolkata"}))
    undo = UndoBin(DeletedStore(MemoryDocs()), clock=lambda: NOW)
    reg = ToolRegistry()
    for t in calendar_tools(connected, undo=undo) + undo_tools(undo):
        reg.register(t)
    gw = Gateway(registry=reg, policy=Policy(), gate=ConfirmationGate(), audit=AuditLog())

    async def run(name: str, args: dict[str, Any]) -> GatewayResult:
        with context_trust(untrusted=False):
            return await gw.execute(ToolCall(id="x", name=name, arguments=args), scope=SCOPE)

    for eid, event, trusted in (
        ("evmine0001", _event("evmine0001"), True),
        ("evout00001", mark_outside(_event("evout00001")), False),
    ):
        fake_google.on("GET", f"{EVENTS}/{eid}", httpx.Response(200, json=event))
        fake_google.on("DELETE", f"{EVENTS}/{eid}", httpx.Response(204))
        gone = await run("calendar_delete_event", {"event_id": eid})
        assert gone.outcome is GatewayOutcome.EXECUTED and gone.trusted is trusted, gone.error
        fake_google.on("POST", EVENTS, httpx.Response(200, json=_event("evback0001")))
        back = await run("deleted_restore", {"undo_id": gone.result["undo_id"]})
        assert back.outcome is GatewayOutcome.EXECUTED and back.trusted is trusted
        sent = _body(fake_google, "POST", "/calendars/primary/events")
        assert is_marked_outside(sent) is (not trusted)
