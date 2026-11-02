# tests/test_trust_tools.py — slice 11 D8: the calendar, reminder and to-do tools vouch for a result
# only when every item in it is the owner's own; list tools take a `query`. Over the scripted fake
# Google transport and the in-memory Tasks fake; nothing touches the network. Written before the
# implementation.
from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest
from google_fakes import GOOGLE_NOW, FakeGoogle
from tasks_fakes import FakeTasks, tasks_connector

from jarvis.core.guardrails import ConfirmationGate
from jarvis.integrations.google import GoogleConnector
from jarvis.llm.base import ToolCall
from jarvis.tools.audit import AuditLog
from jarvis.tools.external import FENCE_END
from jarvis.tools.gateway import Gateway, GatewayOutcome, GatewayResult
from jarvis.tools.google_calendar import calendar_tools
from jarvis.tools.google_tasks import tasks_tools
from jarvis.tools.policy import Policy
from jarvis.tools.registry import ToolRegistry
from jarvis.tools.reminders import reminder_tools

CAL = "https://www.googleapis.com/calendar/v3"
EVENTS = f"{CAL}/calendars/primary/events"
TZ_URL = f"{CAL}/users/me/calendarList/primary"
FREEBUSY = f"{CAL}/freeBusy"
SCOPE = "u_owner:sess_1"
NOW = datetime.fromtimestamp(GOOGLE_NOW, UTC)
ME = {"email": "akash@example.com", "self": True}
PRIYA = {"email": "priya@example.com"}
VOUCHING = {
    "calendar_list_events",
    "calendar_free_slots",
    "calendar_create_event",
    "calendar_update_event",
    "reminders_list",
    "reminder_add",
    "reminder_update",
    "tasks_list",
    "task_add",
    "task_update",
    "task_complete",
}
TAG = {"private": {"jarvis": "reminder"}}


def _ev(eid: str, summary: str, **over: Any) -> dict[str, Any]:
    e: dict[str, Any] = {
        "id": eid,
        "summary": summary,
        "eventType": "default",
        "start": {"dateTime": "2027-01-15T15:00:00+05:30", "timeZone": "Asia/Kolkata"},
        "end": {"dateTime": "2027-01-15T16:00:00+05:30", "timeZone": "Asia/Kolkata"},
        "organizer": dict(ME),
        "creator": dict(ME),
        "htmlLink": f"https://calendar.google.com/event?eid={eid}",
    }
    e.update(over)
    return e


OWN = _ev("evdentist1", "Dentist")
INVITE = _ev("evlunch01", "Lunch", organizer=PRIYA, creator=PRIYA,
             attendees=[dict(ME), PRIYA])  # fmt: skip
GMAIL = _ev("evflight01", "Flight to Delhi", eventType="fromGmail")


def _registry(conn: GoogleConnector) -> ToolRegistry:
    reg = ToolRegistry()
    for t in calendar_tools(conn) + reminder_tools(conn, clock=lambda: NOW):
        reg.register(t)
    return reg


@pytest.fixture
def gw(connected: GoogleConnector, fake_google: FakeGoogle) -> Gateway:
    fake_google.on("GET", TZ_URL, httpx.Response(200, json={"timeZone": "Asia/Kolkata"}))
    return Gateway(
        registry=_registry(connected), policy=Policy(), gate=ConfirmationGate(), audit=AuditLog()
    )


async def _run(gw: Gateway, name: str, args: dict[str, Any]) -> GatewayResult:
    return await gw.execute(ToolCall(id="c", name=name, arguments=args), scope=SCOPE)


WINDOW = {"start": "2027-01-15T00:00:00", "end": "2027-01-16T00:00:00"}


# ---- which tools may vouch ----------------------------------------------------------------------


async def test_only_the_owners_calendar_reminder_and_todo_tools_may_vouch(
    gw: Gateway,
) -> None:
    conn_tools = {t.name: t for t in gw.registry._tools.values()}
    fake = FakeTasks()
    for t in tasks_tools(await tasks_connector(fake)):
        conn_tools[t.name] = t
    assert {n for n, t in conn_tools.items() if t.may_vouch} == VOUCHING
    # deletes are workstream A's (undo bin): their results stay untrusted until A vouches
    assert not conn_tools["calendar_delete_event"].may_vouch
    assert not conn_tools["task_delete"].may_vouch
    assert all(not t.trusted_output for t in conn_tools.values())


