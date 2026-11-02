# tests/test_review_followups.py — slice 11 final review (s11-int @ cfd8834), written before the
# fixes: Reminders "Never" is total over the calendar tools (MEDIUM 2), a round's note counts a
# tool that raised (LOW 5), and a duplicate card keeps the stricter reason (LOW 6).
# (The to-do token, vouching and restore-claim findings are tested beside their neighbours in
# test_trust_outside.py and test_undo_bin.py.)
from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
from google_fakes import GOOGLE_UID, FakeGoogle

from jarvis.core.guardrails import (
    ActionRisk,
    AskReason,
    ConfirmationGate,
    ConfirmationRequired,
    PendingAction,
)
from jarvis.core.models import Session
from jarvis.core.rounds import Rounds
from jarvis.integrations.google import GoogleConnector
from jarvis.llm.base import ToolCall
from jarvis.permissions.groups import GROUPS
from jarvis.tools.audit import AuditLog
from jarvis.tools.base import Tool
from jarvis.tools.gateway import Gateway, GatewayOutcome, GatewayResult
from jarvis.tools.google_calendar import calendar_tools
from jarvis.tools.policy import Effect, Policy, PolicyRule
from jarvis.tools.registry import ToolRegistry
from jarvis.tools.reminders import reminder_tools

CAL = "https://www.googleapis.com/calendar/v3"
EVENTS = f"{CAL}/calendars/primary/events"
TZ_URL = f"{CAL}/users/me/calendarList/primary"
SCOPE = f"{GOOGLE_UID}:sess_1"
ME = {"email": "akash@example.com", "self": True}
TAG = {"private": {"jarvis": "reminder"}}


def _rules(effect: Effect, *group_ids: str) -> list[PolicyRule]:
    return [r for g in GROUPS if g.id in group_ids for r in g.rules(effect)]


def _event(eid: str, **over: Any) -> dict[str, Any]:
    e: dict[str, Any] = {
        "id": eid,
        "summary": "Dentist",
        "eventType": "default",
        "start": {"dateTime": "2027-01-15T16:00:00+05:30", "timeZone": "Asia/Kolkata"},
        "end": {"dateTime": "2027-01-15T16:30:00+05:30", "timeZone": "Asia/Kolkata"},
        "organizer": dict(ME),
        "creator": dict(ME),
    }
    e.update(over)
    return e


def _gw(conn: GoogleConnector, fake: FakeGoogle, rules: list[PolicyRule]) -> Gateway:
    fake.on("GET", TZ_URL, httpx.Response(200, json={"timeZone": "Asia/Kolkata"}))
    reg = ToolRegistry()
    for t in calendar_tools(conn) + reminder_tools(conn):
        reg.register(t)
    return Gateway(registry=reg, policy=Policy(rules), gate=ConfirmationGate(), audit=AuditLog())


def _plant(fake: FakeGoogle, eid: str, **over: Any) -> None:
    fake.on("GET", f"{EVENTS}/{eid}", httpx.Response(200, json=_event(eid, **over)))
    fake.on("PATCH", f"{EVENTS}/{eid}", httpx.Response(200, json=_event(eid, **over)))
    fake.on("DELETE", f"{EVENTS}/{eid}", httpx.Response(204))


UPDATE = {"location": "Smile Clinic"}


async def _call(gw: Gateway, name: str, eid: str, **args: Any) -> GatewayResult:
    call = ToolCall(id="c", name=name, arguments={"event_id": eid, **args})
    return await gw.execute(call, scope=SCOPE)


# ---- MEDIUM 2: Reminders "Never" is total ----


async def test_reminders_never_stops_the_calendar_tools_changing_a_tagged_reminder(
    connected: GoogleConnector, fake_google: FakeGoogle
) -> None:
    gw = _gw(connected, fake_google, _rules(Effect.DENY, "reminders"))
    _plant(fake_google, "remravi01", summary="⏰ call Ravi", extendedProperties=TAG)
    upd = await _call(gw, "calendar_update_event", "remravi01", **UPDATE)
    assert upd.outcome is GatewayOutcome.DENIED
    assert "switched off" in (upd.error or "") and "Reminders" in (upd.error or "")
    assert fake_google.sent("PATCH", "/events/remravi01") == []
    gone = await _call(gw, "calendar_delete_event", "remravi01")
    assert gone.outcome is GatewayOutcome.DENIED and "Reminders" in (gone.error or "")
    assert fake_google.sent("DELETE", "/events/remravi01") == []


async def test_reminders_never_leaves_plain_calendar_events_alone(
    connected: GoogleConnector, fake_google: FakeGoogle
) -> None:
    gw = _gw(connected, fake_google, _rules(Effect.DENY, "reminders"))
    _plant(fake_google, "evdentist1")
    out = await _call(gw, "calendar_update_event", "evdentist1", **UPDATE)
    assert out.outcome is GatewayOutcome.EXECUTED
    assert len(fake_google.sent("PATCH", "/events/evdentist1")) == 1


