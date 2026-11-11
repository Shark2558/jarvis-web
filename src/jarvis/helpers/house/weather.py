# src/jarvis/helpers/house/weather.py
"""Item 4, weather from Open-Meteo (docs/plans/r11-free-helpers.md D12; `helpers.sources`).

- `request_params`: his point rounded to 0.01 degrees (about 1 km; his district centre unless
  he typed his own), the hourly and daily fields D12 needs, his time zone, 2 days. His district's
  name never leaves JARVIS.
- `parse_forecast`: the JSON checked and bounded; a value outside any plausible range or not a
  number is left out (None), never trusted.
- `hits`: the first hour in the next 24 over each of his thresholds (rain in an hour, apparent
  temperature, gusts) and each day of the two with heavy rain in the day.
- `WeatherJob` (`weather_poll`, the 5-minute clock): for each configured owner with a place,
  whose "Weather and alerts" row isn't Never, only when due (every `weather_poll_minutes`; 15
  minutes after an outage) and never in a run that already read SACHET: one fetch (8 s at most),
  then one `weather_warning` per kind per day (a claim each; "Heavy rain likely around 15:00
  today: about 22 mm in an hour. Weather data by Open-Meteo.com."). The day's summary (the
  brief's line) and the outage, if any, are kept sealed in `outside/{uid}`.
Data CC BY 4.0: the panel and the brief carry "Weather data by Open-Meteo.com (CC BY 4.0)".
"""

from __future__ import annotations

import json
import math
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from jarvis.helpers.house import words
from jarvis.helpers.house.fetch import Fetcher, FetchError, OutsideSlot
from jarvis.helpers.house.guard import Counts, allowed
from jarvis.helpers.house.models import Outside, Thresholds, WeatherState, WeatherSummary
from jarvis.helpers.house.store import HouseStore, OutsideOff, OutsideStore
from jarvis.helpers.ports import HelperContext
from jarvis.helpers.sources import MAX_WEATHER_BYTES, OPEN_METEO_FORECAST_URL, OUTSIDE_TIMEOUT_S
from jarvis.logging import get_logger
from jarvis.notify.quiet import local

log = get_logger(__name__)

JOB = "weather_poll"
HOURLY = (
    "temperature_2m",
    "apparent_temperature",
    "precipitation",
    "precipitation_probability",
    "wind_gusts_10m",
)
DAILY = ("temperature_2m_max", "apparent_temperature_max", "precipitation_sum")
MAX_HOURS = 24 * 3
WINDOW = timedelta(hours=24)
RETRY_AFTER = timedelta(minutes=15)
SACHET_SAME_RUN = timedelta(seconds=90)  # SACHET was read in this clock run: weather waits
RAIN_LIKELY_MM, RAIN_LIKELY_PCT = 1.0, 50
BOUNDS = {
    "temperature_2m": (-60.0, 70.0),
    "apparent_temperature": (-80.0, 80.0),
    "precipitation": (0.0, 500.0),
    "precipitation_probability": (0.0, 100.0),
    "wind_gusts_10m": (0.0, 400.0),
    "temperature_2m_max": (-60.0, 70.0),
    "apparent_temperature_max": (-80.0, 80.0),
    "precipitation_sum": (0.0, 2000.0),
}


@dataclass(frozen=True)
class Hour:
    at: datetime  # local, aware
    temp: float | None
    feels: float | None
    precip: float | None
    prob: float | None
    gust: float | None


@dataclass(frozen=True)
class Day:
    day: date
    t_max: float | None
    rain: float | None


@dataclass(frozen=True)
class Forecast:
    hours: tuple[Hour, ...]
    days: tuple[Day, ...]


@dataclass(frozen=True)
class Hit:
    kind: str  # rain_hour | rain_day | heat | gust
    at: datetime  # local
    value: float


def request_params(point: tuple[float, float], tz: str) -> dict[str, str]:
    lat, lon = point
    return {
        "latitude": f"{lat:.2f}",
        "longitude": f"{lon:.2f}",
        "hourly": ",".join(HOURLY),
        "daily": ",".join(DAILY),
        "timezone": tz,
        "forecast_days": "2",
    }


