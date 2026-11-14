# src/jarvis/selfwatch/clocks.py
"""JARVIS's two clocks watch each other (docs/plans/r14-hardening.md D5).

- The morning tick (Cloud Scheduler `0,30 4-11`, `selfwatch_daily`) says "the 5-minute clock has
  not run since …" when the watchdog was not seen for `WATCHDOG_GAP` (20 minutes).
- The 5-minute watchdog (`selfwatch_clock`, Home on or off) says "the morning clock did not run
  today by 05:00" when no tick ran by `TICK_BY` on the owner's local day.
- Each is told once per outage (`clock_stopped`); the stopped clock's own next run says it is
  back (`selfwatch_ok`). Nothing is said without a baseline (a clock never seen yet).
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
ClockName = Literal["tick", "watchdog"]


@dataclass(frozen=True)
class ClockState:
    tick: datetime | None = None
    watchdog: datetime | None = None
    tick_outage: str | None = None  # the local day "no tick by 05:00" was told
    watchdog_outage: datetime | None = None  # the watchdog's last run when it was told stopped


@dataclass(frozen=True)
class Event:
    kind: Literal["clock_stopped", "selfwatch_ok"]
    clock: ClockName
    cause: str  # the claim's cause: one outage
    at: str = ""  # the local time the message names
    outage: str = ""  # the outage it opens or closes: a local day (tick) or a stamp (watchdog)


def _later(a: datetime | None, b: datetime | None) -> datetime | None:
    if a is None or b is None:
        return a or b
    return max(a, b)


def watchdog_stopped(s: ClockState, now: datetime) -> datetime | None:
    """The watchdog's last run, when it has not run for `WATCHDOG_GAP` (not told yet)."""
    if s.watchdog is None or s.watchdog_outage is not None:
        return None
    return s.watchdog if now - s.watchdog > WATCHDOG_GAP else None


def tick_missing(s: ClockState, now: datetime, tz: ZoneInfo) -> str | None:
    """Today's local date when no tick ran by 05:00 (a tick was seen before; not told yet)."""
    local = now.astimezone(tz)
    if s.tick is None or s.tick_outage is not None or local.time() < TICK_BY:
        return None
    return None if s.tick.astimezone(tz).date() >= local.date() else local.date().isoformat()


def on_watchdog(s: ClockState, now: datetime, tz: ZoneInfo) -> tuple[ClockState, list[Event]]:
    """The 5-minute clock ran: its stamp, its own recovery, and the morning clock's check."""
    s = replace(s, watchdog=_later(s.watchdog, now))
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
    s = replace(s, tick=_later(s.tick, now))
    events: list[Event] = []
    if s.tick_outage is not None:
        was = s.tick_outage
        events.append(Event("selfwatch_ok", "tick", f"back:tick:{was}", outage=was))
        s = replace(s, tick_outage=None)
    since = watchdog_stopped(s, now)
    if since is not None:
        at, was = f"{since.astimezone(tz):%H:%M}", since.isoformat()
        events.append(Event("clock_stopped", "watchdog", f"watchdog:{was}", at, outage=was))
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


def decode(doc: dict[str, Any] | None) -> ClockState:
    d = doc or {}
    day = d.get("tick_outage")
    return ClockState(
        tick=_when(d.get("tick")),
        watchdog=_when(d.get("watchdog")),
        tick_outage=day if isinstance(day, str) and len(day) == 10 else None,
        watchdog_outage=_when(d.get("watchdog_outage")),
    )


def encode(s: ClockState) -> dict[str, Any]:
    def iso(at: datetime | None) -> str | None:
        return None if at is None else at.isoformat()

    return {
        "tick": iso(s.tick),
        "watchdog": iso(s.watchdog),
        "tick_outage": s.tick_outage,
        "watchdog_outage": iso(s.watchdog_outage),
    }


def merged(stored: ClockState, mine: ClockState) -> ClockState:
    """The later stamp of each clock; the stored outages (another process may have told one)."""
    return replace(
        stored, tick=_later(stored.tick, mine.tick), watchdog=_later(stored.watchdog, mine.watchdog)
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
            self.mine = await docs.transaction(fn)
            return self.mine, True
        except Exception as exc:  # noqa: BLE001 - the clocks run on memory meanwhile
            log.warning("selfwatch clocks not kept", extra={"error": type(exc).__name__})
            self.mine = change(self.mine)
            return self.mine, False

    async def read(self, docs: Docs) -> ClockState:
        try:
            return merged(decode(await docs.get(self._path)), self.mine)
        except Exception as exc:  # noqa: BLE001
            log.warning("selfwatch clocks unreadable", extra={"error": type(exc).__name__})
            return self.mine


__all__ = [
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
    "tick_missing",
    "undo",
    "watchdog_stopped",
]
