# src/jarvis/series/cards.py
"""JARVIS's own words about a plan (R11.1 O2b, D6): the check-in question, the re-plan card and
what an answer or a move did. Fixed templates by code: a session's number, the plan's name (only
when it is the owner's own word, `Plan.words`), dates and times. Never a title: titles may be a
file's words, and an alert or a card line never carries those."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, tzinfo

from jarvis.series.models import Move, Plan, PlanSession

_DAYS = "Mon Tue Wed Thu Fri Sat Sun".split()
_MONTHS = "Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split()
QUESTION = (
    "Session {n} of {total} in {plan} was at {at}. Did it happen, Sir? "
    "Say 'session done' or 'session skipped'."
)
ARROW = "→"


def _count(n: int) -> str:
    return f"{n} session{'' if n == 1 else 's'}"


def clock(at: datetime, tz: tzinfo) -> str:
    return at.astimezone(tz).strftime("%H:%M")


def day(at: datetime, tz: tzinfo) -> str:
    """ "8 Feb 2027" in the owner's zone."""
    d = at.astimezone(tz)
    return f"{d.day} {_MONTHS[d.month - 1]} {d.year}"


def when(at: datetime, tz: tzinfo) -> str:
    """ "Tue 24 Nov 19:00" in the owner's zone."""
    d = at.astimezone(tz)
    return f"{_DAYS[d.weekday()]} {d.day} {_MONTHS[d.month - 1]} {d:%H:%M}"


def question(plan: Plan, s: PlanSession, tz: tzinfo) -> str:
    """The check-in alert (kind `series_checkin`): number, plan, time. At most 300 characters."""
    return QUESTION.format(n=s.n, total=plan.total, plan=plan.words, at=clock(s.start, tz))


def waiting_words(plan: Plan, s: PlanSession, tz: tzinfo) -> str:
    """The same question on the console's check-in card (its two buttons answer it)."""
    return f"Session {s.n} of {plan.total} in {plan.words} ({when(s.start, tz)}): did it happen?"


def marked(plan: Plan, s: PlanSession) -> str:
    return f"Session {s.n} of {plan.total} in {plan.words} is marked {s.state}, Sir."


def _ends(plan: Plan, moves: Sequence[Move], tz: tzinfo) -> str:
    by_n = {m.n: m.start for m in moves}
    return day(max(by_n.get(s.n, s.start) for s in plan.sessions), tz)


def replan_card(plan: Plan, s: PlanSession, moves: Sequence[Move], tz: tzinfo) -> str:
    """The ONE approval card of a re-plan: how many move and why, the count before and after,
    the new last day, then every "old date -> new date" (the console lists these lines)."""
    k = len(moves)
    slots = "its next free slot" if k == 1 else "their next free slots"
    lines = [
        f"Move {_count(k)} of {plan.words} to {slots} (session {s.n} was skipped).",
        f"{_count(plan.total)} before, {plan.total} after: none is dropped. "
        f"The plan now ends on {_ends(plan, moves, tz)}.",
        *(f"{m.n}. {when(m.was, tz)} {ARROW} {when(m.start, tz)}" for m in moves),
    ]
    return "\n".join(lines)


def moved_words(plan: Plan, *, asked: int, moved: int, tz: tzinfo) -> str:
    """What an approved re-plan did, by code."""
    last = day(max(s.start for s in plan.sessions), tz) if plan.sessions else ""
    still = f"It still has {plan.total} and now ends on {last}."
    if moved == asked:
        return f"Moved {_count(moved)} of {plan.words}, Sir. {still}"
    if not moved:
        return f"None of the {_count(asked)} of {plan.words} could be moved, Sir."
    return (
        f"Moved {moved} of {_count(asked)} of {plan.words}, Sir; {asked - moved} could not be "
        f"moved (check your calendar). {still}"
    )


__all__ = [
    "ARROW",
    "QUESTION",
    "clock",
    "day",
    "marked",
    "moved_words",
    "question",
    "replan_card",
    "waiting_words",
    "when",
]
