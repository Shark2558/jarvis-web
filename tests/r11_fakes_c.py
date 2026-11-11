# tests/r11_fakes_c.py -- R11 Part C's own fakes (docs/plans/r11-free-helpers.md, Part C: nudges).
# Shared by tests/test_r11_c_*.py and evals/r11_helpers/nudges.py. Imports I0's shared fakes
# (`r11_fakes`), never copies them. Made-up data only: no real names, places or numbers.
#
# - `FakeCalendar`: the `CalendarSource` port; events by local day, counts its fetches.
# - `FakeRain`: the `RainSource` port; rainy local days.
# - `FakePending`: a `PendingSource` with fixed items (what Part A's sources give).
# - `keyring()`: a test keyring (a fixed, obviously fake root).
# - `part(...)`: Part C built on I0's `ctx` fakes, with the fakes above; returns a `Rig`.
# - `run_tool(...)`: a Part C tool run as the gateway runs it (the owner's tool context).
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, date, datetime
from typing import Any
from zoneinfo import ZoneInfo

from r11_fakes import UID, Clock, FakeNotifier, ctx

from jarvis.helpers.ports import HelperContext, HelperPart, PendingItem
from jarvis.keyring import Keyring
from jarvis.storage.docs import MemoryDocs
from jarvis.tools.base import Tool
from jarvis.tools.context import tool_context

IST = ZoneInfo("Asia/Kolkata")
FAKE_ROOT = bytes(range(101, 133))  # 32 distinct bytes: a test key, never a real one


def keyring() -> Keyring:
    return Keyring(FAKE_ROOT)


def at_ist(day: date, hhmm: str) -> datetime:
    h, m = (int(x) for x in hhmm.split(":"))
    return datetime(day.year, day.month, day.day, h, m, tzinfo=IST).astimezone(UTC)


@dataclass(frozen=True)
class Planned:
    """One event in the fake calendar, in IST on its day."""

    title: str
    start: str
    end: str
    own: bool = True
    ident: str = ""


@dataclass
class FakeCalendar:
    days: dict[date, list[Planned]] = field(default_factory=dict)
    every_day: list[Planned] = field(default_factory=list)
    fail: bool = False
    fetches: int = 0

    async def events(self, uid: str, start: datetime, end: datetime) -> list[Any]:
        from jarvis.helpers.nudges.calendar import CalEvent

        self.fetches += 1
        if self.fail:
            raise RuntimeError("calendar down")
        day = start.astimezone(IST).date()
        out = []
        for i, p in enumerate([*self.every_day, *self.days.get(day, [])]):
            out.append(
                CalEvent(
                    key=f"{day.isoformat()}-{p.ident or i}",
                    title=p.title,
                    start=at_ist(day, p.start),
                    end=at_ist(day, p.end),
                    own=p.own,
                )
            )
        return [e for e in out if e.end > start and e.start < end]


@dataclass
class FakeRain:
    rainy: set[date] = field(default_factory=set)
    unknown: bool = False

    async def rain_likely(self, uid: str, start: datetime, end: datetime) -> bool | None:
        if self.unknown:
            return None
        return start.astimezone(IST).date() in self.rainy


@dataclass
class FakePending:
    items: list[PendingItem] = field(default_factory=list)
    name: str = "today"
    fail: bool = False

    async def pending(self, uid: str, now: datetime) -> Sequence[PendingItem]:
        if self.fail:
            raise RuntimeError("pending down")
        return list(self.items)


@dataclass
class Rig:
    part: HelperPart
    ctx: HelperContext
    notifier: FakeNotifier
    docs: MemoryDocs
    clock: Clock
    calendar: FakeCalendar
    rain: FakeRain
    pending: FakePending

    def tool(self, name: str) -> Tool:
        return next(t for t in self.part.tools if t.name == name)

    def job(self, name: str) -> Any:
        return next(j for j in self.part.clock_jobs if j.name == name)

    def rebuilt(self) -> Rig:
        """A restart: a fresh part (new caches) on the same documents, clock and fakes."""
        from jarvis.helpers.nudges import part as nudges_part

        fresh = nudges_part.build(self.ctx, calendar=self.calendar, rain=self.rain)
        return replace(self, part=fresh)


def part(
    *,
    sealed: bool = True,
    calendar: FakeCalendar | None = None,
    rain: FakeRain | None = None,
    pending: FakePending | None = None,
    policy: bool = True,
    at: datetime | None = None,
    **over: Any,
) -> Rig:
    """`over`: Settings fields only (I0's `ctx` passes them to Settings)."""
    from jarvis.helpers.nudges import part as nudges_part

    pend = pending or FakePending()
    c, notifier, docs, clock = ctx("nudges", pending=(pend,), **over)
    notifier.policy = policy  # the real policy: quiet hours drop a nudge, the day rings it
    if at is not None:
        clock.at = at
    if sealed:
        c = replace(c, keyring=keyring())
    cal, wet = calendar or FakeCalendar(), rain or FakeRain()
    built = nudges_part.build(c, calendar=cal, rain=wet)
    return Rig(built, c, notifier, docs, clock, cal, wet, pend)


async def run_tool(rig: Rig, name: str, **args: Any) -> Any:
    tool = rig.tool(name)
    tool.validate(args)
    with tool_context(f"{UID}:s1"):
        return await tool.run(args)


__all__ = [
    "FAKE_ROOT",
    "IST",
    "FakeCalendar",
    "FakePending",
    "FakeRain",
    "Planned",
    "Rig",
    "at_ist",
    "keyring",
    "part",
    "run_tool",
]
