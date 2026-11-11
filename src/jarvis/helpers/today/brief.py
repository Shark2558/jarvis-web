# src/jarvis/helpers/today/brief.py
"""Part A's lines for the brief's "Helpers" section (docs/plans/r11-free-helpers.md D7-D9): at most
three fixed-template lines, never a model's words and never input to the AI summary.

1. Bills due today, tomorrow or overdue: "Bills: Electricity ₹1,240 due tomorrow; Water ₹300 due
   today" (two at most, then "and N more").
2. Birthdays today, when he switched them on: "Birthdays today: Asha, Ravi" (the brief is his own
   console, so it names them; the alerts don't unless "names in alerts" is on).
3. His top priority when it isn't a bill already said: "Top priority: Water the plants".
A part that can't answer in time is left out by the brief itself (`HelpersBrief`).
"""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from datetime import date, datetime, time, tzinfo

from jarvis.helpers.ports import PendingItem
from jarvis.helpers.today.bills import BillsService, amount_words, current_due, when_words
from jarvis.helpers.today.birthdays import BirthdayReader
from jarvis.helpers.today.pending import PendingService
from jarvis.helpers.today.store import BillsOff
from jarvis.tools.card import one_line

NAME = "today"
SHOWN = 2
NAMES_SHOWN = 3
BIRTHDAY_TIMEOUT_S = 2.5
SOON = 1  # tomorrow


def _more(shown: list[str], total: int, sep: str) -> str:
    extra = total - len(shown)
    return sep.join(shown) + (f" and {extra} more" if extra > 0 else "")


class TodayBrief:
    name = NAME

    def __init__(
        self, bills: BillsService, birthdays: BirthdayReader, pending: PendingService
    ) -> None:
        self._bills = bills
        self._birthdays = birthdays
        self._pending = pending

    async def _bill_line(self, uid: str, day: date) -> str | None:
        try:
            book = await self._bills.book(uid)
        except BillsOff:
            return None
        due = [
            (d, b)
            for b in book.bills
            if (d := current_due(b, day)) is not None and (d - day).days <= SOON
        ]
        if not due:
            return None
        due.sort(key=lambda row: row[0])
        parts = [f"{b.label} {amount_words(b)} {when_words(d, day)}" for d, b in due[:SHOWN]]
        return "Bills: " + _more(parts, len(due), "; ")

    async def _birthday_line(self, uid: str, day: date) -> str | None:
        prefs = (await self._bills.book(uid)).prefs
        if not prefs.birthdays_on:
            return None
        try:  # inside the brief's own budget for this part
            reading = await asyncio.wait_for(self._birthdays.on_day(uid, day), BIRTHDAY_TIMEOUT_S)
        except TimeoutError:
            return None
        names = [one_line(p.name, 40) for p in reading.people]
        if not names:
            return None
        return "Birthdays today: " + _more(names[:NAMES_SHOWN], len(names), ", ")

    async def _top_line(self, uid: str, day: date, tz: tzinfo) -> str | None:
        now = datetime.combine(day, time(12, 0), tzinfo=tz)
        top: PendingItem | None
        top, _ = await self._pending.top(uid, now)
        if top is None or top.source == NAME:
            return None
        return f"Top priority: {top.label}"

    async def lines(self, uid: str, tz: tzinfo, day: date) -> Sequence[str]:
        out = [
            await self._bill_line(uid, day),
            await self._birthday_line(uid, day),
            await self._top_line(uid, day, tz),
        ]
        return [x for x in out if x][:3]


__all__ = ["NAME", "TodayBrief"]
