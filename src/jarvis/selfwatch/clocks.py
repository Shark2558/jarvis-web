# src/jarvis/selfwatch/clocks.py
"""JARVIS's two clocks watch each other (docs/plans/r14-hardening.md D5).

- The morning tick (Cloud Scheduler `0,30 4-11`, `selfwatch_daily`) says "the 5-minute clock has
  not run since …" when the watchdog was not seen for `WATCHDOG_GAP` (20 minutes).
- The 5-minute watchdog (`selfwatch_clock`, Home on or off) says "the morning clock did not run
  today by 05:00" when no tick ran by `TICK_BY` on the owner's local day.
- Each is told once per outage (`clock_stopped`); the stopped clock's own next run says it is
  back (`selfwatch_ok`).
- The baseline is `first_seen`, the first time either clock was seen (kept, the earliest wins).
  A clock never seen is judged from it, never in a fresh install's first hour (`FRESH`): the
  morning clock is due at the first 05:00 at least an hour after it; the 5-minute clock is
  stopped once it is more than an hour old. So a clock that never starts after a deploy (a
  missing Scheduler job) is said once. With no clock seen at all nothing can be said.
- An alert that reached nobody is undone (`undo`): the outage it opened (or closed) goes back
  as it was, so the next run raises it again (the teller bounds the tries).
- If both clocks stop nothing can speak up; the Vitals item `clocks` shows it when he looks.

`{prefix}selfwatch/clocks` holds the two stamps and the open outages. Every update is a
transaction that keeps the later stamp of each clock (another process during a deploy may have
written one), and the observer's in-memory stamps (any job outcome from a clock proves it ran)
join on the next update. With the store down the clocks run on memory.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime, time, timedelta
from typing import Any, Literal
from zoneinfo import ZoneInfo

from jarvis.logging import get_logger
from jarvis.storage.docs import Docs, DocTx

log = get_logger(__name__)

WATCHDOG_GAP = timedelta(minutes=20)
TICK_BY = time(5, 0)
FRESH = timedelta(hours=1)  # a fresh install's first hour: a clock never seen is no outage yet
ClockName = Literal["tick", "watchdog"]


@dataclass(frozen=True)
class ClockState:
    tick: datetime | None = None
    watchdog: datetime | None = None
    tick_outage: str | None = None  # the local day "no tick by 05:00" was told
    watchdog_outage: datetime | None = None  # the watchdog's last run when it was told stopped
    first_seen: datetime | None = None  # the first time either clock was seen (the baseline)


@dataclass(frozen=True)
class Event:
    kind: Literal["clock_stopped", "selfwatch_ok"]
    clock: ClockName
    cause: str  # the claim's cause: one outage
    at: str = ""  # the local time the message names
    outage: str = ""  # the outage it opens or closes: a local day (tick) or a stamp (watchdog)
    never: bool = False  # the clock was never seen (judged from `first_seen`)


def _later(a: datetime | None, b: datetime | None) -> datetime | None:
    if a is None or b is None:
        return a or b
    return max(a, b)


def _earlier(a: datetime | None, b: datetime | None) -> datetime | None:
    if a is None or b is None:
        return a or b
    return min(a, b)


def watchdog_stopped(s: ClockState, now: datetime) -> datetime | None:
    """The watchdog's last run (or, never seen, the baseline) when it has not run for
    `WATCHDOG_GAP` (never seen: for `FRESH`); not told yet."""
    if s.watchdog_outage is not None:
        return None
    if s.watchdog is None:
        first = s.first_seen
        return first if first is not None and now - first > max(FRESH, WATCHDOG_GAP) else None
    return s.watchdog if now - s.watchdog > WATCHDOG_GAP else None


def tick_due(s: ClockState, tz: ZoneInfo) -> datetime | None:
    """A morning clock never seen: the first 05:00 at least `FRESH` after the baseline."""
    if s.tick is not None or s.first_seen is None:
        return None
    start = (s.first_seen + FRESH).astimezone(tz)
    due = datetime.combine(start.date(), TICK_BY, tzinfo=tz)
    return due if due >= start else datetime.combine(start.date() + timedelta(days=1), TICK_BY, tz)


def tick_missing(s: ClockState, now: datetime, tz: ZoneInfo) -> str | None:
    """Today's local date when no tick ran by 05:00 (judged from its last run, or never seen
    from the baseline); not told yet."""
    local = now.astimezone(tz)
    if s.tick_outage is not None or local.time() < TICK_BY:
        return None
    if s.tick is None:
        due = tick_due(s, tz)
        return local.date().isoformat() if due is not None and now >= due else None
    return None if s.tick.astimezone(tz).date() >= local.date() else local.date().isoformat()


def _seen_first(s: ClockState) -> ClockState:
    return replace(s, first_seen=_earlier(s.first_seen, _earlier(s.tick, s.watchdog)))


def on_watchdog(s: ClockState, now: datetime, tz: ZoneInfo) -> tuple[ClockState, list[Event]]:
    """The 5-minute clock ran: its stamp, its own recovery, and the morning clock's check."""
    s = _seen_first(replace(s, watchdog=_later(s.watchdog, now)))
    events: list[Event] = []
    if s.watchdog_outage is not None:
        was = s.watchdog_outage.isoformat()
        events.append(Event("selfwatch_ok", "watchdog", f"back:watchdog:{was}", outage=was))
        s = replace(s, watchdog_outage=None)
    day = tick_missing(s, now, tz)
    if day is not None:
        at = f"{TICK_BY:%H:%M}"
        events.append(Event("clock_stopped", "tick", f"tick:{day}", at, outage=day))
        s = replace(s, tick_outage=day)
    return s, events


