# src/jarvis/coach/day.py
"""R8 rows 182 and 183 (docs/plans/r8-vision.md 4.7, D12; builder C): "Your day", the day strip.

The home camera's activity coach keeps, every 15 minutes and at a session's end, its segments
(kind, start, end: desk, away, phone, eating; `jarvis.coach.home.activity`). `strip()` joins every
kept activity tally of one person for one local day into one strip:

- each tally is laid over the day in the order it was kept (a later tally of the same session
  repeats and extends the earlier ones, so the newest says last);
- a stretch nobody covered between the day's first and last segment is `off` (the coach wasn't
  looking: the camera off, the laptop asleep);
- the totals (seconds of each kind) and the **longest sitting stretch**: desk, phone and eating
  in a row, broken only by `BREAK_S` or more away or off.

`DayService.day()` adds screen time from ActivityWatch (`jarvis.coach.ports.ScreenTime`, row 183:
per-program minutes and active time, never a window title) and is what `GET /v1/coach/day` and
the brief's line read. Only kinds, times and minutes: the day strip holds nothing else.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from datetime import date, datetime, timedelta, tzinfo
from typing import Any, Literal
from zoneinfo import ZoneInfo

from jarvis.coach.ports import ScreenTime, ScreenTimeDay
from jarvis.coach.store import CoachStore
from jarvis.coach.usecases import parse_tally
from jarvis.logging import get_logger

log = get_logger(__name__)

Kind = Literal["desk", "away", "phone", "eating", "off"]
KINDS: tuple[Kind, ...] = ("desk", "away", "phone", "eating", "off")
SITTING: frozenset[str] = frozenset({"desk", "phone", "eating"})
BREAK_S = 180  # away this long breaks a sitting stretch (a few minutes up and about)
TOP_PROGRAMS = 5
USE = "activity"
_CODE: dict[str, int] = {"desk": 1, "away": 2, "phone": 3, "eating": 4}
_NAME: dict[int, Kind] = {1: "desk", 2: "away", 3: "phone", 4: "eating"}


@dataclass(frozen=True)
class Stretch:
    kind: Kind
    start: int  # unix seconds
    end: int


@dataclass(frozen=True)
class ScreenView:
    state: str  # ok | not_installed | unreachable
    active_minutes: float = 0.0
    programs: tuple[tuple[str, float], ...] = ()  # the top few: (program, minutes)


@dataclass(frozen=True)
class DayStrip:
    day: str
    start: int  # the local day's bounds (unix seconds)
    end: int
    stretches: tuple[Stretch, ...] = ()
    totals: Mapping[str, int] | None = None  # seconds of each kind
    longest: Stretch | None = None  # the longest sitting stretch
    screen: ScreenView | None = None

    def as_json(self) -> dict[str, Any]:
        return {
            "day": self.day,
            "start": self.start,
            "end": self.end,
            "stretches": [{"kind": s.kind, "start": s.start, "end": s.end} for s in self.stretches],
            "totals": dict(self.totals or {}),
            "longest": None
            if self.longest is None
            else {"start": self.longest.start, "end": self.longest.end},
            "screen": None
            if self.screen is None
            else {
                "state": self.screen.state,
                "active_minutes": self.screen.active_minutes,
                "programs": [{"name": n, "minutes": m} for n, m in self.screen.programs],
            },
        }


def bounds(day: date, tz: tzinfo) -> tuple[int, int]:
    start = datetime(day.year, day.month, day.day, tzinfo=tz)
    return int(start.timestamp()), int((start + timedelta(days=1)).timestamp())


def _segments(items: Iterable[Mapping[str, Any]], who: str) -> list[tuple[str, int, int]]:
    """Every kept activity segment of `who`, oldest tally first (the newest is laid last)."""
    mine = [i for i in items if i.get("use") == USE and i.get("who") == who]
    mine.sort(key=lambda i: str(i.get("kept_at", "")))
    out: list[tuple[str, int, int]] = []
    for item in mine:
        tally = parse_tally(USE, item.get("tally"))
        if tally is None:
            continue  # a kept tally that no longer fits is left out, never repaired
        segs = getattr(tally, "segments", ())
        out.extend((s.kind, s.start, s.end) for s in segs if s.end > s.start)
    return out


def _paint(segments: list[tuple[str, int, int]], start: int, end: int) -> bytearray:
    second = bytearray(end - start)  # 0: nobody said
    for kind, a, b in segments:
        lo, hi = max(a, start), min(b, end)
        if hi > lo:
            second[lo - start : hi - start] = bytes([_CODE[kind]]) * (hi - lo)
    return second


def _runs(second: bytearray, start: int) -> list[Stretch]:
    out: list[Stretch] = []
    i, n = 0, len(second)
    while i < n:
        code = second[i]
        j = i
        while j < n and second[j] == code:
            j += 1
        if code:
            out.append(Stretch(_NAME[code], start + i, start + j))
        i = j
    return out


def _with_off(runs: list[Stretch]) -> list[Stretch]:
    out: list[Stretch] = []
    for r in runs:
        if out and r.start > out[-1].end:
            out.append(Stretch("off", out[-1].end, r.start))
        out.append(r)
    return out


def longest_sitting(stretches: Iterable[Stretch]) -> Stretch | None:
    best: Stretch | None = None
    cur_start: int | None = None
    cur_end = 0
    for s in stretches:
        if s.kind in SITTING:
            cur_start = s.start if cur_start is None else cur_start
            cur_end = s.end
        elif s.end - s.start >= BREAK_S and cur_start is not None:
            if best is None or cur_end - cur_start > best.end - best.start:
                best = Stretch("desk", cur_start, cur_end)
            cur_start = None
    if cur_start is not None and (best is None or cur_end - cur_start > best.end - best.start):
        best = Stretch("desk", cur_start, cur_end)
    return best


def strip(
    items: Iterable[Mapping[str, Any]],
    day: date,
    tz: tzinfo,
    *,
    who: str = "me",
    screen: ScreenView | None = None,
) -> DayStrip:
    start, end = bounds(day, tz)
    stretches = _with_off(_runs(_paint(_segments(items, who), start, end), start))
    totals: dict[str, int] = {k: 0 for k in KINDS}
    for s in stretches:
        totals[s.kind] += s.end - s.start
    return DayStrip(
        day=day.isoformat(),
        start=start,
        end=end,
        stretches=tuple(stretches),
        totals=totals,
        longest=longest_sitting(stretches),
        screen=screen,
    )


def screen_view(state: str, got: ScreenTimeDay | None) -> ScreenView:
    if state != "ok" or got is None:
        return ScreenView(state=state if state != "ok" else "unreachable")
    top = sorted(got.programs.items(), key=lambda p: (-p[1], p[0]))[:TOP_PROGRAMS]
    return ScreenView(
        state="ok",
        active_minutes=round(float(got.active_minutes), 1),
        programs=tuple((name, round(float(m), 1)) for name, m in top),
    )


class DayService:
    """The day strip for the routes and the brief (I1 builds it beside `app.state.coach`)."""

    def __init__(
        self,
        store: CoachStore,
        screen: ScreenTime | None,
        *,
        tz: str,
        now: Callable[[], datetime],
    ) -> None:
        self._store, self._screen, self._tz, self._now = store, screen, ZoneInfo(tz), now

    @property
    def zone(self) -> ZoneInfo:
        return self._tz

    def today(self) -> date:
        return self._now().astimezone(self._tz).date()

    async def screen(self, uid: str, day: date) -> ScreenView:
        if self._screen is None:
            return ScreenView(state="not_installed")
        try:
            state = await self._screen.state(uid)
            got = await self._screen.day(uid, day.isoformat()) if state == "ok" else None
        except Exception as exc:  # noqa: BLE001 - screen time never breaks the strip
            log.warning("screen time unreadable", extra={"error": type(exc).__name__})
            return ScreenView(state="unreachable")
        return screen_view(state, got)

    async def day(self, uid: str, day: date, *, who: str = "me") -> DayStrip:
        back = (self.today() - day).days
        if back < 0 or back >= self._store.keep_days:
            raise ValueError("a day he keeps")
        items = await self._store.list(uid, days=back + 1) if self._store.sealed else []
        return strip(items, day, self._tz, who=who, screen=await self.screen(uid, day))


def hm(seconds: int) -> str:
    """ "5 h 45 min", "25 min" (plain words for the brief and the pane)."""
    minutes = max(0, round(seconds / 60))
    h, m = divmod(minutes, 60)
    return f"{h} h {m:02d} min" if h else f"{m} min"


__all__ = [
    "BREAK_S",
    "KINDS",
    "DayService",
    "DayStrip",
    "ScreenView",
    "Stretch",
    "bounds",
    "hm",
    "longest_sitting",
    "screen_view",
    "strip",
]
