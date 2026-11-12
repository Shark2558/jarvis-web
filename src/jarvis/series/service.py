# src/jarvis/series/service.py
"""Following a series of sessions (R11.1 O2b; docs/plans/r11-1-observations.md D6; Layer 5,
Task & Productivity). No model anywhere.

- `PlanBook` for the batch tool: `room` (at most 10 plans of 200 sessions), `remember` (the
  events an approved batch made become the plan's sessions, numbered in time order; a second
  batch with the same name extends the plan; an event already known is never added twice) and
  `forget` (an Undo took the events away).
- `waiting`: sessions that ended at least `ASK_AFTER` ago and have no answer yet.
- `mark`: "done" or "skipped" for a named session, or for the one that is waiting.
- `recheck`: before a check-in, the session's event as his calendar has it (`series.sync`):
  deleted by hand, the session is `removed` and never asked; moved by hand, it takes the new
  time and is asked after it.
- `proposal`: the re-plan for a skipped session: the plan is first brought up to date with his
  calendar, then `replan.build` moves that session, every other skipped one and every later one
  to the next free slots of the plan's own rhythm; his other entries and the plan's sessions
  that stay (at their real times; the ones he placed himself, or that now have guests, among
  them) are busy. `move` applies it (`series.moving`): `replan.verify` once more, each event
  patched (five at a time), then the plan's record; what could not be moved is said, by number.

Google and the clock are read when a call runs (the app builds them around this part).
"""

from __future__ import annotations

import math
from collections.abc import Callable, Collection, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Literal

from jarvis.integrations.google import (
    GoogleAPIError,
    GoogleConnector,
    GoogleNotConnected,
    GoogleNotFound,
)
from jarvis.logging import get_logger
from jarvis.series import moving, replan, sync
from jarvis.series.calendar import batch_listing, other_events
from jarvis.series.models import (
    MAX_PLANS,
    MAX_SESSIONS,
    OPEN_STATES,
    TITLE_MAX,
    Book,
    Plan,
    PlanSession,
    ReplanRefused,
    plan_id,
)
from jarvis.series.moving import Asked as Proposal
from jarvis.series.moving import Moved
from jarvis.series.store import SeriesStore
from jarvis.tools.calendar_batch import Made, changed_by_owner
from jarvis.tools.google_calendar import EVENTS_URL, CalendarAPI

log = get_logger(__name__)

ASK_AFTER = timedelta(minutes=15)
LOOK_AHEAD_SLOTS = 20  # how many of the plan's slots past its end a re-plan may look at
MIN_LOOK_AHEAD_WEEKS = 4
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
        n=n,
        event_id=m.event_id,
        title=m.title[:TITLE_MAX],
        start=m.start,
        end=m.end,
        batch=m.batch,
        item=m.n,
    )


def _placed(plan: Plan, events: dict[str, Any], n: int, now: datetime) -> dict[int, str]:
    """The sessions a re-plan leaves where they are, and why: he changed the event himself, or it
    now has guests or repeats. ReplanRefused when that is the skipped session itself."""
    out: dict[int, str] = {}
    for s in plan.sessions:
        e = events.get(s.event_id)
        if e is None or s.state in ("done", "removed") or (s.n != n and s.start <= now):
            continue
        why = moving.stays_why(e)
        if s.n == n and why:
            raise ReplanRefused(
                f"Session {n} can't be moved by me, Sir: {why}. Move it in Google Calendar."
            )
        if s.n != n and (why or changed_by_owner(e)):
            out[s.n] = why or moving.YOU_CHANGED
    return out


