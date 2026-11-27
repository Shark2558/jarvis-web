# src/jarvis/calls/booking.py
"""Booking calls (R18 A1; docs/plans/r18-calls.md section 4 step 9; BUILD-BRIEF.md "Booking";
Layer 5 Communication + Task & Productivity).

A booking card holds the acceptable days and times (`Booking.windows`, IST), the name (and
number) to give, the reason and "no payment" (fixed). During the call the engine (A2) asks
`accept_slot` about every slot the other person offers: JARVIS accepts only a slot that starts
and ends inside one window and is not in the past, and repeats it back (`SlotVerdict.words`);
anything else is declined with the windows it can accept (`windows_text`).

After the call, `BookingCalendar.add` puts the accepted slot on his Google Calendar through the
existing `calendar_create_event` tool and the gateway (no guests: adding an event is reversible,
so it is not an R3 step; his own "Ask first" for calendar writes still makes it a card), and
`undo` deletes it again through `calendar_delete_event` (his own event: R2, kept in Recently
deleted). The event's words are the card's own (his reason and the name to give), never the
other person's; the record keeps the event's id (`CallRecord.booking_event_ref`) for the Undo.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any, Literal

from jarvis.calls.approvals import SCOPE_SESSION, audit_step
from jarvis.calls.limits import IST
from jarvis.calls.models import Booking, CallCard, TimeWindow
from jarvis.calls.ports import CallStore
from jarvis.core.guardrails import ActionRisk
from jarvis.llm.base import ToolCall
from jarvis.logging import get_logger
from jarvis.tools.audit import AuditTrail
from jarvis.tools.card import one_line
from jarvis.tools.gateway import Gateway, GatewayOutcome, GatewayResult
from jarvis.tools.taint import context_trust

log = get_logger(__name__)

CREATE_TOOL, DELETE_TOOL = "calendar_create_event", "calendar_delete_event"
BOOKING_TOOL = "calls_booking"
SlotCode = Literal["inside", "outside", "past", "no_booking"]


def _day(at: datetime | date) -> str:
    return f"{at:%A} {at.day} {at:%B}"


def _when(at: datetime) -> str:
    return f"{_day(at)} at {at:%H:%M}"


def windows_text(booking: Booking) -> str:
    """The windows in plain English: "Friday 28 November between 10:00 and 12:00; ..."."""
    parts = [f"{_day(w.day)} between {w.start:%H:%M} and {w.end:%H:%M}" for w in booking.windows]
    return "; ".join(parts)


@dataclass(frozen=True)
class SlotVerdict:
    ok: bool
    code: SlotCode
    words: str  # English: the repeat-back line, or what can be accepted (the engine translates)
    start: datetime | None = None  # IST
    end: datetime | None = None
    window: TimeWindow | None = None


def _ist(at: datetime) -> datetime:
    return at.replace(tzinfo=IST) if at.tzinfo is None else at.astimezone(IST)


def accept_slot(
    card: CallCard, start: datetime, *, now: datetime, minutes: int | None = None
) -> SlotVerdict:
    """Is the offered slot inside the card's limits? A slot without a zone is read as IST."""
    booking = card.booking
    if booking is None:
        return SlotVerdict(False, "no_booking", "This call isn't for a booking.")
    begin = _ist(start)
    end = begin + timedelta(minutes=minutes or booking.duration_minutes)
    if begin < _ist(now):
        return SlotVerdict(False, "past", "That time has already passed.")
    for w in booking.windows:
        opens = datetime.combine(w.day, w.start, tzinfo=IST)
        closes = datetime.combine(w.day, w.end, tzinfo=IST)
        if opens <= begin and end <= closes:
            words = f"So that is {_when(begin)}. Is that right?"
            return SlotVerdict(True, "inside", words, begin, end, w)
    words = f"I can only accept {windows_text(booking)}."
    return SlotVerdict(False, "outside", words)


@dataclass(frozen=True)
class CalendarOutcome:
    status: Literal["added", "undone", "awaiting", "failed", "skipped", "nothing"]
    words: str
    event_id: str | None = None
    approval_id: str | None = None


MSG_ADDED = "Added to your calendar: {when}. You can undo it from the call's summary."
MSG_AWAITING = "The calendar entry is waiting for your approval."
MSG_FAILED = "JARVIS couldn't add it to your calendar; add it yourself: {when}."
MSG_UNDONE = "Removed from your calendar (it is in Recently deleted for 30 days)."
MSG_UNDO_FAILED = "JARVIS couldn't remove the calendar entry; remove it yourself."
MSG_NOTHING = "This call added nothing to your calendar."


