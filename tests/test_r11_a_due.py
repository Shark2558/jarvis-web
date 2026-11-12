# tests/test_r11_a_due.py -- R11 Part A code review H1: a bill keeps the day of the month he asked
# for (29, 30 or 31) apart from its first due date, and each period falls on min(that day, the
# month's last day): a day-31 bill is due 28 Feb (29 in a leap year), 31 Mar, 30 Apr, 31 May ...
# even when it was added in a short month. A document written before the day was kept still reads
# (the day is the start's own).
from __future__ import annotations

from datetime import date

import pytest
from r11_fakes import UID, Clock
from r11_fakes_a import at, keyring

from jarvis.helpers.today.bills import BillsService, current_due, reminders_due
from jarvis.helpers.today.models import Bill, Due
from jarvis.helpers.today.store import BillStore
from jarvis.storage.docs import MemoryDocs


def _svc(clock: Clock) -> BillsService:
    return BillsService(BillStore(MemoryDocs(), keyring()), tz="Asia/Kolkata", now=clock)


async def _dates(clock: Clock, day: int, first: date, last: date) -> list[date]:
    svc = _svc(clock)
    bill = await svc.add(UID, label="Rent", amount="900", day=day)
    (kept,) = (await svc.book(UID)).bills  # through the sealed store and back
    assert kept.due == bill.due and kept.due.day == day
    return kept.due.dates_between(first, last)


@pytest.mark.parametrize(
    ("day", "want"),
    [
        (29, [(2, 28), (3, 29), (4, 29), (5, 29)]),
        (30, [(2, 28), (3, 30), (4, 30), (5, 30)]),
        (31, [(2, 28), (3, 31), (4, 30), (5, 31)]),
    ],
)
async def test_added_in_february_a_month_end_bill_keeps_its_day(
    day: int, want: list[tuple[int, int]]
) -> None:
    clock = Clock(at(2027, 2, 10, 12, 0))
    got = await _dates(clock, day, date(2027, 2, 1), date(2027, 5, 31))
    assert got == [date(2027, m, d) for m, d in want]


@pytest.mark.parametrize("day", [29, 30, 31])
async def test_in_a_leap_year_february_has_its_29th(day: int) -> None:
    clock = Clock(at(2028, 2, 10, 12, 0))
    got = await _dates(clock, day, date(2028, 2, 1), date(2028, 3, 31))
    assert got == [date(2028, 2, 29), date(2028, 3, day)]


async def test_added_in_a_30_day_month_a_day_31_bill_is_due_on_the_31st_after() -> None:
    clock = Clock(at(2027, 4, 10, 12, 0))
    got = await _dates(clock, 31, date(2027, 4, 1), date(2027, 7, 31))
    assert got == [date(2027, 4, 30), date(2027, 5, 31), date(2027, 6, 30), date(2027, 7, 31)]


async def test_reminders_and_the_current_due_date_follow_the_day() -> None:
    clock = Clock(at(2027, 2, 10, 12, 0))
    svc = _svc(clock)
    bill = await svc.add(UID, label="Rent", amount="900", day=31)
    assert reminders_due(bill, date(2027, 3, 28)) == [(date(2027, 3, 31), 3)]
    assert reminders_due(bill, date(2027, 3, 25)) == []  # not 3 days before the 28th
    assert current_due(bill, date(2027, 3, 1)) == date(2027, 2, 28)  # still unpaid: overdue
    bill, due = await svc.mark_paid(UID, "Rent")
    assert due == date(2027, 2, 28)
    assert current_due(bill, date(2027, 3, 1)) == date(2027, 3, 31)


def test_a_document_from_before_the_day_was_kept_still_reads() -> None:
    old = Due.model_validate({"start": "2026-01-31", "every_months": 1})
    assert old.day == 31 and old.on(date(2026, 2, 28)) and old.on(date(2026, 3, 31))
    bill = Bill.model_validate(
        {"id": "a1b2c3d4e5f6", "label": "Rent", "due": {"start": "2026-11-13", "every_months": 1}}
    )
    assert bill.due == Due(start=date(2026, 11, 13), every_months=1, day=13)


def test_a_day_that_does_not_fit_its_start_is_refused() -> None:
    with pytest.raises(ValueError):
        Due(start=date(2027, 2, 15), every_months=1, day=31)
    assert Due(start=date(2027, 2, 28), every_months=1, day=31).day == 31