def _numbered(old: Sequence[PlanSession], new: Sequence[Made]) -> list[PlanSession]:
    """Numbered in time order while nothing is answered or moved; after that the numbers he has
    heard stay, and new sessions follow them."""
    fresh = sorted(new, key=lambda m: (m.start, m.title))
    if all(s.state == "planned" for s in old):
        rows: list[tuple[datetime, str, PlanSession | Made]] = [
            *((s.start, s.title, s) for s in old),
            *((m.start, m.title, m) for m in fresh),
        ]
        both = sorted(rows, key=lambda row: row[:2])
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
            base = plan or Plan(
                id=pid, name=name, prefix=prefix, outside=outside, created_at=now, updated_at=now
            )
            rows, fresh = sync.relinked(base.sessions, new, TITLE_MAX)  # never a second row
            _room(book, plan, len(fresh))
            update = {
                "sessions": _numbered(rows, fresh),
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

    async def waiting(self, uid: str, *, within: timedelta | None = None) -> list[Waiting]:
        """Sessions that ended at least `ASK_AFTER` ago with no answer, the latest first;
        `within`: only those that ended at most that long ago."""
        now = self._now()
        out = [
            Waiting(p, s)
            for p in (await self._store.load(uid)).plans
            for s in p.sessions
            if s.state in OPEN_STATES
            and s.end + ASK_AFTER <= now
            and (within is None or now - s.end <= within)
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

    async def skipped(
        self, uid: str, series: str | None = None, session: int | None = None
    ) -> Waiting:
        """The session a re-plan starts from: the named one, else the last one he skipped.
        Reads JARVIS's own record only. LookupError (plain words) when there is none."""
        return self._skipped(await self._store.load(uid), series, session)

    async def recheck(self, uid: str, plan: Plan, s: PlanSession) -> str:
        """Before a check-in: "ok" (as recorded), "removed" (he deleted the event: never asked),
        "moved" (he moved it: the plan takes the new time) or "unknown" (it could not be read:
        asked as recorded)."""
        conn = self._google()
        if conn is None:
            return "unknown"
        try:
            event = await conn.request(uid, "GET", f"{EVENTS_URL}/{s.event_id}")
        except GoogleNotFound:
            event = None
        except (GoogleAPIError, GoogleNotConnected) as exc:
            log.warning("a session could not be checked first", extra={"error": type(exc).__name__})
            return "unknown"
        new = sync.session_synced(s, event if isinstance(event, dict) else None, now=self._now())
        if new == s:
            return "ok"
        one = plan.model_copy(update={"sessions": [new]})

        def work(book: Book) -> Book:
            stored = book.plan(plan.id)
            return book if stored is None else book.replaced(sync.carried(stored, one))

        await self._store.change(uid, work)
        return "removed" if new.state == "removed" else "moved"

    async def _synced(
        self, uid: str, conn: GoogleConnector, plan: Plan
    ) -> tuple[Plan, dict[str, Any]]:
        """The plan as his calendar has it now (saved when it changed), and its events by id."""
        events: dict[str, Any] = {}
        complete = True
        for batch in sorted({s.batch for s in plan.sessions if s.batch}):
            found, whole = await batch_listing(conn, uid, batch)
            complete = complete and whole
            events.update({str(e.get("id")): e for e in found.values()})
        fresh = sync.synced(plan, events, complete=complete, now=self._now())
        if fresh is plan:
            return plan, events

        def work(book: Book) -> Book:
            stored = book.plan(plan.id)
            return book if stored is None else book.replaced(sync.carried(stored, fresh))

        try:
            after = (await self._store.change(uid, work)).plan(plan.id)
        except Exception as exc:  # noqa: BLE001 - planned on what his calendar says anyway
            log.warning("a plan was not brought up to date", extra={"error": type(exc).__name__})
            return fresh, events
        return after or fresh, events

    async def proposal(
        self, uid: str, series: str | None = None, session: int | None = None
    ) -> Proposal:
        """The re-plan for a skipped session (the named one, else the last one he skipped).
        It only writes JARVIS's own record (brought up to date with his calendar). LookupError
        / ReplanRefused carry plain words."""
        found = await self.skipped(uid, series, session)
        conn, now, n = self._conn(), self._now(), found.session.n
        plan, events = await self._synced(uid, conn, found.plan)
        tz = await CalendarAPI(conn, None, self._tz).owner_tz(uid)
        kept = _placed(plan, events, n, now)
        slots = len(replan.rhythm(plan, tz, skip=kept)) or 1
        weeks = max(MIN_LOOK_AHEAD_WEEKS, math.ceil(LOOK_AHEAD_SLOTS / slots))
        until = max([now, *(s.end for s in plan.sessions)]) + timedelta(weeks=weeks)
        going = {s.event_id for s in replan.tail(plan, n, now, kept)}
        busy = await other_events(conn, uid, now, until, going, tz)
        moves = replan.build(plan, n, busy, now=now, tz=tz, until=until, keep=kept)
        replan.verify(plan, n, moves, now=now, keep=kept)  # never even proposed if one is lost
        session_now = plan.session(n) or found.session
        return Proposal(plan, session_now, moves, tz, events, kept)

    async def move(self, uid: str, series: str | None = None, session: int | None = None) -> Moved:
        """Apply the re-plan: checked once more, then each event, then the plan's record."""
        p = await self.proposal(uid, series, session)
        replan.verify(p.plan, p.session.n, p.moves, now=self._now(), keep=p.kept)
        return await moving.apply(self._store, self._conn(), uid, p, self._now())


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