async def test_reminders_never_does_not_let_a_calendar_event_be_made_a_reminder(
    connected: GoogleConnector, fake_google: FakeGoogle
) -> None:
    """The create tool has no way to set the reminder tag: an argument that tries is dropped."""
    gw = _gw(connected, fake_google, _rules(Effect.DENY, "reminders"))
    fake_google.on("POST", EVENTS, httpx.Response(200, json=_event("evnew00001")))
    args = {
        "summary": "⏰ call Ravi",
        "start": "2027-01-15T16:00:00",
        "end": "2027-01-15T16:30:00",
        "extendedProperties": TAG,
    }
    await gw.execute(ToolCall(id="c", name="calendar_create_event", arguments=args), scope=SCOPE)
    sent = [json.loads(r.content) for r in fake_google.sent("POST", "/calendars/primary/events")]
    assert all("extendedProperties" not in body for body in sent)


async def test_calendar_never_still_blocks_every_calendar_tool_even_for_a_reminder(
    connected: GoogleConnector, fake_google: FakeGoogle
) -> None:
    gw = _gw(
        connected,
        fake_google,
        _rules(Effect.DENY, "calendar_change", "calendar_remove", "calendar_delete"),
    )
    _plant(fake_google, "remravi01", summary="⏰ call Ravi", extendedProperties=TAG)
    _plant(fake_google, "evdentist1")
    for eid in ("remravi01", "evdentist1"):
        assert (
            await _call(gw, "calendar_update_event", eid, **UPDATE)
        ).outcome is GatewayOutcome.DENIED
        assert (await _call(gw, "calendar_delete_event", eid)).outcome is GatewayOutcome.DENIED
    assert fake_google.sent("PATCH", "/events/remravi01") == []


async def test_the_reminders_row_says_it_covers_the_calendar_tools_too() -> None:
    row = next(g for g in GROUPS if g.id == "reminders")
    assert "Calendar tools" in row.hint and "reminder" in row.hint
    assert "Reminders" in row.refusal() and "Never" in row.refusal()


# ---- LOW 5: a tool that raised may have written ----


def _writer() -> Tool:
    return Tool(
        "note_add",
        "Add a note.",
        {"type": "object", "properties": {}},
        ActionRisk.REVERSIBLE,
        lambda a: {},
        summary_template="Add a note",
    )


def _rounds() -> tuple[Rounds, ToolRegistry]:
    reg = ToolRegistry()
    reg.register(_writer())
    return Rounds(session=Session(user_id="u_owner")), reg


def test_a_tool_that_raised_counts_as_a_write_with_honest_wording() -> None:
    rounds, reg = _rounds()
    call = ToolCall(id="c", name="note_add", arguments={})
    raised = GatewayResult(GatewayOutcome.ERROR, error="the tool failed", raised=True)
    rounds.note(reg, [call], [raised])
    assert rounds.wrote is True  # the loop stops and records if the store is down
    assert rounds.done == ["Add a note (may not have been done)"]


def test_an_error_before_the_tool_ran_is_not_a_write() -> None:
    rounds, reg = _rounds()
    call = ToolCall(id="c", name="note_add", arguments={})
    for refused in (
        GatewayResult(GatewayOutcome.ERROR, error="could not look it up first"),
        GatewayResult(GatewayOutcome.DENIED, error="blocked"),
    ):
        rounds.note(reg, [call], [refused])
    assert rounds.wrote is False and rounds.done == []


def test_an_executed_write_is_noted_as_before() -> None:
    rounds, reg = _rounds()
    call = ToolCall(id="c", name="note_add", arguments={})
    rounds.note(reg, [call], [GatewayResult(GatewayOutcome.EXECUTED, result={"ok": True})])
    assert rounds.done == ["Add a note"]


def test_a_raised_read_only_tool_is_not_a_write() -> None:
    rounds, _ = _rounds()
    reg = ToolRegistry()
    reg.register(
        Tool(
            "note_list",
            "List.",
            {"type": "object", "properties": {}},
            ActionRisk.READ_ONLY,
            lambda a: {},
        )  # fmt: skip
    )
    call = ToolCall(id="c", name="note_list", arguments={})
    rounds.note(reg, [call], [GatewayResult(GatewayOutcome.ERROR, error="x", raised=True)])
    assert rounds.done == []


# ---- LOW 6: a duplicate card keeps the stricter reason ----


def _card(reason: AskReason | None) -> PendingAction:
    return PendingAction(
        tool="gmail_send",
        arguments={"to": "a@b.com"},
        risk=ActionRisk.IRREVERSIBLE,
        summary="Send a message to a@b.com",
        scope="u1:s1",
        reason=reason,
    )


@pytest.mark.parametrize(
    ("stored", "fresh", "kept"),
    [
        (AskReason.SPOKEN, AskReason.RISK, AskReason.RISK),  # the stricter one wins
        (AskReason.SPOKEN, AskReason.DRAFT_RECIPIENT, AskReason.DRAFT_RECIPIENT),
        (AskReason.RISK, AskReason.SPOKEN, AskReason.RISK),  # never relaxed
        (AskReason.DRAFT_RECIPIENT, AskReason.OWNER_RULE, AskReason.DRAFT_RECIPIENT),
        (None, AskReason.SPOKEN, AskReason.SPOKEN),  # a card from before the field
    ],
)
async def test_a_duplicate_proposal_merges_the_reason_like_a_re_proposal_does(
    stored: AskReason | None, fresh: AskReason, kept: AskReason
) -> None:
    gate = ConfirmationGate()
    await gate.store.put(_card(stored))
    with pytest.raises(ConfirmationRequired) as exc:
        await gate.check(_card(fresh))
    assert exc.value.action.reason is kept
    again = (await gate.pending())[0]
    assert again.reason is kept  # and it is what is stored, so what Approve all sees
