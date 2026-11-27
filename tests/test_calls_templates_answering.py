# tests/test_calls_templates_answering.py — R18 A1: the laundry and appointment templates
# (calls.templates; rows 195-197, each call after his tap) and the answering policy for the calls
# he misses (calls.answering; row 104, off by default).
from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any

import pytest

from jarvis.calls.answering import (
    AnsweringPolicy,
    GoogleContactBook,
    decide,
    message_card,
)
from jarvis.calls.models import AnswerPolicy, CallSettings, Direction
from jarvis.calls.protocol import CallStateEvent
from jarvis.calls.store import MemoryCallStore
from jarvis.calls.templates import (
    APPOINTMENT,
    LAUNDRY_PICKUP,
    LAUNDRY_STATUS,
    TemplateRefused,
    catalogue,
    draft_from,
    is_template,
)

UID = "u_0123456789abcdef"
NUMBER = "+919000000001"
AT = datetime(2026, 11, 27, 6, 30, tzinfo=UTC)
WINDOW = {"day": "2026-11-28", "start": "10:00", "end": "12:00"}


def test_the_laundry_pickup_template_writes_a_booking_draft_in_malayalam_first() -> None:
    draft = draft_from(
        LAUNDRY_PICKUP, {"number": NUMBER, "windows": [WINDOW], "give_name": "Sam", "items": 6}
    )
    assert draft.template == LAUNDRY_PICKUP and draft.languages == ("ml-IN", "en-IN")
    assert draft.purpose == "Book a laundry pickup of 6 items"
    assert draft.booking is not None and draft.booking.windows[0].day == date(2026, 11, 28)
    assert draft.booking.no_payment and draft.may_agree == (
        "A pickup time inside the given windows.",
    )


def test_the_laundry_status_template_agrees_to_nothing_without_windows() -> None:
    draft = draft_from(
        LAUNDRY_STATUS, {"contact": "Laundry", "give_name": "Sam", "order": "6 shirts"}
    )
    assert draft.may_agree == () and draft.booking is None
    assert any("6 shirts" in line for line in draft.may_say)
    with_delivery = draft_from(
        LAUNDRY_STATUS, {"contact": "Laundry", "give_name": "Sam", "windows": [WINDOW]}
    )
    assert with_delivery.booking is not None and with_delivery.booking.reason == "Laundry delivery"


def test_the_appointment_template() -> None:
    draft = draft_from(
        APPOINTMENT,
        {
            "number": NUMBER,
            "place": "the clinic",
            "reason": "a check-up",
            "windows": [WINDOW],
            "give_name": "Sam",
            "give_number": "+919000000002",
            "languages": ["en-IN", "hi-IN"],
        },
    )
    assert draft.purpose == "Book an appointment at the clinic: a check-up"
    assert draft.booking is not None and draft.booking.give_number == "+919000000002"
    assert draft.languages == ("en-IN", "hi-IN")


@pytest.mark.parametrize(
    ("name", "fields"),
    [
        ("pizza", {"number": NUMBER}),
        (LAUNDRY_PICKUP, {"windows": [WINDOW], "give_name": "Sam"}),  # nobody to call
        (LAUNDRY_PICKUP, {"number": NUMBER, "give_name": "Sam"}),  # no windows
        (
            APPOINTMENT,
            {
                "number": NUMBER,
                "place": "x",
                "reason": "y",
                "windows": [WINDOW],
                "give_name": "S",
                "pay": 1,
            },
        ),
    ],
)
def test_bad_template_fields_are_refused(name: str, fields: dict[str, Any]) -> None:
    with pytest.raises(TemplateRefused):
        draft_from(name, fields)


def test_the_catalogue_lists_the_three_templates() -> None:
    names = [t["name"] for t in catalogue()]
    assert names == [LAUNDRY_PICKUP, LAUNDRY_STATUS, APPOINTMENT]
    assert all(is_template(n) for n in names) and not is_template("pizza")


# ---- answering ----------------------------------------------------------------------------------
ON = CallSettings(answering_on=True, owner_first_name="Sam")


def test_answering_is_off_by_default() -> None:
    assert CallSettings().answering_on is False
    assert decide(CallSettings(), rings=9, saved=True).code == "off"


