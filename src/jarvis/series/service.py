# src/jarvis/series/service.py
"""Following a series of sessions (R11.1 O2b; docs/plans/r11-1-observations.md D6; Layer 5,
Task & Productivity). No model anywhere.

- `PlanBook` for the batch tool: `room` (at most 10 plans of 200 sessions), `remember` (the
  events an approved batch made become the plan's sessions, numbered in time order; a second
  batch with the same name extends the plan; an event already known is never added twice) and
  `forget` (an Undo took the events away).
- `waiting`: sessions that ended at least `ASK_AFTER` ago and have no answer yet.
- `mark`: "done" or "skipped" for a named session, or for the one that is waiting.
- `proposal`: the re-plan for a skipped session: his calendar's other entries are read, then
  `replan.build` moves that session and every later one to the next free slots of the plan's own
  rhythm. `move` applies it: `replan.verify` once more, each event patched (five at a time), then
  the plan's record. An event he changed himself, or that is gone, is left as it is and said so.

Google and the clock are read when a call runs (the app builds them around this part).
"""

from __future__ import annotations

import asyncio
import math
from collections.abc import Callable, Collection, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta, tzinfo
from typing import Any, Literal

from jarvis.integrations.google import GoogleAPIError, GoogleConnector, GoogleNotFound
from jarvis.logging import get_logger
from jarvis.series import replan
from jarvis.series.calendar import batch_events, move_event, other_events
from jarvis.series.models import (
    MAX_PLANS,
    MAX_SESSIONS,
    OPEN_STATES,
    TITLE_MAX,
    Book,
    Move,
    Plan,
    PlanSession,
    ReplanRefused,
    plan_id,
)
from jarvis.series.store import SeriesStore
from jarvis.tools.calendar_batch import Made, changed_by_owner
from jarvis.tools.google_calendar import EVENTS_URL, CalendarAPI

log = get_logger(__name__)

ASK_AFTER = timedelta(minutes=15)
LOOK_AHEAD_SLOTS = 20  # how many of the plan's slots past its end a re-plan may look at
MIN_LOOK_AHEAD_WEEKS = 4
PARALLEL = 5
Answer = Literal["done", "skipped"]
NOT_LINKED = "Google is not linked, Sir, so I can't look at your calendar."
NOTHING_WAITING = "No session is waiting for an answer, Sir."
NOTHING_SKIPPED = "No skipped session is waiting for new dates, Sir."
NO_PLAN = "You have no plan by that name, Sir."
TOO_MANY_PLANS = f"You already follow {MAX_PLANS} plans, Sir: stop one before starting another."


@dataclass(frozen=True)
class Waiting:
    plan: Plan
    session: PlanSession


@dataclass(frozen=True)
class Proposal:
    plan: Plan
    session: PlanSession
    moves: list[Move]
    tz: tzinfo


@dataclass(frozen=True)
class Moved:
    plan: Plan  # as it is after the moves that went through
    asked: int
    moved: int
    kept: int = 0  # he changed the event himself: left where it is
    missing: int = 0  # the event is no longer in his calendar
    failed: int = 0
    tz: tzinfo | None = field(default=None, compare=False)


def _room(book: Book, plan: Plan | None, count: int) -> None:
    if plan is None and len(book.plans) >= MAX_PLANS:
        raise ValueError(TOO_MANY_PLANS)
    total = (plan.total if plan is not None else 0) + count
    if total > MAX_SESSIONS:
        raise ValueError(
            f"A plan holds at most {MAX_SESSIONS} sessions, Sir; this would make {total}."
        )


def _session(m: Made, n: int) -> PlanSession:
    return PlanSession(
        n=n, event_id=m.event_id, title=m.title[:TITLE_MAX], start=m.start, end=m.end, batch=m.batch
    )


def _numbered(old: Sequence[PlanSession], new: Sequence[Made]) -> list[PlanSession]:
    """Numbered in time order while nothing is answered or moved; after that the numbers he has
    heard stay, and new sessions follow them."""
    fresh = sorted(new, key=lambda m: (m.start, m.title))
    if all(s.state == "planned" for s in old):
        both = sorted(
            [*((s.start, s.title, s) for s in old), *((m.start, m.title, m) for m in fresh)],
            key=lambda row: row[:2],
        )
        return [
            x.model_copy(update={"n": i}) if isinstance(x, PlanSession) else _session(x, i)
            for i, (_, _, x) in enumerate(both, 1)
        ]
    top = max((s.n for s in old), default=0)
    return [*old, *(_session(m, top + i) for i, m in enumerate(fresh, 1))]


