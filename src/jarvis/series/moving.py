# src/jarvis/series/moving.py
"""Applying an approved re-plan (R11.1 O2b; docs/plans/r11-1-observations.md D6; Layer 6). Each
session's event is patched to its new time, five at a time, then the plan's record. What can't
be moved is never reported as moved, and never as failed when it may have happened:

    moved        patched (or patched, its answer lost, and read again with the new time)
    kept         he changed the event himself since: left where he put it
    left         it now has guests or repeats, or is not his: moving it would not tell the
                 others (`sendUpdates=none`), so it stays, and the result names it
    missing      its event is no longer in his calendar
    unconfirmed  Google did not answer and the event does not show the new time
    failed       Google refused it

A record that could not be updated after the calendar moved is said in the result (check-ins
may then ask at the old times), never raised: the events have already moved.
`stays_why` is the same rule for the re-plan itself: such a session is left out of the moves
and its time counts as busy.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, tzinfo
from typing import Any

from jarvis.integrations.google import (
    GoogleConnector,
    GoogleNotFound,
    GoogleUncertain,
)
from jarvis.logging import get_logger
from jarvis.series import replan, sync
from jarvis.series.calendar import move_event
from jarvis.series.models import Book, Move, Plan, PlanSession
from jarvis.series.store import SeriesStore
from jarvis.tools.calendar_batch import changed_by_owner
from jarvis.tools.calendar_cards import others_on
from jarvis.tools.google_calendar import EVENTS_URL

log = get_logger(__name__)

PARALLEL = 5
YOU_CHANGED = "you changed it"
GUESTS = "other people are on it, and moving it would not tell them"
REPEATS = "it repeats"
NOT_YOURS = "you're not its organiser"
SPECIAL = "it is a special kind of event"


@dataclass(frozen=True)
class Moved:
    plan: Plan  # as it is after the moves that went through
    asked: int
    moved: int
    kept: int = 0
    missing: int = 0
    failed: int = 0
    unconfirmed: int = 0
    left: tuple[tuple[int, str], ...] = ()  # (session, why), in JARVIS's own words
    unrecorded: bool = False  # the calendar moved, the plan's record could not be updated
    tz: tzinfo | None = field(default=None, compare=False)


def stays_why(event: dict[str, Any]) -> str:
    """Why this event must not be moved by JARVIS ("" when it may be)."""
    if others_on(event):
        return GUESTS
    if event.get("recurrence") or event.get("recurringEventId"):
        return REPEATS
    organizer = event.get("organizer")
    if isinstance(organizer, dict) and not organizer.get("self"):
        return NOT_YOURS
    if str(event.get("eventType") or "default") != "default":
        return SPECIAL
    return ""


async def _settled(conn: GoogleConnector, uid: str, s: PlanSession, m: Move) -> str:
    """A patch whose answer was lost: read the event again; moved when it shows the new time."""
    try:
        event = await conn.request(uid, "GET", f"{EVENTS_URL}/{s.event_id}")
    except Exception as exc:  # noqa: BLE001 - can't tell: never called failed or moved
        log.warning("a session's move could not be checked", extra={"error": type(exc).__name__})
        return "unconfirmed"
    start, _ = sync.span_of(event) if isinstance(event, dict) else (None, None)
    return "moved" if start == m.start else "unconfirmed"


async def move_one(
    conn: GoogleConnector,
    uid: str,
    event: Any,
    s: PlanSession,
    m: Move,
    tz: tzinfo,
    *,
    asked_for: bool = False,
) -> tuple[str, str]:
    """(outcome, why). `asked_for`: the session he skipped, which he asked to re-plan even if
    he edited it. Never raises."""
    try:
        if event is None:
            event = await conn.request(uid, "GET", f"{EVENTS_URL}/{s.event_id}")
        if not isinstance(event, dict) or event.get("status") == "cancelled":
            return "missing", ""
        if not asked_for and changed_by_owner(event):
            return "kept", YOU_CHANGED
        if why := stays_why(event):
            return "left", why
        await move_event(conn, uid, event, m, tz)
    except GoogleNotFound:
        return "missing", ""
    except GoogleUncertain:
        log.warning("a session's move was not confirmed; reading it again")
        return await _settled(conn, uid, s, m), ""
    except Exception as exc:  # noqa: BLE001 - one session never fails the rest (GoogleAPIError too)
        log.warning("a session wasn't moved", extra={"error": type(exc).__name__})
        return "failed", ""
    return "moved", ""


@dataclass(frozen=True)
class Asked:
    """What `apply` needs of an approved re-plan (`service.Proposal`)."""

    plan: Plan
    session: PlanSession
    moves: list[Move]
    tz: tzinfo
    events: dict[str, Any]
    kept: dict[int, str]


async def apply(
    store: SeriesStore, conn: GoogleConnector, uid: str, p: Asked, now: datetime
) -> Moved:
    by_n = {s.n: s for s in p.plan.sessions}
    changes = replan.real(p.moves)  # a session that keeps its time is not patched
    pairs = [(by_n[m.n], m) for m in changes]  # `verify`: every move is a session of the plan
    outcomes: list[tuple[str, str]] = []
    for i in range(0, len(pairs), PARALLEL):
        outcomes += await asyncio.gather(
            *(
                move_one(
                    conn, uid, p.events.get(s.event_id), s, m, p.tz, asked_for=s.n == p.session.n
                )
                for s, m in pairs[i : i + PARALLEL]
            )
        )
    went = [m for m, (how, _) in zip(changes, outcomes, strict=True) if how == "moved"]
    placed = [(m.n, why) for m, (how, why) in zip(changes, outcomes, strict=True) if how == "left"]
    left = [*p.kept.items(), *placed]
    pid, unrecorded = p.plan.id, False

    def work(book: Book) -> Book:
        stored = book.plan(pid) or p.plan
        return book.replaced(replan.applied(sync.carried(stored, p.plan), went, now))

    try:
        after = (await store.change(uid, work)).plan(pid) or p.plan
    except Exception as exc:  # noqa: BLE001 - the calendar has moved: say so, never raise
        log.error(
            "the plan's record was not updated after a move", extra={"error": type(exc).__name__}
        )
        after, unrecorded = replan.applied(p.plan, went, now), True
    count = [how for how, _ in outcomes]
    return Moved(
        after,
        asked=len(changes),
        moved=len(went),
        kept=count.count("kept"),
        missing=count.count("missing"),
        failed=count.count("failed"),
        unconfirmed=count.count("unconfirmed"),
        left=tuple(sorted(left)),
        unrecorded=unrecorded,
        tz=p.tz,
    )


__all__ = ["PARALLEL", "YOU_CHANGED", "Asked", "Moved", "apply", "move_one", "stays_why"]
