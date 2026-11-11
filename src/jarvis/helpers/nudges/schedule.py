# src/jarvis/helpers/nudges/schedule.py
"""When each nudge is due (docs/plans/r11-free-helpers.md D3 "on time", D6). Pure code.

A stand-up or water nudge is due every N minutes after his window opens (the first one after he
has sat N minutes), strictly before the window closes; a focus or free-time nudge at each of his
times. On his days only. The 5-minute clock sends a slot in its first run at or after it (never
early); a slot more than `STALE` old is skipped (the clock was down: a stale nudge is noise).
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from jarvis.helpers.nudges.models import EVERY_KINDS, TIMES_KINDS, Nudge, clock

STALE = timedelta(minutes=30)
FALLBACK_TZ = "Asia/Kolkata"


def zone(tz: str) -> ZoneInfo:
    try:
        return ZoneInfo(tz)
    except (ZoneInfoNotFoundError, ValueError):
        return ZoneInfo(FALLBACK_TZ)


def _aware(at: datetime) -> datetime:
    return at if at.tzinfo is not None else at.replace(tzinfo=UTC)


def local_day(at: datetime, tz: str) -> date:
    return _aware(at).astimezone(zone(tz)).date()


def at_local(day: date, hhmm: str, tz: ZoneInfo) -> datetime:
    """`hhmm` on `day` in his zone, as a UTC time."""
    t = clock(hhmm)
    return datetime(day.year, day.month, day.day, t.hour, t.minute, tzinfo=tz).astimezone(UTC)


def slots(kind: str, n: Nudge, day: date, tz: ZoneInfo) -> list[datetime]:
    """Every due time of `kind` on `day` (UTC, sorted), or [] when it isn't one of his days."""
    if day.weekday() not in n.days:
        return []
    if kind in TIMES_KINDS:
        return [at_local(day, t, tz) for t in n.times]
    if kind not in EVERY_KINDS or n.every <= 0:
        return []
    start, end = at_local(day, n.start, tz), at_local(day, n.end, tz)
    step = timedelta(minutes=n.every)
    out, at = [], start + step
    while at < end:
        out.append(at)
        at += step
    return out


def due(times: list[datetime], now: datetime) -> datetime | None:
    """The latest time reached and not yet stale (never one still to come)."""
    now = _aware(now)
    reached = [t for t in times if t <= now and now - t <= STALE]
    return max(reached) if reached else None


def in_window(n: Nudge, now: datetime, tz: ZoneInfo) -> bool:
    here = _aware(now).astimezone(tz)
    if here.weekday() not in n.days:
        return False
    return clock(n.start) <= here.time() < clock(n.end)


__all__ = ["STALE", "at_local", "due", "in_window", "local_day", "slots", "zone"]
