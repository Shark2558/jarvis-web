# src/jarvis/helpers/today/jobs.py
"""Part A's two jobs on the 5-minute clock (docs/plans/r11-free-helpers.md D3, D7, D8).

Both run for the configured owners (`ctx.owners`; the caller's list is ignored), are idempotent and
light: one read of each owner's `bills/{uid}` a run, Google only when a birthday reminder is due.

- `bills_due`: at his time (default 09:00), each reminder `bills.reminders_due` owes today. Every
  one is claimed in a transaction (`bills_told`) BEFORE it is sent, so it goes once across
  restarts and a second clock run in the same minute sends nothing; a send that no channel took
  (`SendResult.retry`) releases its claim for the next run. Sent only through the part's own
  sender, kind `bill_due` (held at night by the one policy), as a generic fixed text ("A bill is
  due tomorrow. Open JARVIS to see it."); his label and amount go only in `named=`, which the
  notifier uses only when "names in alerts" is on (integrated review L1: Telegram is a cloud
  chat). The console's Today tab and brief keep the full line.
- `birthdays`: when he switched birthdays on, at his time (default 08:30): today's birthdays from
  `birthdays.BirthdayReader` (his Contacts row obeyed, fail closed); each contact claimed in
  `birthdays_told` (a hash of him, the contact's resource name and the year), then ONE `birthday`
  alert for those not yet told: "A birthday today in your contacts: open JARVIS to see whose." The
  names go only in `named=`, which the notifier uses only when "names in alerts" is on.
Both sweep their old claims once a day (`DailySweep`): a sweep that fails is logged as its class
and tried again on the next run, and never stops the reminders. Logs carry class names and counts
only.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import date, datetime

from jarvis.helpers.gate import PartSender, SendResult
from jarvis.helpers.today.bills import (
    BillsService,
    plain_reminder,
    reminder_text,
    reminders_due,
)
from jarvis.helpers.today.birthdays import Birthday, BirthdayReader
from jarvis.helpers.today.store import BillsOff, Claims
from jarvis.logging import get_logger
from jarvis.notify.quiet import local
from jarvis.tools.card import one_line

log = get_logger(__name__)

BILLS_JOB = "bills_due"
BIRTHDAYS_JOB = "birthdays"
JOB_BUDGET_S = 8.0
NAME_IN_ALERT = 40
ONE_BIRTHDAY = "A birthday today in your contacts: open JARVIS to see whose."
SOME_BIRTHDAYS = "{n} birthdays today in your contacts: open JARVIS to see whose."


def _tally(counts: dict[str, int], got: SendResult) -> None:
    key = (
        "sent"
        if got.delivered
        else "held"
        if got.outcome == "held"
        else "retry"
        if got.retry
        else "other"
    )
    counts[key] = counts.get(key, 0) + 1


def _counts() -> dict[str, int]:
    return {"sent": 0, "held": 0, "retry": 0, "other": 0}


class DailySweep:
    """Old claims swept once a day per owner; a failure is logged (its class) and retried on the
    next run. Bookkeeping only: it never stops a reminder."""

    def __init__(self, what: str) -> None:
        self._what = what
        self._done: dict[str, date] = {}

    async def run(self, claims: Claims, uid: str, today: date, now: datetime) -> None:
        if self._done.get(uid) == today:
            return
        try:
            await claims.sweep(uid, now)
        except Exception as exc:  # noqa: BLE001 - bookkeeping only; the next run tries again
            why = {"job": self._what, "error": type(exc).__name__}
            log.warning("old claims not swept", extra=why)
            return
        self._done[uid] = today


class BillsDueJob:
    name = BILLS_JOB
    budget_s = JOB_BUDGET_S

    def __init__(
        self,
        service: BillsService,
        claims: Claims,
        sender: PartSender,
        *,
        owners: tuple[str, ...],
        tz: str,
        now: Callable[[], datetime],
    ) -> None:
        self._svc = service
        self._claims = claims
        self._sender = sender
        self._owners = owners
        self._tz = tz
        self._now = now
        self._sweep = DailySweep(BILLS_JOB)

    async def run(self, owners: Sequence[str]) -> dict[str, int]:
        counts = _counts()
        for uid in self._owners:
            try:
                await self._owner(uid, counts)
            except BillsOff:
                continue
            except Exception as exc:  # noqa: BLE001 - one owner never stops the others
                log.warning("bill reminders skipped", extra={"error": type(exc).__name__})
                counts["other"] += 1
        return counts

    async def _owner(self, uid: str, counts: dict[str, int]) -> None:
        book = await self._svc.book(uid)
        now = self._now()
        today = local(now, self._tz).date()
        await self._sweep.run(self._claims, uid, today, now)
        due_at = self._svc.at_local(today, book.prefs.bills_at)
        if not book.bills or now < due_at:
            return
        for bill in book.bills:
            for due, off in reminders_due(bill, today):
                key = f"{bill.id}|{due.isoformat()}|{off}"
                if not await self._claims.claim(uid, key, now):
                    continue
                named = reminder_text(bill, due, off)
                got = await self._sender.send(
                    uid, "bill_due", plain_reminder(off), due=due_at, named=named
                )
                if got.retry:
                    await self._claims.release(uid, key)
                _tally(counts, got)


def birthday_text(people: Sequence[Birthday]) -> tuple[str, str]:
    """(message, named): the message names nobody; `named` is for "names in alerts" only."""
    names = [one_line(p.name, NAME_IN_ALERT) or "a contact" for p in people]
    message = ONE_BIRTHDAY if len(names) == 1 else SOME_BIRTHDAYS.format(n=len(names))
    if len(names) == 1:
        return message, f"Today is {names[0]}'s birthday."
    if len(names) == 2:
        return message, f"Today is {names[0]}'s and {names[1]}'s birthday."
    return message, f"Birthdays today: {', '.join(names[:-1])} and {names[-1]}."


class BirthdaysJob:
    name = BIRTHDAYS_JOB
    budget_s = JOB_BUDGET_S

    def __init__(
        self,
        service: BillsService,
        reader: BirthdayReader,
        claims: Claims,
        sender: PartSender,
        *,
        owners: tuple[str, ...],
        tz: str,
        now: Callable[[], datetime],
    ) -> None:
        self._svc = service
        self._reader = reader
        self._claims = claims
        self._sender = sender
        self._owners = owners
        self._tz = tz
        self._now = now
        self._sweep = DailySweep(BIRTHDAYS_JOB)

    async def run(self, owners: Sequence[str]) -> dict[str, int]:
        counts = _counts()
        for uid in self._owners:
            try:
                await self._owner(uid, counts)
            except Exception as exc:  # noqa: BLE001 - one owner never stops the others
                log.warning("birthday reminders skipped", extra={"error": type(exc).__name__})
                counts["other"] += 1
        return counts

    async def _owner(self, uid: str, counts: dict[str, int]) -> None:
        prefs = (await self._svc.book(uid)).prefs
        now = self._now()
        today = local(now, self._tz).date()
        due_at = self._svc.at_local(today, prefs.birthday_at)
        if not prefs.birthdays_on or now < due_at:
            return
        await self._sweep.run(self._claims, uid, today, now)
        reading = await self._reader.on_day(uid, today)
        fresh = [
            p
            for p in reading.people
            if await self._claims.claim(uid, f"{p.resource}|{today.year}", now)
        ]
        if not fresh:
            return
        message, named = birthday_text(fresh)
        got = await self._sender.send(uid, "birthday", message, due=due_at, named=named)
        if got.retry:
            for p in fresh:
                await self._claims.release(uid, f"{p.resource}|{today.year}")
        _tally(counts, got)


__all__ = [
    "BILLS_JOB",
    "BIRTHDAYS_JOB",
    "ONE_BIRTHDAY",
    "BillsDueJob",
    "BirthdaysJob",
    "DailySweep",
    "birthday_text",
]
