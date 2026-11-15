# src/jarvis/wardrobe/styling/outlook.py
"""R13 D14, plan review L4 (docs/plans/r13-wardrobe.md): tomorrow's weather, in C's OWN document.

R11's stored weather is `extra="forbid"` and keeps today only, so C adds nothing to R11's
documents (a rollback to v14.0.2 would find them unreadable) and edits no R11 file. Instead:
- his place is read, read-only and late, from R11 B's `OutsideStore` (`ctx.outside()`, the
  `house` part's service); C runs only while R11's weather is on for him (Helpers and weather on,
  his place set): his consent there is the consent here;
- the `outfit_clock` fetches at most twice a day, once from 05:00 and once from 18:00 his time
  (`slot_of`; a failure waits an hour), with R11's own `request_params`, fetcher and
  `parse_forecast` (Open-Meteo, no key; no new outside service);
- today's and tomorrow's summary (the highest temperature and the hours rain is likely, by R11's
  own thresholds) is kept sealed in `wardrobe_outlook/{uid}` (overwritten each time);
- `weather(uid, day, span)` says what a look assumes: "Weather for your home area: rain likely
  from 15:00." or, with Helpers off, no place or nothing kept for that day, "Weather unknown: I
  assumed indoors." (STY-07).
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, tzinfo
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from jarvis.helpers.house.fetch import Fetcher, FetchError
from jarvis.helpers.house.weather import (
    RAIN_LIKELY_MM,
    RAIN_LIKELY_PCT,
    Forecast,
    parse_forecast,
    request_params,
)
from jarvis.helpers.sources import MAX_WEATHER_BYTES, OPEN_METEO_FORECAST_URL, OUTSIDE_TIMEOUT_S
from jarvis.logging import get_logger
from jarvis.wardrobe.ports import WardrobeContext
from jarvis.wardrobe.styling.rules import Rules
from jarvis.wardrobe.styling.sealed import Off, SealedDoc, Unreadable
from jarvis.wardrobe.styling.texts import WEATHER_UNKNOWN

log = get_logger(__name__)
MORNING, EVENING = time(5, 0), time(18, 0)
RETRY = timedelta(minutes=60)
HOME = "Weather for your home area"


class _M(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class DayOutlook(_M):
    day: date
    t_max: float | None = None
    rain_hours: tuple[int, ...] = Field(default=(), max_length=24)


class OutlookDoc(_M):
    days: tuple[DayOutlook, ...] = Field(default=(), max_length=2)
    slot: str | None = Field(default=None, max_length=16)  # "2026-11-16-am": its fetch is done
    place: str | None = Field(default=None, max_length=16)  # a hash of the point it is for
    fetched_at: datetime | None = None
    failed_at: datetime | None = None


@dataclass(frozen=True)
class Weather:
    known: bool
    rain: bool | None = None
    rain_from: str | None = None
    hot: bool = False
    cold: bool = False
    words: str = WEATHER_UNKNOWN


UNKNOWN = Weather(False)


def slot_of(now: datetime, zone: tzinfo) -> str:
    """The fetch this moment belongs to: from 05:00 "am", from 18:00 "pm" (before 05:00: the
    evening before's)."""
    local = now.astimezone(zone)
    if local.time() < MORNING:
        return f"{(local.date() - timedelta(days=1)).isoformat()}-pm"
    return f"{local.date().isoformat()}-{'am' if local.time() < EVENING else 'pm'}"


def summary(fc: Forecast, day: date) -> DayOutlook:
    found = next((d for d in fc.days if d.day == day), None)
    rain = tuple(
        sorted(
            {
                h.at.hour
                for h in fc.hours
                if h.at.date() == day
                and ((h.precip or 0) >= RAIN_LIKELY_MM or (h.prob or 0) >= RAIN_LIKELY_PCT)
            }
        )
    )
    return DayOutlook(day=day, t_max=found.t_max if found else None, rain_hours=rain)


def _place_key(point: tuple[float, float]) -> str:
    return hashlib.sha256(f"{point[0]:.2f},{point[1]:.2f}".encode()).hexdigest()[:16]


def _rain_in(d: DayOutlook, span: tuple[datetime, datetime] | None, zone: tzinfo) -> list[int]:
    if span is None:
        return list(d.rain_hours)
    start, end = span
    out = []
    for h in d.rain_hours:
        at = datetime.combine(d.day, time(h), tzinfo=zone)
        if start - timedelta(hours=1) < at < end:
            out.append(h)
    return out


class Outlook:
    def __init__(
        self, ctx: WardrobeContext, fetcher: Fetcher | None, sealed: SealedDoc[OutlookDoc], rules: Rules
    ) -> None:  # fmt: skip
        self._ctx, self._fetcher, self.sealed, self._rules = ctx, fetcher, sealed, rules

    async def point(self, uid: str) -> tuple[float, float] | None:
        """His R11 place, while R11's weather is on for him; else None."""
        s = self._ctx.s
        if not (s.helpers_enabled and s.weather_enabled):
            return None
        out: Any = self._ctx.outside()
        if out is None:
            return None
        try:
            o = await out.read(uid)
        except Exception as exc:  # noqa: BLE001 - R11 off for him, or its key missing: unknown
            log.info("outfits: no place for the weather", extra={"error": type(exc).__name__})
            return None
        place = getattr(o, "place", None)
        point = place.point() if place is not None else None
        return point if isinstance(point, tuple) else None

    async def refresh(self, uid: str, now: datetime, zone: tzinfo) -> str:
        """One fetch when due (at most twice a day); its result word for the clock's counts."""
        point = await self.point(uid)
        if point is None or self._fetcher is None or not self.sealed.available:
            return "off"
        doc = await self.sealed.read(uid)
        slot, place = slot_of(now, zone), _place_key(point)
        if doc.place == place and (
            doc.slot == slot or (doc.failed_at and now - doc.failed_at < RETRY)
        ):  # noqa: E501
            return "not_due"
        tz = getattr(zone, "key", str(zone))
        try:
            got = await self._fetcher.get(
                OPEN_METEO_FORECAST_URL,
                params=request_params(point, tz),
                cap=MAX_WEATHER_BYTES,
                timeout_s=OUTSIDE_TIMEOUT_S,
            )
            fc = parse_forecast(got.body, tz)
        except (FetchError, ValueError) as exc:
            log.warning("outfits: weather not read", extra={"error": type(exc).__name__})
            failed = doc.model_copy(update={"failed_at": now, "place": place})
            await self.sealed.change(uid, lambda _: failed)
            return "failed"
        today = now.astimezone(zone).date()
        days = (summary(fc, today), summary(fc, today + timedelta(days=1)))
        fresh = OutlookDoc(days=days, slot=slot, place=place, fetched_at=now)
        await self.sealed.change(uid, lambda _: fresh)
        return "fetched"

    async def weather(
        self, uid: str, day: date, span: tuple[datetime, datetime] | None, zone: tzinfo
    ) -> Weather:
        if await self.point(uid) is None:
            return UNKNOWN
        try:
            doc = await self.sealed.read(uid)
        except (Off, Unreadable):
            return UNKNOWN
        d = next((x for x in doc.days if x.day == day), None)
        if d is None:
            return UNKNOWN
        hours = _rain_in(d, span, zone)
        hot = d.t_max is not None and d.t_max >= self._rules.hot_c
        cold = d.t_max is not None and d.t_max <= self._rules.cold_c
        if hours:
            at = f"{hours[0]:02d}:00"
            return Weather(True, True, at, hot, cold, f"{HOME}: rain likely from {at}.")
        up = f", up to {d.t_max:.0f}°C" if d.t_max is not None else ""
        return Weather(True, False, None, hot, cold, f"{HOME}: no rain expected{up}.")


__all__ = [
    "HOME",
    "UNKNOWN",
    "DayOutlook",
    "Outlook",
    "OutlookDoc",
    "Weather",
    "slot_of",
    "summary",
]
