# src/jarvis/series/replan.py
"""The re-plan after a skipped session (R11.1 O2b; docs/plans/r11-1-observations.md D6). Pure:
no I/O, no model.

- `rhythm`: the plan's own weekly slots: the weekdays, start times and lengths its sessions use.
- `tail`: what moves: the skipped session, then every later session that has not started yet and
  is not done. A session that already started is never moved by another one's skip (he may
  still answer for it).
- `build`: each of those takes the next free slot of the rhythm, in order: after now, not on
  another calendar entry (`busy`), not on a session of the plan that stays. So every later
  session moves on and the plan ends later. A session keeps its own length.
- `verify`: THE check that none is lost: the moves are exactly the sessions that must move, every
  session still has its own time (none shares a start, none overlaps another moved one), none
  is put in the past, and their order is kept. A re-plan that fails it is refused; `series.tools`
  runs it again just before anything moves.
- `applied`: the plan after the moves: the same sessions, the same count.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from datetime import datetime, time, timedelta, tzinfo

from jarvis.series.models import OPEN_STATES, Move, Plan, PlanSession, ReplanRefused

MAX_DAYS = 370  # how far ahead a re-plan may reach
Span = tuple[datetime, datetime]


@dataclass(frozen=True)
class Slot:
    weekday: int  # Monday = 0
    at: time
    minutes: int


def rhythm(plan: Plan, tz: tzinfo) -> list[Slot]:
    """The distinct (weekday, start time) pairs of the plan's sessions, in week order; a slot's
    length is the longest session that used it."""
    longest: dict[tuple[int, time], int] = {}
    for s in plan.sessions:
        local = s.start.astimezone(tz)
        key = (local.weekday(), local.time().replace(second=0, microsecond=0))
        minutes = int((s.end - s.start).total_seconds() // 60)
        longest[key] = max(longest.get(key, 0), minutes)
    return [Slot(day, at, minutes) for (day, at), minutes in sorted(longest.items())]


def tail(plan: Plan, n: int, now: datetime) -> list[PlanSession]:
    """The sessions a skip of session `n` moves, in plan order."""
    skipped = plan.session(n)
    if skipped is None:
        raise ReplanRefused(f"There is no session {n} in that plan, Sir.")
    if skipped.state == "done":
        raise ReplanRefused(f"Session {n} is already done, Sir, so there is nothing to move.")
    later = [
        s
        for s in plan.sessions
        if s.n != n and s.state in OPEN_STATES and s.start > now and s.start > skipped.start
    ]
    return [skipped, *sorted(later, key=lambda s: (s.start, s.n))]


def _slots(
    slots: Sequence[Slot], after: datetime, tz: tzinfo, until: datetime
) -> Iterator[datetime]:
    """Every start of the rhythm strictly after `after`, in time order, up to `until`."""
    day = after.astimezone(tz).date()
    last = min(until, after + timedelta(days=MAX_DAYS))
    while datetime.combine(day, time(0), tzinfo=tz) <= last:
        for slot in slots:
            start = datetime.combine(day, slot.at, tzinfo=tz)
            if slot.weekday == day.weekday() and after < start <= last:
                yield start
        day += timedelta(days=1)


def _free(start: datetime, end: datetime, busy: Sequence[Span]) -> bool:
    return all(end <= b_start or start >= b_end for b_start, b_end in busy)


def build(
    plan: Plan, n: int, busy: Sequence[Span], *, now: datetime, tz: tzinfo, until: datetime
) -> list[Move]:
    """The moves for a skip of session `n`, or ReplanRefused (plain words). `busy`: the other
    entries of his calendar up to `until` (never this plan's own sessions)."""
    moving = tail(plan, n, now)
    ids = {s.n for s in moving}
    taken = [*busy, *((s.start, s.end) for s in plan.sessions if s.n not in ids)]
    starts = _slots(rhythm(plan, tz), max(now, moving[0].start), tz, until)
    moves: list[Move] = []
    for s in moving:
        length = s.end - s.start
        start = next((c for c in starts if _free(c, c + length, taken)), None)
        if start is None:
            raise ReplanRefused(
                f"I couldn't find free slots for all {len(moving)} sessions, Sir: too many of "
                "the coming ones are busy. Nothing was moved."
            )
        taken.append((start, start + length))
        moves.append(Move(s.n, s.start, start, start + length))
    verify(plan, n, moves, now=now)
    return moves


def verify(plan: Plan, n: int, moves: Sequence[Move], *, now: datetime) -> None:
    """Refuse a re-plan that would lose a session (D6). Raises ReplanRefused."""
    expected = [s.n for s in tail(plan, n, now)]
    if sorted(m.n for m in moves) != sorted(expected) or len(moves) != len(expected):
        raise ReplanRefused(
            f"This re-plan would lose a session, Sir ({len(expected)} must move, {len(moves)} "
            "would), so nothing was moved."
        )
    if any(m.start <= now or m.end <= m.start for m in moves):
        raise ReplanRefused("This re-plan puts a session in the past, Sir, so nothing was moved.")
    after = applied(plan, moves, now)
    starts = [s.start for s in after.sessions]
    spans = sorted((m.start, m.end) for m in moves)
    overlap = any(
        a_end > b_start for (_, a_end), (b_start, _) in zip(spans, spans[1:], strict=False)
    )
    if len(set(starts)) != len(starts) or overlap:
        raise ReplanRefused(
            "This re-plan puts two sessions at the same time, Sir, which would lose one, so "
            "nothing was moved."
        )
    if len(after.sessions) != len(plan.sessions):
        raise ReplanRefused("This re-plan would lose a session, Sir, so nothing was moved.")
    by_n = {m.n: m.start for m in moves}
    order = [by_n[k] for k in expected]
    if order != sorted(order):
        raise ReplanRefused("This re-plan changes the order of the sessions, Sir: not moved.")


def applied(plan: Plan, moves: Sequence[Move], now: datetime) -> Plan:
    """The plan after `moves`: every session is still there; a moved one has its new time and
    is `moved` (planned again, asked about after the new time)."""
    by_n = {m.n: m for m in moves}
    sessions = [
        s.model_copy(
            update={
                "start": by_n[s.n].start,
                "end": by_n[s.n].end,
                "state": "moved",
                "answered_at": None,
            }
        )
        if s.n in by_n
        else s
        for s in plan.sessions
    ]
    return plan.model_copy(update={"sessions": sessions, "updated_at": now})


__all__ = ["MAX_DAYS", "Slot", "applied", "build", "rhythm", "tail", "verify"]