def _num(values: Any, i: int, name: str) -> float | None:
    try:
        v = values[i]
    except (IndexError, TypeError, KeyError):
        return None
    if isinstance(v, bool) or not isinstance(v, int | float) or not math.isfinite(v):
        return None
    lo, hi = BOUNDS[name]
    return float(v) if lo <= v <= hi else None


def _times(block: Any, zone: ZoneInfo, *, daily: bool) -> list[datetime]:
    if not isinstance(block, dict) or not isinstance(block.get("time"), list):
        raise ValueError("Open-Meteo's answer has no times.")
    out = []
    for raw in block["time"][:MAX_HOURS]:
        if not isinstance(raw, str) or len(raw) > 20:
            raise ValueError("Open-Meteo's answer has a bad time.")
        parsed = datetime.fromisoformat(raw + ("T00:00" if daily else ""))
        out.append(parsed.replace(tzinfo=zone))
    return out


def parse_forecast(raw: bytes, tz: str) -> Forecast:
    try:
        data = json.loads(raw)
    except (ValueError, UnicodeDecodeError) as exc:
        raise ValueError("Open-Meteo's answer isn't JSON.") from exc
    if not isinstance(data, dict):
        raise ValueError("Open-Meteo's answer isn't a forecast.")
    zone = ZoneInfo(tz)
    hourly, daily = data.get("hourly"), data.get("daily")
    if not isinstance(hourly, dict):
        raise ValueError("Open-Meteo's answer has no hourly forecast.")
    hours = tuple(
        Hour(at, *(_num(hourly.get(n), i, n) for n in HOURLY))
        for i, at in enumerate(_times(hourly, zone, daily=False))
    )
    days: tuple[Day, ...] = ()
    if isinstance(daily, dict):
        days = tuple(
            Day(
                at.date(),
                _num(daily.get("temperature_2m_max"), i, "temperature_2m_max"),
                _num(daily.get("precipitation_sum"), i, "precipitation_sum"),
            )
            for i, at in enumerate(_times(daily, zone, daily=True))
        )
    return Forecast(hours, days)


def _first(hours: Sequence[Hour], kind: str, value: Any, top: float) -> Hit | None:
    for h in hours:
        v = value(h)
        if v is not None and v >= top:
            return Hit(kind, h.at, v)
    return None


def hits(fc: Forecast, th: Thresholds, now: datetime) -> list[Hit]:
    start = now.astimezone(fc.hours[0].at.tzinfo) if fc.hours else now
    window = [h for h in fc.hours if start - timedelta(hours=1) < h.at <= start + WINDOW]
    out = [
        _first(window, "rain_hour", lambda h: h.precip, th.rain_hour_mm),
        *(
            Hit("rain_day", datetime.combine(d.day, datetime.min.time(), start.tzinfo), d.rain)
            for d in fc.days
            if d.rain is not None
            and d.rain >= th.rain_day_mm
            and start.date() <= d.day <= (start + WINDOW).date()
        ),
        _first(window, "heat", lambda h: h.feels, th.feels_c),
        _first(window, "gust", lambda h: h.gust, th.gust_kmh),
    ]
    return [h for h in out if h is not None]


def summarize(fc: Forecast, now: datetime) -> WeatherSummary:
    zone = fc.hours[0].at.tzinfo if fc.hours else None
    here = now.astimezone(zone) if zone else now
    today = here.date()
    day = next((d for d in fc.days if d.day == today), None)
    t_max = day.t_max if day else None
    rest = [h for h in fc.hours if h.at.date() == today and h.at >= here - timedelta(hours=1)]
    rain = next(
        (h for h in rest if (h.precip or 0) >= RAIN_LIKELY_MM or (h.prob or 0) >= RAIN_LIKELY_PCT),
        None,
    )
    return WeatherSummary(
        day=today.isoformat(),
        t_max=t_max,
        rain_from=rain.at.strftime("%H:%M") if rain else None,
        at=now.isoformat(),
    )


def _due(state: WeatherState, now: datetime) -> bool:
    return state.next_at is None or now >= datetime.fromisoformat(state.next_at)


