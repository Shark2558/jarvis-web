# src/jarvis/helpers/house/chores.py
"""Item 2, the chores rota (docs/plans/r11-free-helpers.md D10, D3).

Pure schedule: `occurs_on` (daily, chosen weekdays, every N days from its start), `due_at` (his
time on that day, in his zone), `whose` (the turn for an occurrence: the stored turn moved once for
every occurrence that ended without "done") and `mark_done` (a new Chore: the turn moves once).

`ChoresJob` (`chores_due`, the 5-minute clock): for each configured owner whose "Chores, home
upkeep" row isn't Never, each chore that occurs today, is past its time and wasn't done today is
claimed (`house_told`, in a transaction) and then sent as `chore_due`: "Chore today: Dishes. Open
JARVIS to see whose turn it is." (the rota member only in `named`). A send no channel took
releases the claim, so the next run tries again; a claim that exists means it went already.
It goes only to him: JARVIS never messages other people.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from jarvis.helpers.house import words
from jarvis.helpers.house.guard import Counts, allowed
from jarvis.helpers.house.models import Chore, Freq
from jarvis.helpers.house.store import HouseStore
from jarvis.helpers.ports import HelperContext
from jarvis.logging import get_logger
from jarvis.notify.quiet import local

log = get_logger(__name__)

JOB = "chores_due"
LOOK_AHEAD_DAYS = 400  # the longest gap between two occurrences is 90 days


def occurs_on(c: Chore, day: date) -> bool:
    start = date.fromisoformat(c.start)
    if day < start:
        return False
    if c.freq == "weekly":
        return day.weekday() in c.days
    if c.freq == "every":
        return (day - start).days % (c.every or 1) == 0
    return True


def next_on_or_after(c: Chore, day: date) -> date | None:
    for i in range(LOOK_AHEAD_DAYS):
        d = day + timedelta(days=i)
        if occurs_on(c, d):
            return d
    return None


def last_on_or_before(c: Chore, day: date) -> date | None:
    start = date.fromisoformat(c.start)
    for i in range(LOOK_AHEAD_DAYS):
        d = day - timedelta(days=i)
        if d < start:
            return None
        if occurs_on(c, d):
            return d
    return None


def due_at(c: Chore, day: date, tz: str) -> datetime:
    hh, mm = (int(x) for x in c.at.split(":"))
    return datetime.combine(day, time(hh, mm), tzinfo=ZoneInfo(tz))


def _ended(c: Chore, day: date) -> int:
    """Occurrences after the stored turn's day, up to and including `day`: each period that
    ended without "done" moves the turn once."""
    if c.turn_day is None:
        return 0
    first = date.fromisoformat(c.turn_day)
    if day <= first:
        return 0
    count, d = 0, first + timedelta(days=1)
    while d <= day and count < LOOK_AHEAD_DAYS:
        count += int(occurs_on(c, d))
        d += timedelta(days=1)
    return count


def turn_on(c: Chore, day: date) -> int:
    return (c.turn + _ended(c, day)) % len(c.members) if c.members else 0


def whose(c: Chore, day: date) -> str | None:
    return c.members[turn_on(c, day)] if c.members else None


def mark_done(c: Chore, today: date) -> Chore:
    occurrence = last_on_or_before(c, today) or today
    turn = (turn_on(c, occurrence) + 1) % len(c.members) if c.members else 0
    nxt = next_on_or_after(c, occurrence + timedelta(days=1))
    return c.model_copy(
        update={
            "turn": turn,
            "turn_day": nxt.isoformat() if nxt else None,
            "last_done": today.isoformat(),
        }
    )


def new_chore(
    *,
    cid: str,
    label: str,
    freq: Freq,
    today: date,
    at: str = "09:00",
    days: Sequence[int] = (),
    every: int | None = None,
    members: Sequence[str] = (),
) -> Chore:
    draft = Chore(
        id=cid,
        label=label,
        freq=freq,
        days=tuple(sorted(set(days))) if freq == "weekly" else (),
        every=every if freq == "every" else None,
        start=today.isoformat(),
        at=at,
        members=tuple(members),
    )
    first = next_on_or_after(draft, today)
    return draft.model_copy(update={"turn_day": first.isoformat() if first else None})


class ChoresJob:
    name = JOB
    budget_s = 3.0

    def __init__(self, ctx: HelperContext, store: HouseStore) -> None:
        self._ctx = ctx
        self._store = store

    async def run(self, owners: Sequence[str]) -> dict[str, int]:
        """`owners` is ignored: the helpers serve the configured owners (`ctx.owners`)."""
        n = Counts()
        for uid in self._ctx.owners:
            try:
                if not await allowed(self._ctx, uid, "chore_list"):
                    n.add("skipped")
                    continue
                await self._owner(uid, n)
            except Exception as exc:  # noqa: BLE001 - one owner never blocks another
                log.warning("chores job failed for an owner", extra={"error": type(exc).__name__})
                n.add("failed")
        return n.done("sent", "retry", "skipped", "failed")

    async def _owner(self, uid: str, n: Counts) -> None:
        now = self._ctx.now()
        today = local(now, self._ctx.tz).date()
        for c in await self._store.chores(uid):
            due = due_at(c, today, self._ctx.tz)
            if not occurs_on(c, today) or now < due or c.last_done == today.isoformat():
                continue
            ident = f"{c.id}|{today.isoformat()}"
            if not await self._store.claim(uid, "chore", ident, now):
                continue
            member = whose(c, today)
            named = words.chore_named(c.label, member) if member else None
            got = await self._ctx.sender.send(
                uid, "chore_due", words.chore(c.label), due=due, named=named
            )
            if got.retry:
                await self._store.release(uid, "chore", ident)
                n.add("retry")
            else:
                n.add("sent" if got.counted else "dropped")


__all__ = [
    "JOB",
    "ChoresJob",
    "due_at",
    "last_on_or_before",
    "mark_done",
    "new_chore",
    "next_on_or_after",
    "occurs_on",
    "turn_on",
    "whose",
]
