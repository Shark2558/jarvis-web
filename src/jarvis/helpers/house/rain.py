# src/jarvis/helpers/house/rain.py
"""Part B's rain hint for Part C's free-time pick (docs/plans/r11-free-helpers.md D12; R11 I1).

`RainHint.rain_likely(uid, start, end)` reads his sealed weather summary (the `weather_poll`
job keeps "rain likely from HH:MM today" from Open-Meteo's hourly forecast) and answers:

- True: rain is likely to start before `end` today (the free-time gap);
- False: today's summary has no rain from now on, or it starts after the gap;
- None (unknown, so Part C applies no rain rule): no keyring, his place isn't set, no summary
  yet, a summary older than `STALE_AFTER` or of another day, or a gap on another day.

Exposed as `services["rain"]`; the wiring hands it to Part C late (`HelperContext.rain`). It
reads only JARVIS's own sealed summary: no outside call, nothing logged but a class name.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from jarvis.helpers.house.store import OutsideOff, OutsideStore
from jarvis.logging import get_logger

log = get_logger(__name__)

STALE_AFTER = timedelta(hours=3)  # the poll runs every hour: three missed polls = unknown


class RainHint:
    def __init__(self, outside: OutsideStore, *, tz: str, now: Callable[[], datetime]) -> None:
        self._outside = outside
        self._zone = ZoneInfo(tz)
        self._now = now

    async def rain_likely(self, uid: str, start: datetime, end: datetime) -> bool | None:
        try:
            o = await self._outside.read(uid)
        except OutsideOff:
            return None
        except Exception as exc:  # noqa: BLE001 - unknown weather: no rain rule
            log.warning("rain hint unreadable", extra={"error": type(exc).__name__})
            return None
        s = o.weather.summary
        if o.place is None or s is None:
            return None
        try:
            day, at = date.fromisoformat(s.day), datetime.fromisoformat(s.at)
        except ValueError:
            return None
        if self._now() - at > STALE_AFTER or start.astimezone(self._zone).date() != day:
            return None
        if s.rain_from is None:
            return False
        hh, mm = (int(x) for x in s.rain_from.split(":"))
        return datetime.combine(day, time(hh, mm), self._zone) < end


__all__ = ["STALE_AFTER", "RainHint"]
