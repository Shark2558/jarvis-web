# src/jarvis/series/cards.py
"""JARVIS's own words about a plan (R11.1 O2b, D6): the check-in question, the re-plan card and
what an answer or a move did. Fixed templates by code: a session's number, the plan's name (only
when it is the owner's own word, `Plan.words`), dates and times. Never a title: titles may be a
file's words, and an alert or a card line never carries those. The re-plan card's first line
carries no plan name either (R14 D13 (5)): Telegram shows that line alone."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime, tzinfo

from jarvis.series import replan
from jarvis.series.models import Move, Plan, PlanSession
from jarvis.series.moving import Moved

_DAYS = "Mon Tue Wed Thu Fri Sat Sun".split()
_MONTHS = "Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split()
QUESTION = (
    "Session {n} of {total} in {plan} was at {at}. Did it happen, Sir? "
    "Say 'session done' or 'session skipped'."
)
ARROW = "→"
CARD_PLAN = "your plan"  # the re-plan card's first line: code's words only (R14 D13 (5))
SHOW_LEFT = 5  # sessions named one by one; the rest are counted


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


def skipped_words(plan: Plan) -> str:
    """Skipped sessions that still sit at their old time ("" when there is none): the console
    offers "Propose new dates" beside it."""
    k = sum(s.state == "skipped" for s in plan.sessions)
    if not k:
        return ""
    return f"{k} skipped session{'' if k == 1 else 's'} of {plan.words} {_has(k)} no new date yet."


def _has(k: int) -> str:
    return "has" if k == 1 else "have"


def marked(plan: Plan, s: PlanSession) -> str:
    return f"Session {s.n} of {plan.total} in {plan.words} is marked {s.state}, Sir."


def _ends(plan: Plan, moves: Sequence[Move], tz: tzinfo) -> str:
    by_n = {m.n: m.start for m in moves}
    return day(max(by_n.get(s.n, s.start) for s in plan.sessions), tz)


def _left(kept: Mapping[int, str]) -> str:
    """ "session 9 (other people are on it), session 11 (you changed it)" ("" when none)."""
    named = [f"session {n} ({why})" for n, why in sorted(kept.items())[:SHOW_LEFT]]
    more = len(kept) - SHOW_LEFT
    return ", ".join(named) + (f" and {more} more" if more > 0 else "")


def replan_card(
    plan: Plan,
    s: PlanSession,
    moves: Sequence[Move],
    tz: tzinfo,
    kept: Mapping[int, str] | None = None,
) -> str:
    """The ONE approval card of a re-plan: how many move and why (and the earlier skipped ones
    that move too), the count before and after, the new last day, what stays where it is, then
    every "old date -> new date" (the console lists these lines). A session that keeps its own
    time (a gap he left absorbed the shift) is not listed. R14 D13 (5): the first line, the only
    one Telegram shows, names no plan (its name is the batch call's argument, the model's words);
    the stored plan's words open the second line, which only the console shows."""
    changes = replan.real(moves)
    k = len(changes)
    slots = "its next free slot" if k == 1 else "their next free slots"
    earlier = sum(1 for m in changes if m.n != s.n and _was_skipped(plan, m.n))
    also = (
        f"; {earlier} earlier skipped session{'' if earlier == 1 else 's'} "
        f"move{'s' if earlier == 1 else ''} too"
        if earlier
        else ""
    )
    lines = [
        f"Move {_count(k)} of {CARD_PLAN} to {slots} (session {s.n} was skipped{also}).",
        f"{_upper(plan.words)}: {_count(plan.total)} before, {plan.total} after: none is "
        f"dropped. The plan now ends on {_ends(plan, moves, tz)}.",
    ]
    if kept:
        lines.append(f"Left where they are: {_left(kept)}.")
    lines += [f"{m.n}. {when(m.was, tz)} {ARROW} {when(m.start, tz)}" for m in changes]
    return "\n".join(lines)


def _upper(words: str) -> str:
    return words[:1].upper() + words[1:]


def _was_skipped(plan: Plan, n: int) -> bool:
    found = plan.session(n)
    return found is not None and found.state == "skipped"


def _their(k: int, one: str, many: str) -> str:
    return one if k == 1 else many


def moved_words(plan: Plan, done: Moved) -> str:
    """What an approved re-plan did, by code: what moved, and every reason something did not."""
    assert done.tz is not None
    asked, moved = done.asked, done.moved
    last = day(max(s.start for s in plan.sessions), done.tz) if plan.sessions else ""
    still = f"It still has {plan.total} and now ends on {last}."
    if moved == asked:
        head = f"Moved {_count(moved)} of {plan.words}, Sir. {still}"
    elif not moved:
        head = f"None of the {_count(asked)} of {plan.words} could be moved, Sir."
    else:
        head = f"Moved {moved} of {_count(asked)} of {plan.words}, Sir. {still}"
    parts = [head]
    if done.kept:
        them = _their(done.kept, "it", "them")
        parts.append(f"{done.kept} you changed yourself stayed where you put {them}.")
    if done.missing:
        parts.append(
            f"{done.missing} {_their(done.missing, 'is', 'are')} no longer in your calendar."
        )
    if done.unconfirmed:
        parts.append(f"Google didn't confirm {done.unconfirmed}: check your calendar.")
    if done.failed:
        parts.append(f"{done.failed} could not be moved (check your calendar).")
    parts += [f"Session {n} was left where it is ({why})." for n, why in done.left[:SHOW_LEFT]]
    if len(done.left) > SHOW_LEFT:
        parts.append(f"{len(done.left) - SHOW_LEFT} more were left where they are.")
    if done.unrecorded:
        parts.append(
            "Your calendar moved, but the plan's record could not be updated, so check-ins may "
            "ask at the old times."
        )
    return " ".join(parts)


__all__ = [
    "ARROW",
    "CARD_PLAN",
    "QUESTION",
    "clock",
    "day",
    "marked",
    "moved_words",
    "question",
    "replan_card",
    "skipped_words",
    "waiting_words",
    "when",
]