def test_mail_web_documents_and_memory_tools_never_vouch() -> None:
    from jarvis.documents.tools import document_tools
    from jarvis.recall.tools import memory_tools
    from jarvis.tools.builtin import InMemoryWorld, builtin_tools
    from jarvis.tools.gmail import gmail_tools
    from jarvis.web.tools import web_tools

    others = (
        gmail_tools(object())  # type: ignore[arg-type]
        + web_tools(object())  # type: ignore[arg-type]
        + document_tools(object())  # type: ignore[arg-type]
        + memory_tools(object())  # type: ignore[arg-type]
        + builtin_tools(InMemoryWorld())
    )
    assert others and not any(t.may_vouch for t in others)


# ---- calendar_list_events -------------------------------------------------------------------


@pytest.mark.parametrize(
    ("items", "trusted"),
    [
        ([OWN], True),
        ([], True),  # nothing in it: nobody's words
        ([_ev("evremind01", "⏰ call Ravi", extendedProperties=TAG)], True),
        ([OWN, INVITE], False),  # an invite from someone else in the same result
        ([OWN, GMAIL], False),
        ([_ev("evdeleg01", "Board prep", creator=PRIYA)], False),  # a delegate made it
        ([_ev("evomit001", "Offsite", attendeesOmitted=True)], False),
        ([_ev("evbday001", "Ravi's birthday", eventType="birthday")], False),
        ([{k: v for k, v in OWN.items() if k != "creator"}], False),
    ],
)
async def test_list_events_is_trusted_only_when_every_event_is_the_owners_own(
    gw: Gateway, fake_google: FakeGoogle, items: list[dict[str, Any]], trusted: bool
) -> None:
    fake_google.on("GET", EVENTS, httpx.Response(200, json={"items": items}))
    out = await _run(gw, "calendar_list_events", WINDOW)
    assert out.outcome is GatewayOutcome.EXECUTED and out.trusted is trusted
    if items:  # fencing and trust are independent: titles stay fenced either way
        assert FENCE_END.search(out.for_model())


async def test_list_events_passes_the_query_to_google(gw: Gateway, fake_google: FakeGoogle) -> None:
    fake_google.on("GET", EVENTS, httpx.Response(200, json={"items": [OWN]}))
    await _run(gw, "calendar_list_events", {**WINDOW, "query": "dentist"})
    req = fake_google.sent("GET", "/calendars/primary/events")[-1]
    assert req.url.params["q"] == "dentist"
    spec = gw.registry.get("calendar_list_events")
    assert spec is not None and "query" in spec.input_schema["properties"]
    assert "change or delete" in spec.input_schema["properties"]["query"]["description"]


async def test_a_failed_list_is_untrusted(gw: Gateway, fake_google: FakeGoogle) -> None:
    fake_google.on("GET", EVENTS, httpx.Response(500, json={"error": {"message": "x"}}))
    out = await _run(gw, "calendar_list_events", WINDOW)
    assert out.outcome is GatewayOutcome.ERROR and out.trusted is False


# ---- free slots, create, update -------------------------------------------------------------


async def test_free_slots_carry_times_only_and_are_trusted(
    gw: Gateway, fake_google: FakeGoogle
) -> None:
    busy = {"calendars": {"primary": {"busy": [
        {"start": "2027-01-15T10:00:00+05:30", "end": "2027-01-15T11:00:00+05:30"},
    ]}}}  # fmt: skip
    fake_google.on("POST", FREEBUSY, httpx.Response(200, json=busy))
    out = await _run(
        gw, "calendar_free_slots", {**WINDOW, "duration_min": 30, "working_hours": "09:00-18:00"}
    )
    assert out.outcome is GatewayOutcome.EXECUTED and out.trusted is True
    assert set(out.result) == {"time_zone", "slots"}
    assert all(set(s) == {"start", "end"} for s in out.result["slots"])


async def test_creating_an_event_for_the_owner_alone_is_trusted_and_an_invite_is_not(
    gw: Gateway, fake_google: FakeGoogle
) -> None:
    fake_google.on("POST", EVENTS, httpx.Response(200, json=OWN))
    args = {"summary": "Dentist", "start": "2027-01-15T15:00:00", "end": "2027-01-15T16:00:00"}
    out = await _run(gw, "calendar_create_event", args)
    assert out.outcome is GatewayOutcome.EXECUTED and out.trusted is True
    ret = _ev("evteam0001", "Team", attendees=[dict(ME), PRIYA])
    fake_google.routes[f"POST {EVENTS}"] = [httpx.Response(200, json=ret)]
    call = ToolCall(
        id="c", name="calendar_create_event", arguments={**args, "attendees": [PRIYA["email"]]}
    )
    card = (await gw.execute(call, scope=SCOPE)).pending
    assert card is not None  # an invite is R3: the owner approves it first
    invite = await gw.execute(call, scope=SCOPE, confirmation_id=card.id)
    assert invite.outcome is GatewayOutcome.EXECUTED and invite.trusted is False