class WeatherJob:
    name = JOB
    budget_s = OUTSIDE_TIMEOUT_S + 1.0

    def __init__(
        self,
        ctx: HelperContext,
        outside: OutsideStore,
        store: HouseStore,
        fetcher: Fetcher,
        *,
        slot: OutsideSlot | None = None,
    ) -> None:
        self._ctx = ctx
        self._outside = outside
        self._store = store
        self._fetcher = fetcher
        self._slot = slot
        self._every = timedelta(minutes=ctx.settings.weather_poll_minutes)

    async def run(self, owners: Sequence[str]) -> dict[str, int]:
        """`owners` is ignored: the helpers serve the configured owners (`ctx.owners`)."""
        n = Counts()
        for uid in self._ctx.owners:
            try:
                if not await allowed(self._ctx, uid, "weather_now"):
                    n.add("skipped")
                    continue
                await self._owner(uid, n)
            except OutsideOff:
                n.add("off")
            except Exception as exc:  # noqa: BLE001 - one owner never blocks another
                log.warning("weather job failed for an owner", extra={"error": type(exc).__name__})
                n.add("failed")
        return n.done("sent", "retry", "unreachable", "skipped", "failed")

    async def _owner(self, uid: str, n: Counts) -> None:
        now = self._ctx.now()
        o = await self._outside.read(uid)
        point = o.place.point() if o.place is not None else None
        if o.place is None or point is None:
            n.add("no_place" if o.place is None else "no_point")
            return
        if not _due(o.weather, now):
            return
        read = o.sachet.checked_at
        spent = self._slot is not None and self._slot.used_within(SACHET_SAME_RUN.total_seconds())
        if spent or (read is not None and now - datetime.fromisoformat(read) < SACHET_SAME_RUN):
            n.add("deferred")  # SACHET used this run's outside time; next run
            return
        try:
            got = await self._fetcher.get(
                OPEN_METEO_FORECAST_URL,
                params=request_params(point, self._ctx.tz),
                cap=MAX_WEATHER_BYTES,
                timeout_s=OUTSIDE_TIMEOUT_S,
            )
            fc = parse_forecast(got.body, self._ctx.tz)
        except (FetchError, ValueError) as exc:
            log.warning("weather unreachable", extra={"error": type(exc).__name__})
            n.add("unreachable")
            await self._save(uid, o, lambda w: _failed(w, now))
            return
        for hit in hits(fc, o.thresholds, now):
            await self._warn(uid, hit, now, n)
        summary = summarize(fc, now)
        await self._save(uid, o, lambda w: _ok(w, now, self._every, summary))

    async def _warn(self, uid: str, hit: Hit, now: datetime, n: Counts) -> None:
        ident = f"{hit.kind}|{hit.at.date().isoformat()}"
        if not await self._store.claim(uid, "wx", ident, now):
            return
        today = local(now, self._ctx.tz).date()
        text = words.weather(hit.kind, hit.at, hit.value, today)
        got = await self._ctx.sender.send(uid, "weather_warning", text, due=now)
        if got.retry:
            await self._store.release(uid, "wx", ident)
            n.add("retry")
        else:
            n.add("sent" if got.counted else "dropped")

    async def _save(self, uid: str, seen: Outside, fn: Any) -> None:
        def apply(cur: Outside) -> Outside:
            if cur.place != seen.place:
                return cur  # his place changed meanwhile: this answer is for the old one
            return cur.model_copy(update={"weather": fn(cur.weather)})

        await self._outside.change(uid, apply)


def _failed(w: WeatherState, now: datetime) -> WeatherState:
    return w.model_copy(
        update={
            "checked_at": now.isoformat(),
            "next_at": (now + RETRY_AFTER).isoformat(),
            "fail_since": w.fail_since or now.isoformat(),
        }
    )


def _ok(w: WeatherState, now: datetime, every: timedelta, s: WeatherSummary) -> WeatherState:
    stamp = now.isoformat()
    return w.model_copy(
        update={
            "checked_at": stamp,
            "next_at": (now + every).isoformat(),
            "ok_at": stamp,
            "fail_since": None,
            "summary": s,
        }
    )


__all__ = [
    "JOB",
    "Day",
    "Forecast",
    "Hit",
    "Hour",
    "WeatherJob",
    "hits",
    "parse_forecast",
    "request_params",
    "summarize",
]