def test_after_the_rings_and_by_the_caller_policy() -> None:
    assert decide(ON, rings=4, saved=None).code == "wait"
    assert decide(ON, rings=5, saved=None).answer
    contacts = ON.model_copy(update={"answer_policy": AnswerPolicy.CONTACTS})
    assert decide(contacts, rings=5, saved=True).answer
    assert decide(contacts, rings=5, saved=False).code == "not_contact"
    assert decide(contacts, rings=5, saved=None).code == "contacts_down"
    others = ON.model_copy(update={"answer_policy": AnswerPolicy.NOT_CONTACTS})
    assert decide(others, rings=5, saved=False).answer
    assert decide(others, rings=5, saved=True).code == "contact"
    assert decide(others, rings=5, saved=None).code == "contacts_down"
    assert decide(ON.model_copy(update={"owner_first_name": ""}), rings=5, saved=None).code == (
        "no_name"
    )


def _ringing(
    rings: int = 6, number: str | None = NUMBER, call_id: str | None = None
) -> CallStateEvent:
    return CallStateEvent(state="ringing", rings=rings, number_e164=number, call_id=call_id, at=AT)


class _Book:
    def __init__(self, saved: bool | None) -> None:
        self.saved = saved
        self.asked = 0

    async def is_saved(self, uid: str, e164: str) -> bool:
        self.asked += 1
        if self.saved is None:
            raise RuntimeError("contacts down")
        return self.saved


async def _policy(saved: bool | None, **settings: Any) -> tuple[AnsweringPolicy, _Book]:
    store = MemoryCallStore()
    await store.save_settings(UID, {"answering_on": True, "owner_first_name": "Sam"} | settings)
    book = _Book(saved)
    return AnsweringPolicy(store, book, clock=lambda: AT), book


async def test_the_policy_reads_his_settings_and_contacts() -> None:
    policy, book = await _policy(True, answer_policy="contacts")
    assert (await policy.should_answer(UID, _ringing())).answer and book.asked == 1
    policy, _ = await _policy(None, answer_policy="contacts")
    assert (await policy.should_answer(UID, _ringing())).code == "contacts_down"
    policy, book = await _policy(None)  # everyone: no look-up
    assert (await policy.should_answer(UID, _ringing())).answer and book.asked == 0


async def test_withheld_numbers_and_our_own_calls_are_left_alone() -> None:
    policy, _ = await _policy(True)
    assert (await policy.should_answer(UID, _ringing(number=None))).code == "withheld"
    placed = _ringing(call_id="call_00000000000a")
    assert (await policy.should_answer(UID, placed)).code == "not_ringing"
    active = CallStateEvent(state="active", number_e164=NUMBER, at=AT)
    assert (await policy.should_answer(UID, active)).code == "not_ringing"


async def test_the_month_cap_stops_answering() -> None:
    policy, _ = await _policy(True, month_cap_inr=5)
    await policy.store.add_spend(UID, "2026-11", 5.0)
    assert (await policy.should_answer(UID, _ringing())).code == "month_cap"


async def test_too_few_rings_waits() -> None:
    policy, _ = await _policy(True, answer_after_rings=8)
    assert (await policy.should_answer(UID, _ringing(rings=7))).code == "wait"


def test_the_message_card_never_agrees_to_anything() -> None:
    card = message_card(ON, NUMBER)
    assert card.direction is Direction.INCOMING and card.may_agree == ()
    assert "Take a message for Sam" in card.purpose and card.limits.max_minutes == 3


class _C:
    def __init__(self, phones: tuple[str, ...]) -> None:
        self.phones = phones


class _Found:
    def __init__(self, contacts: list[_C]) -> None:
        self.contacts = contacts


class _Client:
    def __init__(self, contacts: list[_C]) -> None:
        self.contacts = contacts
        self.queries: list[str] = []

    async def require(self, uid: str) -> None:
        return None

    async def search(self, uid: str, name: str) -> _Found:
        self.queries.append(name)
        return _Found(self.contacts)


async def test_a_saved_contact_matches_only_on_the_exact_number() -> None:
    client = _Client([_C(("+919000000002",)), _C((NUMBER,))])
    assert await GoogleContactBook(client).is_saved(UID, NUMBER)
    assert client.queries == ["9000000001"]
    assert not await GoogleContactBook(_Client([_C(("+919000000002",))])).is_saved(UID, NUMBER)