async def test_updating_the_owners_own_event_is_trusted(
    gw: Gateway, fake_google: FakeGoogle
) -> None:
    fake_google.on("GET", f"{EVENTS}/evdentist1", httpx.Response(200, json=OWN))
    fake_google.on("PATCH", f"{EVENTS}/evdentist1", httpx.Response(200, json=OWN))
    out = await _run(gw, "calendar_update_event", {"event_id": "evdentist1", "summary": "Dentist"})
    assert out.outcome is GatewayOutcome.EXECUTED and out.trusted is True
    fake_google.routes[f"PATCH {EVENTS}/evdentist1"] = [
        httpx.Response(200, json={**OWN, "creator": PRIYA})
    ]
    again = await _run(gw, "calendar_update_event", {"event_id": "evdentist1", "location": "x"})
    assert again.outcome is GatewayOutcome.EXECUTED and again.trusted is False


# ---- reminders ----------------------------------------------------------------------------------


def _rem(eid: str, **over: Any) -> dict[str, Any]:
    return _ev(eid, "⏰ call Ravi", extendedProperties=TAG, transparency="transparent", **over)


async def test_reminders_list_is_trusted_only_for_the_owners_own_reminders(
    gw: Gateway, fake_google: FakeGoogle
) -> None:
    fake_google.on("GET", EVENTS, httpx.Response(200, json={"items": [_rem("remravi01")]}))
    own = await _run(gw, "reminders_list", {})
    assert own.outcome is GatewayOutcome.EXECUTED and own.trusted is True
    fake_google.routes[f"GET {EVENTS}"] = [
        httpx.Response(200, json={"items": [_rem("remravi01"), _rem("remx00001", creator=PRIYA)]})
    ]
    mixed = await _run(gw, "reminders_list", {})
    assert mixed.trusted is False


async def test_reminders_list_takes_a_query(gw: Gateway, fake_google: FakeGoogle) -> None:
    fake_google.on("GET", EVENTS, httpx.Response(200, json={"items": []}))
    out = await _run(gw, "reminders_list", {"query": "Ravi"})
    assert out.outcome is GatewayOutcome.EXECUTED and out.trusted is True
    req = fake_google.sent("GET", "/calendars/primary/events")[-1]
    assert req.url.params["q"] == "Ravi"
    assert req.url.params["privateExtendedProperty"] == "jarvis=reminder"


async def test_reminder_add_and_update_vouch_by_the_same_rule(
    gw: Gateway, fake_google: FakeGoogle
) -> None:
    fake_google.on("POST", EVENTS, httpx.Response(200, json=_rem("remnew001")))
    add = await _run(gw, "reminder_add", {"text": "call Ravi", "when": "2027-01-15T17:00:00"})
    assert add.outcome is GatewayOutcome.EXECUTED and add.trusted is True
    fake_google.on("GET", f"{EVENTS}/remravi01", httpx.Response(200, json=_rem("remravi01")))
    fake_google.on(
        "PATCH", f"{EVENTS}/remravi01", httpx.Response(200, json=_rem("remravi01", creator=PRIYA))
    )
    upd = await _run(gw, "reminder_update", {"event_id": "remravi01", "text": "call Ravi now"})
    assert upd.outcome is GatewayOutcome.EXECUTED and upd.trusted is False


# ---- to-dos -------------------------------------------------------------------------------------

GMAIL_LINK = [{"type": "email", "description": "Re: invoice",
               "link": "https://mail.google.com/mail/#all/18c0"}]  # fmt: skip


def _todo_fake() -> FakeTasks:
    fake = FakeTasks(lists=[{"id": "L1", "title": "My Tasks"}, {"id": "L2", "title": "Work"}])
    fake.add("L1", "Call plumber", id="t_plumb", due="2027-01-15", notes="Leak under the sink")
    fake.add("L1", "Pay the dentist", id="t_dent", notes="Dr Rao, Friday")
    fake.add("L2", "Review RFP", id="t_rfp", due="2027-01-20")
    fake.add("L2", "Invoice from vendor", id="t_mail", links=GMAIL_LINK)
    fake.add("L2", "Fix clause 4", id="t_doc", assignmentInfo={"surfaceType": "DOCUMENT"})
    return fake


async def _tgw(fake: FakeTasks) -> Gateway:
    reg = ToolRegistry()
    for t in tasks_tools(await tasks_connector(fake), default_tz="Asia/Kolkata",
                         clock=lambda: NOW):  # fmt: skip
        reg.register(t)
    return Gateway(registry=reg, policy=Policy(), gate=ConfirmationGate(), audit=AuditLog())