def on_tick(s: ClockState, now: datetime, tz: ZoneInfo) -> tuple[ClockState, list[Event]]:
    """The morning clock ran: its stamp, its own recovery, and the 5-minute clock's check."""
    s = _seen_first(replace(s, tick=_later(s.tick, now)))
    events: list[Event] = []
    if s.tick_outage is not None:
        was = s.tick_outage
        events.append(Event("selfwatch_ok", "tick", f"back:tick:{was}", outage=was))
        s = replace(s, tick_outage=None)
    since = watchdog_stopped(s, now)
    if since is not None:
        at, was, never = f"{since.astimezone(tz):%H:%M}", since.isoformat(), s.watchdog is None
        cause = f"watchdog:{was}"
        events.append(Event("clock_stopped", "watchdog", cause, at, outage=was, never=never))
        s = replace(s, watchdog_outage=since)
    return s, events


def undo(s: ClockState, e: Event) -> ClockState:
    """The state as if `e` had not happened (its alert reached nobody: raised again next run)."""
    if e.clock == "tick":
        if e.kind == "clock_stopped":
            return replace(s, tick_outage=None) if s.tick_outage == e.outage else s
        return s if s.tick_outage is not None else replace(s, tick_outage=e.outage or None)
    was = _when(e.outage)
    if e.kind == "clock_stopped":
        return replace(s, watchdog_outage=None) if s.watchdog_outage == was else s
    return s if s.watchdog_outage is not None else replace(s, watchdog_outage=was)


def _when(v: object) -> datetime | None:
    if not isinstance(v, str):
        return None
    try:
        at = datetime.fromisoformat(v)
    except ValueError:
        return None
    return at if at.tzinfo is not None else None


STAMPS = ("tick", "watchdog", "watchdog_outage", "first_seen")


def decode(doc: dict[str, Any] | None) -> ClockState:
    """The stored state; a field that is there but unreadable (a naive time, a damaged value)
    reads as unknown and is logged (counts only)."""
    d = doc or {}
    day = d.get("tick_outage")
    got = ClockState(
        tick=_when(d.get("tick")),
        watchdog=_when(d.get("watchdog")),
        tick_outage=day if isinstance(day, str) and len(day) == 10 else None,
        watchdog_outage=_when(d.get("watchdog_outage")),
        first_seen=_when(d.get("first_seen")),
    )
    bad = sum(d.get(k) is not None and getattr(got, k) is None for k in (*STAMPS, "tick_outage"))
    if bad:
        log.warning("selfwatch clocks: stored fields unreadable", extra={"count": bad})
    return got


def encode(s: ClockState) -> dict[str, Any]:
    def iso(at: datetime | None) -> str | None:
        return None if at is None else at.isoformat()

    return {
        "tick": iso(s.tick),
        "watchdog": iso(s.watchdog),
        "tick_outage": s.tick_outage,
        "watchdog_outage": iso(s.watchdog_outage),
        "first_seen": iso(s.first_seen),
    }


def merged(stored: ClockState, mine: ClockState) -> ClockState:
    """The later stamp of each clock, the earlier baseline; the stored outages (another process
    may have told one)."""
    return replace(
        stored,
        tick=_later(stored.tick, mine.tick),
        watchdog=_later(stored.watchdog, mine.watchdog),
        first_seen=_earlier(stored.first_seen, mine.first_seen),
    )


class Clocks:
    def __init__(self, *, prefix: str = "jarvis_") -> None:
        self._path = f"{prefix}selfwatch/clocks"
        self.mine = ClockState()

    def seen(self, clock: str, at: datetime) -> None:
        """The observer's stamp: a job outcome from this clock proves it ran (sync, in memory)."""
        if clock == "tick":
            self.mine = replace(self.mine, tick=_later(self.mine.tick, at))
        elif clock == "watchdog":
            self.mine = replace(self.mine, watchdog=_later(self.mine.watchdog, at))

    async def update(
        self, docs: Docs, change: Callable[[ClockState], ClockState]
    ) -> tuple[ClockState, bool]:
        """Read, change, write in one transaction; (the new state, whether it was kept)."""

        async def fn(tx: DocTx) -> ClockState:
            new = change(merged(decode(await tx.get(self._path)), self.mine))
            tx.set(self._path, encode(new))
            return new

        try:
            got = await docs.transaction(fn)
        except Exception as exc:  # noqa: BLE001 - the clocks run on memory meanwhile
            log.warning("selfwatch clocks not kept", extra={"error": type(exc).__name__})
            self.mine = change(self.mine)
            return self.mine, False
        self.mine = merged(got, self.mine)  # a stamp the observer made meanwhile is kept
        return got, True

    async def read(self, docs: Docs) -> ClockState:
        try:
            return merged(decode(await docs.get(self._path)), self.mine)
        except Exception as exc:  # noqa: BLE001
            log.warning("selfwatch clocks unreadable", extra={"error": type(exc).__name__})
            return self.mine


__all__ = [
    "FRESH",
    "TICK_BY",
    "WATCHDOG_GAP",
    "ClockName",
    "ClockState",
    "Clocks",
    "Event",
    "decode",
    "encode",
    "merged",
    "on_tick",
    "on_watchdog",
    "tick_due",
    "tick_missing",
    "undo",
    "watchdog_stopped",
]
