# tests/test_calls_booking.py — R18 A1: booking calls (calls.booking): a slot accepted only inside
# the card's windows and repeated back; after the call the calendar add through the gateway's
# calendar tool, and its Undo.
from __future__ import annotations

from datetime import UTC, date, datetime, time
from typing import Any

from jarvis.calls.booking import BookingCalendar, accept_slot, event_args, windows_text
from jarvis.calls.limits import IST
from jarvis.calls.models import Booking, CallCard, CallRecord, TimeWindow
from jarvis.calls.store import MemoryCallStore
from jarvis.core.guardrails import ActionRisk, ConfirmationGate
from jarvis.tools.audit import AuditLog
from jarvis.tools.base import Tool
from jarvis.tools.gateway import Gateway
from jarvis.tools.policy import Effect, Policy, PolicyRule
from jarvis.tools.registry import ToolRegistry

UID = "u_0123456789abcdef"
NOW = datetime(2026, 11, 27, 6, 30, tzinfo=UTC)  # 12:00 IST, Friday 27 November
BOOKING = Booking(
    windows=(
        TimeWindow(day=date(2026, 11, 28), start=time(10), end=time(12)),
        TimeWindow(day=date(2026, 11, 30), start=time(16), end=time(18)),
    ),
    give_name="A. Owner",
    reason="Laundry pickup",
    duration_minutes=30,
)
CARD = CallCard(
    number_e164="+919000000001",
    contact_name="Laundry Shop",
    purpose="Book a pickup",
    booking=BOOKING,
)


def _at(day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 11, day, hour, minute, tzinfo=IST)


def test_a_slot_inside_a_window_is_accepted_and_repeated_back() -> None:
    v = accept_slot(CARD, _at(28, 10, 30), now=NOW)
    assert v.ok and v.code == "inside" and v.window == BOOKING.windows[0]
    assert v.words == "So that is Saturday 28 November at 10:30. Is that right?"


def test_a_slot_that_would_end_outside_the_window_is_declined() -> None:
    v = accept_slot(CARD, _at(28, 11, 45), now=NOW)
    assert not v.ok and v.code == "outside"
    assert "Saturday 28 November between 10:00 and 12:00" in v.words


def test_a_slot_on_another_day_or_in_the_past_is_declined() -> None:
    assert accept_slot(CARD, _at(29, 10, 30), now=NOW).code == "outside"
    assert accept_slot(CARD, _at(27, 11), now=NOW).code == "past"


def test_a_slot_without_a_zone_is_read_as_ist() -> None:
    assert accept_slot(CARD, datetime(2026, 11, 30, 16, 0), now=NOW).ok


def test_a_card_without_booking_accepts_nothing() -> None:
    plain = CARD.model_copy(update={"booking": None})
    assert accept_slot(plain, _at(28, 10), now=NOW).code == "no_booking"


def test_the_windows_read_in_plain_english() -> None:
    assert windows_text(BOOKING) == (
        "Saturday 28 November between 10:00 and 12:00; Monday 30 November between 16:00 and 18:00"
    )


def test_the_event_uses_only_the_cards_words() -> None:
    args = event_args(CARD, accept_slot(CARD, _at(28, 10), now=NOW))
    assert args["summary"] == "Laundry pickup"
    assert args["start"] == "2026-11-28T10:00:00+05:30" and args["end"].startswith(
        "2026-11-28T10:30"
    )
    assert "No payment" in args["description"] and "A. Owner" in args["description"]


class _Calendar:
    def __init__(self) -> None:
        self.events: dict[str, dict[str, Any]] = {}

    async def create(self, a: dict[str, Any]) -> dict[str, Any]:
        eid = f"ev{len(self.events) + 1}"
        self.events[eid] = a
        return {"id": eid, "summary": a["summary"], "start": a["start"], "end": a["end"]}

    async def delete(self, a: dict[str, Any]) -> dict[str, Any]:
        self.events.pop(a["event_id"])
        return {"deleted": True}


def _gateway(cal: _Calendar, rules: list[PolicyRule] | None = None) -> Gateway:
    reg = ToolRegistry()
    obj = {"type": "object"}
    reg.register(
        Tool(
            "calendar_create_event",
            "create",
            obj | {"properties": {k: {} for k in ("summary", "start", "end", "description")}},
            ActionRisk.REVERSIBLE,
            cal.create,
        )
    )
    reg.register(
        Tool(
            "calendar_delete_event",
            "delete",
            obj | {"properties": {"event_id": {}}},
            ActionRisk.REVERSIBLE,
            cal.delete,
            undoable=True,
        )
    )
    return Gateway(
        registry=reg, policy=Policy(rules or []), gate=ConfirmationGate(), audit=AuditLog()
    )


async def _store_with_record() -> tuple[MemoryCallStore, CallRecord]:
    store = MemoryCallStore()
    rec = CallRecord(number_e164=CARD.number_e164, card_id=CARD.id, started_at=NOW)
    await store.put_record(UID, rec)
    return store, rec


async def test_after_the_call_the_slot_goes_on_the_calendar_and_undo_removes_it() -> None:
    cal = _Calendar()
    store, rec = await _store_with_record()
    booking = BookingCalendar(_gateway(cal), store)
    added = await booking.add(UID, rec.id, CARD, _at(28, 10), now=NOW)
    assert added.status == "added" and added.event_id == "ev1"
    assert "Saturday 28 November at 10:00" in added.words
    stored = await store.get_record(UID, rec.id)
    assert stored is not None and stored.booking_event_ref == "ev1"
    undone = await booking.undo(UID, rec.id)
    assert undone.status == "undone" and cal.events == {}
    stored = await store.get_record(UID, rec.id)
    assert stored is not None and stored.booking_event_ref is None
    assert (await booking.undo(UID, rec.id)).status == "nothing"


async def test_a_slot_outside_the_windows_is_never_added() -> None:
    cal = _Calendar()
    store, rec = await _store_with_record()
    out = await BookingCalendar(_gateway(cal), store).add(UID, rec.id, CARD, _at(29, 10), now=NOW)
    assert out.status == "skipped" and cal.events == {}


async def test_his_ask_first_rule_makes_the_add_a_card() -> None:
    cal = _Calendar()
    store, rec = await _store_with_record()
    rule = PolicyRule(tool_pattern="calendar_create_event", effect=Effect.ASK)
    out = await BookingCalendar(_gateway(cal, [rule]), store).add(
        UID, rec.id, CARD, _at(28, 10), now=NOW
    )
    assert out.status == "awaiting" and out.approval_id and cal.events == {}


async def test_a_card_that_does_not_want_the_calendar_is_skipped() -> None:
    cal = _Calendar()
    store, rec = await _store_with_record()
    card = CARD.model_copy(
        update={"booking": BOOKING.model_copy(update={"add_to_calendar": False})}
    )
    out = await BookingCalendar(_gateway(cal), store).add(UID, rec.id, card, _at(28, 10), now=NOW)
    assert out.status == "skipped"