def _find(book: Book, series: str | None, session: int | None, now: datetime) -> Waiting:
    """The session an answer is about: the named one, else the waiting one that ended last.
    LookupError (plain words) when there is none."""
    plans = list(book.plans)
    if series:
        plan = book.plan(series)
        if plan is None:
            raise LookupError(NO_PLAN)
        plans = [plan]
    waits = [
        Waiting(p, s)
        for p in plans
        for s in p.sessions
        if s.state in OPEN_STATES and s.end + ASK_AFTER <= now
    ]
    waits.sort(key=lambda w: w.session.end, reverse=True)
    if session is None:
        if not waits:
            raise LookupError(NOTHING_WAITING)
        return waits[0]
    named = [w for w in waits if w.session.n == session] or [
        Waiting(p, s) for p in plans for s in p.sessions if s.n == session
    ]
    if not named:
        raise LookupError(f"There is no session {session} in that plan, Sir.")
    return named[0]


class SeriesService:
    def __init__(
        self,
        store: SeriesStore,
        *,
        now: Callable[[], datetime],
        tz: str,
        google: Callable[[], GoogleConnector | None],
    ) -> None:
        self._store, self._now, self._tz, self._google = store, now, tz, google

    @property
    def store(self) -> SeriesStore:
        return self._store

    # ---- PlanBook (the batch tool) ----------------------------------------------------------

    async def room(self, uid: str, name: str, count: int) -> None:
        book = await self._store.load(uid)
        _room(book, book.plan(plan_id(name)), count)

    async def remember(
        self, uid: str, *, name: str, prefix: str, outside: bool, sessions: Sequence[Made]
    ) -> None:
        now = self._now()

        def work(book: Book) -> Book:
            pid = plan_id(name)
            plan = book.plan(pid)
            known = {s.event_id for s in plan.sessions} if plan is not None else set()
            new = [m for m in sessions if m.event_id and m.event_id not in known]
            if not new:
                return book
            _room(book, plan, len(new))
            base = plan or Plan(
                id=pid, name=name, prefix=prefix, outside=outside, created_at=now, updated_at=now
            )
            update = {
                "sessions": _numbered(base.sessions, new),
                "outside": base.outside or outside,  # once from a file, always
                "updated_at": now,
            }
            return book.replaced(base.model_copy(update=update))

        await self._store.change(uid, work)

    async def forget(self, uid: str, event_ids: Collection[str]) -> None:
        gone, now = set(event_ids), self._now()

        def work(book: Book) -> Book:
            out = book
            for plan in book.plans:
                left = [s for s in plan.sessions if s.event_id not in gone]
                if len(left) != plan.total:
                    out = out.replaced(
                        plan.model_copy(update={"sessions": left, "updated_at": now})
                    )
            return out

        await self._store.change(uid, work)

    # ---- reading and answers ----------------------------------------------------------------

    async def book(self, uid: str) -> Book:
        return await self._store.load(uid)

    async def waiting(self, uid: str) -> list[Waiting]:
        """Sessions that ended at least `ASK_AFTER` ago with no answer, the latest first."""
        now = self._now()
        out = [
            Waiting(p, s)
            for p in (await self._store.load(uid)).plans
            for s in p.sessions
            if s.state in OPEN_STATES and s.end + ASK_AFTER <= now
        ]
        return sorted(out, key=lambda w: w.session.end, reverse=True)

    async def mark(
        self, uid: str, answer: Answer, *, series: str | None = None, session: int | None = None
    ) -> Waiting:
        """Record his answer. LookupError (plain words) when no such session is there."""
        now = self._now()
        marked: list[Waiting] = []

        def work(book: Book) -> Book:
            found = _find(book, series, session, now)
            s = found.session.model_copy(update={"state": answer, "answered_at": now})
            sessions = [s if x.n == s.n else x for x in found.plan.sessions]
            plan = found.plan.model_copy(update={"sessions": sessions, "updated_at": now})
            marked.append(Waiting(plan, s))
            return book.replaced(plan)

        await self._store.change(uid, work)
        return marked[-1]

    # ---- the re-plan ------------------------------------------------------------------------

    def _conn(self) -> GoogleConnector:
        conn = self._google()
        if conn is None:
            raise ReplanRefused(NOT_LINKED)
        return conn

    @staticmethod
    def _skipped(book: Book, series: str | None, session: int | None) -> Waiting:
        plans = list(book.plans)
        if series:
            plan = book.plan(series)
            if plan is None:
                raise LookupError(NO_PLAN)
            plans = [plan]
        if session is not None:
            named = [Waiting(p, s) for p in plans for s in p.sessions if s.n == session]
            if not named:
                raise LookupError(f"There is no session {session} in that plan, Sir.")
            return named[0]
        skipped = [Waiting(p, s) for p in plans for s in p.sessions if s.state == "skipped"]
        if not skipped:
            raise LookupError(NOTHING_SKIPPED)
        return max(skipped, key=lambda w: w.session.answered_at or w.session.end)

    async def proposal(
        self, uid: str, series: str | None = None, session: int | None = None
    ) -> Proposal:
        """The re-plan for a skipped session (the named one, else the last one he skipped).
        Read-only. LookupError / ReplanRefused carry plain words."""
        found = self._skipped(await self._store.load(uid), series, session)
        conn, now, plan = self._conn(), self._now(), found.plan
        tz = await CalendarAPI(conn, None, self._tz).owner_tz(uid)
        slots = len(replan.rhythm(plan, tz)) or 1
        weeks = max(MIN_LOOK_AHEAD_WEEKS, math.ceil(LOOK_AHEAD_SLOTS / slots))
        until = max([now, *(s.end for s in plan.sessions)]) + timedelta(weeks=weeks)
        own = {s.event_id for s in plan.sessions}
        busy = await other_events(conn, uid, now, until, own)
        moves = replan.build(plan, found.session.n, busy, now=now, tz=tz, until=until)
        replan.verify(plan, found.session.n, moves, now=now)  # never even proposed if one is lost
        return Proposal(plan, found.session, moves, tz)

    async def _events(self, conn: GoogleConnector, uid: str, plan: Plan) -> dict[str, Any]:
        """The plan's events as Google has them now, by id (listed by their batch markers)."""
        found: dict[str, Any] = {}
        for batch in sorted({s.batch for s in plan.sessions if s.batch}):
            for e in (await batch_events(conn, uid, batch)).values():
                found[str(e.get("id"))] = e
        return found

    async def _move_one(
        self, conn: GoogleConnector, uid: str, event: Any, s: PlanSession, m: Move, tz: tzinfo
    ) -> str:
        """moved | kept | missing | failed. Never raises."""
        try:
            if event is None:
                event = await conn.request(uid, "GET", f"{EVENTS_URL}/{s.event_id}")
            if not isinstance(event, dict) or event.get("status") == "cancelled":
                return "missing"
            if changed_by_owner(event):
                return "kept"
            await move_event(conn, uid, event, m, tz)
        except GoogleNotFound:
            return "missing"
        except GoogleAPIError as exc:
            log.warning("a session wasn't moved", extra={"error": type(exc).__name__})
            return "failed"
        except Exception as exc:  # noqa: BLE001 - one session never fails the re-plan
            log.warning("a session wasn't moved", extra={"error": type(exc).__name__})
            return "failed"
        return "moved"

    async def move(self, uid: str, series: str | None = None, session: int | None = None) -> Moved:
        """Apply the re-plan: checked once more, then each event, then the plan's record."""
        p = await self.proposal(uid, series, session)
        now = self._now()
        replan.verify(p.plan, p.session.n, p.moves, now=now)
        conn = self._conn()
        events = await self._events(conn, uid, p.plan)
        by_n = {s.n: s for s in p.plan.sessions}
        pairs = [(by_n[m.n], m) for m in p.moves]  # `verify`: every move is a session of the plan
        outcomes: list[str] = []
        for i in range(0, len(pairs), PARALLEL):
            outcomes += await asyncio.gather(
                *(
                    self._move_one(conn, uid, events.get(s.event_id), s, m, p.tz)
                    for s, m in pairs[i : i + PARALLEL]
                )
            )
        went = [m for m, how in zip(p.moves, outcomes, strict=True) if how == "moved"]
        pid = p.plan.id

        def work(book: Book) -> Book:
            return book.replaced(replan.applied(book.plan(pid) or p.plan, went, now))

        after = (await self._store.change(uid, work)).plan(pid) or p.plan
        return Moved(
            after,
            asked=len(p.moves),
            moved=len(went),
            kept=outcomes.count("kept"),
            missing=outcomes.count("missing"),
            failed=outcomes.count("failed"),
            tz=p.tz,
        )


__all__ = [
    "ASK_AFTER",
    "NOTHING_SKIPPED",
    "NOTHING_WAITING",
    "NOT_LINKED",
    "NO_PLAN",
    "Answer",
    "Moved",
    "Proposal",
    "SeriesService",
    "Waiting",
]
