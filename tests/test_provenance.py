# tests/test_provenance.py — slice 11 D8: which calendar events and to-dos are the owner's own.
# Pure rules, no I/O. Written before the implementation.
from __future__ import annotations

from typing import Any

import pytest

from jarvis.tools.provenance import (
    OWN_EVENT_TYPES,
    OwnerItems,
    all_owner_authored,
    is_owner_authored_event,
    is_owner_authored_task,
    unwrap,
    vouch,
)

ME = {"email": "akash@example.com", "self": True}
PRIYA = {"email": "priya@example.com"}


def _own_event(**over: Any) -> dict[str, Any]:
    e: dict[str, Any] = {
        "id": "ev1",
        "summary": "Dentist",
        "eventType": "default",
        "organizer": dict(ME),
        "creator": dict(ME),
        "start": {"dateTime": "2027-01-15T15:00:00+05:30"},
    }
    e.update(over)
    return e


# ---- events -----------------------------------------------------------------------------------


def test_an_event_the_owner_made_alone_is_his_own() -> None:
    assert is_owner_authored_event(_own_event())


def test_the_owner_listed_as_the_only_attendee_is_still_his_own() -> None:
    assert is_owner_authored_event(_own_event(attendees=[dict(ME)]))


def test_a_jarvis_reminder_meeting_the_rule_is_his_own() -> None:
    tagged = _own_event(extendedProperties={"private": {"jarvis": "reminder"}})
    assert is_owner_authored_event(tagged)


@pytest.mark.parametrize("missing", ["organizer", "creator"])
def test_without_organizer_and_creator_self_it_is_not(missing: str) -> None:
    e = _own_event()
    e.pop(missing)
    assert not is_owner_authored_event(e)


@pytest.mark.parametrize(
    "over",
    [
        {"organizer": PRIYA},  # an invite: someone else organises it
        {"creator": PRIYA},  # a delegate made it on the owner's calendar
        {"organizer": {"email": "akash@example.com", "self": False}},
        {"creator": {"email": "akash@example.com", "self": "true"}},  # not the JSON true
        {"organizer": "akash@example.com"},  # malformed
        {"attendees": [dict(ME), PRIYA]},  # someone else is on it
        {"attendees": [PRIYA]},
        {"attendees": ["priya@example.com"]},  # malformed entry
        {"attendees": "priya@example.com"},  # malformed list
        {"attendeesOmitted": True},  # Google may have left guests out
        {"eventType": "fromGmail"},  # Gmail put it there from a mail
        {"eventType": "birthday"},  # a contact's birthday: their name, their profile
        {"eventType": "somethingNew"},  # unknown types fail closed
        {"eventType": None},
    ],
)
def test_anything_another_person_or_app_may_have_written_is_not_his_own(
    over: dict[str, Any],
) -> None:
    assert not is_owner_authored_event(_own_event(**over))


@pytest.mark.parametrize("kind", sorted(OWN_EVENT_TYPES))
def test_the_owners_own_event_types(kind: str) -> None:
    assert is_owner_authored_event(_own_event(eventType=kind))


def test_an_event_without_an_event_type_is_a_default_one() -> None:
    e = _own_event()
    e.pop("eventType")
    assert is_owner_authored_event(e)


def test_only_these_event_types_count() -> None:
    assert frozenset({"default", "focusTime", "outOfOffice", "workingLocation"}) == OWN_EVENT_TYPES


@pytest.mark.parametrize("value", [None, [], "ev1", 3])
def test_not_an_event_at_all_is_not_his_own(value: Any) -> None:
    assert not is_owner_authored_event(value)


# ---- to-dos -----------------------------------------------------------------------------------


def test_a_plain_todo_is_his_own() -> None:
    assert is_owner_authored_task({"id": "t1", "title": "Call plumber", "notes": "sink"})
    assert is_owner_authored_task({"id": "t1", "title": "x", "links": []})


@pytest.mark.parametrize(
    "extra",
    [
        {"links": [{"type": "email", "link": "https://mail.google.com/mail/#all/1"}]},
        {"links": [{"type": "chat_message"}]},
        {"links": [{"type": "keep_note"}]},
        {"links": "x"},  # malformed, but present
        {"assignmentInfo": {"surfaceType": "DOCUMENT"}},
        {"assignmentInfo": {"surfaceType": "SPACE"}},
    ],
)
def test_a_todo_from_gmail_chat_keep_docs_or_a_space_is_not(extra: dict[str, Any]) -> None:
    assert not is_owner_authored_task({"id": "t1", "title": "x", **extra})


@pytest.mark.parametrize("value", [None, [], "t1"])
def test_not_a_todo_at_all_is_not_his_own(value: Any) -> None:
    assert not is_owner_authored_task(value)


# ---- results ----------------------------------------------------------------------------------


def test_a_result_is_his_own_only_when_every_item_is() -> None:
    own, invite = _own_event(), _own_event(organizer=PRIYA)
    assert all_owner_authored([own, own], is_owner_authored_event)
    assert not all_owner_authored([own, invite], is_owner_authored_event)
    assert all_owner_authored([], is_owner_authored_event)  # nothing in it: nobody's words


def test_vouch_wraps_only_an_owner_authored_result_and_unwrap_reads_it_back() -> None:
    body = {"events": []}
    assert vouch(body, False) is body
    wrapped = vouch(body, True)
    assert isinstance(wrapped, OwnerItems) and wrapped.value is body
    assert unwrap(wrapped) == (body, True)
    assert unwrap(body) == (body, False)