def event_args(card: CallCard, verdict: SlotVerdict) -> dict[str, Any]:
    """The calendar event: the card's own words only (his reason, the name to give)."""
    assert card.booking is not None and verdict.start is not None and verdict.end is not None
    b = card.booking
    lines = [
        "Booked by JARVIS on a phone call.",
        f"Name given: {one_line(b.give_name, 60)}.",
        "No payment was agreed.",
    ]
    if card.contact_name:
        lines.insert(1, f"With: {one_line(card.contact_name, 60)}.")
    return {
        "summary": one_line(b.reason, 120),
        "start": verdict.start.isoformat(),
        "end": verdict.end.isoformat(),
        "description": " ".join(lines),
    }


class BookingCalendar:
    def __init__(self, gateway: Gateway, store: CallStore, *, audit: AuditTrail | None = None):
        self.gateway, self.store, self.audit = gateway, store, audit

    async def _execute(self, uid: str, name: str, args: dict[str, Any]) -> GatewayResult:
        call = ToolCall(id=f"cb-{uuid.uuid4().hex[:8]}", name=name, arguments=args)
        with context_trust(untrusted=False):  # his own card's words, at his own call's end
            return await self.gateway.execute(call, scope=f"{uid}:{SCOPE_SESSION}")

    async def add(
        self,
        uid: str,
        call_id: str,
        card: CallCard,
        start: datetime,
        *,
        now: datetime | None = None,
    ) -> CalendarOutcome:
        """After the call: the accepted slot on his calendar (checked against the card again)."""
        if card.booking is None or not card.booking.add_to_calendar:
            return CalendarOutcome("skipped", MSG_NOTHING)
        verdict = accept_slot(card, start, now=now or datetime.now(UTC))
        if not verdict.ok or verdict.start is None:
            return CalendarOutcome("skipped", verdict.words)
        when = _when(verdict.start)
        try:
            done = await self._execute(uid, CREATE_TOOL, event_args(card, verdict))
        except Exception as exc:  # noqa: BLE001 - the call is over; tell him plainly
            log.error("booking calendar add failed", extra={"error": type(exc).__name__})
            return CalendarOutcome("failed", MSG_FAILED.format(when=when))
        if done.outcome is GatewayOutcome.AWAITING_CONFIRMATION and done.pending is not None:
            return CalendarOutcome("awaiting", MSG_AWAITING, approval_id=done.pending.id)
        event_id = done.result.get("id") if isinstance(done.result, dict) else None
        if done.outcome is not GatewayOutcome.EXECUTED or not isinstance(event_id, str):
            return CalendarOutcome("failed", MSG_FAILED.format(when=when))
        await self._remember(uid, call_id, event_id)
        await audit_step(
            self.audit, BOOKING_TOOL, "added", {"call": call_id}, when, ActionRisk.REVERSIBLE
        )
        return CalendarOutcome("added", MSG_ADDED.format(when=when), event_id=event_id)

    async def _remember(self, uid: str, call_id: str, event_id: str | None) -> None:
        rec = await self.store.get_record(uid, call_id)
        if rec is not None:
            await self.store.put_record(uid, rec.model_copy(update={"booking_event_ref": event_id}))

    async def undo(self, uid: str, call_id: str) -> CalendarOutcome:
        """His Undo on the call's summary: the event JARVIS added is deleted again."""
        rec = await self.store.get_record(uid, call_id)
        if rec is None or not rec.booking_event_ref:
            return CalendarOutcome("nothing", MSG_NOTHING)
        try:
            done = await self._execute(uid, DELETE_TOOL, {"event_id": rec.booking_event_ref})
        except Exception as exc:  # noqa: BLE001
            log.error("booking undo failed", extra={"error": type(exc).__name__})
            return CalendarOutcome("failed", MSG_UNDO_FAILED)
        if done.outcome is GatewayOutcome.AWAITING_CONFIRMATION and done.pending is not None:
            return CalendarOutcome("awaiting", MSG_AWAITING, approval_id=done.pending.id)
        if done.outcome is not GatewayOutcome.EXECUTED:
            return CalendarOutcome("failed", MSG_UNDO_FAILED)
        await self._remember(uid, call_id, None)
        await audit_step(
            self.audit, BOOKING_TOOL, "undone", {"call": call_id}, "", ActionRisk.REVERSIBLE
        )
        return CalendarOutcome("undone", MSG_UNDONE)


__all__ = [
    "BookingCalendar",
    "CalendarOutcome",
    "SlotVerdict",
    "accept_slot",
    "event_args",
    "windows_text",
]
