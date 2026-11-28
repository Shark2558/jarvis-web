# src/jarvis/coach/screentime.py
"""R8 row 183 (docs/plans/r8-vision.md 4.7, D5, ADR-53; builder C): screen time in the cloud.

`BridgeScreenTime` is the `jarvis.coach.ports.ScreenTime` port (and Vitals' `ScreenTimeReader`,
`jarvis.vitals.own`) over the home bridge's signed `GET /bridge/v1/screentime` (the
`activitywatch` plugin reads ActivityWatch on his laptop). It asks for one local day in his zone
and keeps the answer `CACHE_S` seconds, so the strip and Vitals ask the laptop once.

- `state(uid)`: "ok"; "not_installed" when ActivityWatch isn't there, the home kit isn't linked
  or its plugin isn't built yet (Vitals: "off until ActivityWatch is installed"); "unreachable"
  when the laptop is off or answers oddly (amber).
- `day(uid, day)`: per-program minutes and the active minutes, or None. A reply that doesn't fit
  (a name too long, minutes out of range, too many programs) is dropped, never repaired. There is
  no window title in it to drop: the bridge never sends one.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import date, datetime, time
from typing import Any
from zoneinfo import ZoneInfo

from jarvis.coach.ports import ScreenTimeDay
from jarvis.home.ports import SCREENTIME_ROUTE, HomeCaller, HomeRefused, HomeUnavailable
from jarvis.logging import get_logger

log = get_logger(__name__)

CACHE_S = 60.0
STATES = ("ok", "not_installed", "unreachable")
OFF_CODES = frozenset({"not_linked", "not_built"})
NAME_MAX = 40
PROGRAMS_MAX = 25
DAY_MINUTES = 1440.0


@dataclass(frozen=True)
class _Seen:
    at: float
    state: str
    got: ScreenTimeDay | None


def offset_minutes(day: date, tz: ZoneInfo) -> int:
    """His zone's offset from UTC at noon on `day`, in minutes east."""
    off = datetime.combine(day, time(12), tzinfo=tz).utcoffset()
    return int(off.total_seconds() // 60) if off is not None else 0


def _minutes(v: object) -> float | None:
    if isinstance(v, bool) or not isinstance(v, int | float):
        return None
    return float(v) if 0 <= v <= DAY_MINUTES else None


def parse_day(day: str, reply: Mapping[str, Any]) -> ScreenTimeDay | None:
    """The bridge's answer for `day`, or None when it doesn't fit."""
    active = _minutes(reply.get("active_minutes"))
    progs = reply.get("programs")
    if reply.get("day") != day or active is None or not isinstance(progs, list):
        return None
    if len(progs) > PROGRAMS_MAX:
        return None
    out: dict[str, float] = {}
    for p in progs:
        name = p.get("name") if isinstance(p, Mapping) else None
        minutes = _minutes(p.get("minutes")) if isinstance(p, Mapping) else None
        if not isinstance(name, str) or not 0 < len(name) <= NAME_MAX or minutes is None:
            return None
        if not name.isprintable():
            return None
        out[name] = out.get(name, 0.0) + minutes
    return ScreenTimeDay(day=day, active_minutes=active, programs=out)


class BridgeScreenTime:
    def __init__(
        self,
        caller: HomeCaller | None,
        *,
        tz: str,
        clock: Callable[[], float],
    ) -> None:
        self._caller, self._tz, self._clock = caller, ZoneInfo(tz), clock
        self._seen: dict[tuple[str, str], _Seen] = {}

    def _today(self) -> date:
        return datetime.fromtimestamp(self._clock(), self._tz).date()

    async def _ask(self, uid: str, day: str) -> _Seen:
        now = self._clock()
        hit = self._seen.get((uid, day))
        if hit is not None and now - hit.at < CACHE_S:
            return hit
        seen = _Seen(now, *await self._call(uid, day))
        self._seen = {k: v for k, v in self._seen.items() if now - v.at < CACHE_S}
        self._seen[(uid, day)] = seen
        return seen

    async def _call(self, uid: str, day: str) -> tuple[str, ScreenTimeDay | None]:
        if self._caller is None:
            return "not_installed", None
        query = {"day": day, "offset": str(offset_minutes(date.fromisoformat(day), self._tz))}
        try:
            reply = await self._caller.call(uid, "GET", SCREENTIME_ROUTE[1], query=query)
        except HomeRefused as exc:
            return ("not_installed" if exc.code in OFF_CODES else "unreachable"), None
        except HomeUnavailable:
            return "unreachable", None
        except Exception as exc:  # noqa: BLE001 - screen time is never worth an error
            log.warning(
                "screen time: the laptop's answer failed", extra={"error": type(exc).__name__}
            )
            return "unreachable", None
        state = reply.get("state")
        if state not in STATES:
            return "unreachable", None
        if state != "ok":
            return str(state), None
        got = parse_day(day, reply)
        return ("ok", got) if got is not None else ("unreachable", None)

    async def state(self, uid: str) -> str:
        return (await self._ask(uid, self._today().isoformat())).state

    async def day(self, uid: str, day: str) -> ScreenTimeDay | None:
        date.fromisoformat(day)  # a bad day is a ValueError, never a bridge call
        return (await self._ask(uid, day)).got


__all__ = ["CACHE_S", "BridgeScreenTime", "offset_minutes", "parse_day"]