async def test_tasks_list_is_trusted_only_when_every_shown_todo_is_the_owners_own() -> None:
    gw = await _tgw(_todo_fake())
    mine = await _run(gw, "tasks_list", {"list": "My Tasks"})
    assert mine.outcome is GatewayOutcome.EXECUTED and mine.trusted is True
    work = await _run(gw, "tasks_list", {"list": "Work"})  # a Gmail to-do and a Docs one
    assert work.outcome is GatewayOutcome.EXECUTED and work.trusted is False
    assert FENCE_END.search(mine.for_model())  # still fenced


@pytest.mark.parametrize(
    ("query", "ids", "trusted"),
    [
        ("dentist", ["L1:t_dent"], True),  # title
        ("SINK", ["L1:t_plumb"], True),  # notes, any case
        ("rfp review", ["L2:t_rfp"], True),  # every word, any order
        ("invoice", ["L2:t_mail"], False),  # the target came from Gmail
        ("nothing like this", [], True),  # an empty result is trusted
    ],
)
async def test_tasks_list_query_returns_just_the_target(
    query: str, ids: list[str], trusted: bool
) -> None:
    gw = await _tgw(_todo_fake())
    out = await _run(gw, "tasks_list", {"query": query})
    assert out.outcome is GatewayOutcome.EXECUTED, out.error
    assert [t["id"] for t in out.result["tasks"]] == ids
    assert out.trusted is trusted


@pytest.mark.parametrize("bad", [5, "x" * 201, ["dentist"]])
async def test_tasks_list_query_is_checked(bad: Any) -> None:
    gw = await _tgw(_todo_fake())
    out = await _run(gw, "tasks_list", {"query": bad})
    assert out.outcome is GatewayOutcome.ERROR and "query" in (out.error or "")


@pytest.mark.parametrize("blank", [None, "", "   "])
async def test_a_blank_tasks_list_query_filters_nothing(blank: Any) -> None:
    gw = await _tgw(_todo_fake())
    out = await _run(gw, "tasks_list", {"query": blank, "list": "My Tasks"})
    assert out.outcome is GatewayOutcome.EXECUTED
    assert {t["id"] for t in out.result["tasks"]} == {"L1:t_plumb", "L1:t_dent"}


async def test_tasks_list_schema_names_the_query() -> None:
    gw = await _tgw(FakeTasks())
    tool = gw.registry.get("tasks_list")
    assert tool is not None and "query" in tool.input_schema["properties"]


async def test_todo_writes_vouch_by_the_same_rule() -> None:
    fake = _todo_fake()
    gw = await _tgw(fake)
    add = await _run(gw, "task_add", {"title": "Buy milk"})
    assert add.outcome is GatewayOutcome.EXECUTED and add.trusted is True
    upd = await _run(gw, "task_update", {"task_id": "L1:t_dent", "title": "Pay Dr Rao"})
    assert upd.outcome is GatewayOutcome.EXECUTED and upd.trusted is True
    done = await _run(gw, "task_complete", {"task_id": "L2:t_mail"})
    assert done.outcome is GatewayOutcome.EXECUTED and done.trusted is False  # the Gmail one


def test_query_arguments_are_bounded_in_the_calendar_and_reminder_checks() -> None:
    conn = object()
    reg = _registry(conn)  # type: ignore[arg-type]
    for name in ("calendar_list_events", "reminders_list"):
        tool = reg.get(name)
        assert tool is not None
        with pytest.raises(ValueError, match="query"):
            tool.validate({**WINDOW, "query": "x" * 201})
        with pytest.raises(ValueError, match="query"):
            tool.validate({**WINDOW, "query": 7})
        tool.validate({**WINDOW, "query": "dentist"})


def test_the_prompt_tells_the_model_to_look_up_by_words() -> None:
    from jarvis.core.prompts import LOOKUP_RULE, WIT_IDS, build_system_prompt

    for wit in WIT_IDS:
        assert LOOKUP_RULE in build_system_prompt(honorific="Sir", wit=wit)
    flat = " ".join(LOOKUP_RULE.split()).lower()
    assert (
        "to change or delete a specific item, look it up by its words (query) so only that item "
        "comes back" in flat
    )


def test_list_shapes_say_nothing_about_trust(gw: Gateway) -> None:
    """The flag lives beside the result, never inside what the model reads."""
    spec = json.dumps([t.spec().model_dump() for t in gw.registry._tools.values()])
    assert "may_vouch" not in spec and "trusted" not in spec
