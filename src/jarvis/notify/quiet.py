# src/jarvis/notify/quiet.py
"""Quiet hours (R3 D10 rule 6): a local-time window that may cross midnight."""

from __future__ import annotations

from datetime import UTC, datetime, time
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from jarvis.notify.models import QuietHours

FALLBACK_TZ = "Asia/Kolkata"


def local(now: datetime, tz: str) -> datetime:
    """`now` in the owner's zone (a naive time is taken as UTC; an unknown zone falls back)."""
    aware = now if now.tzinfo is not None else now.replace(tzinfo=UTC)
    try:
        zone = ZoneInfo(tz)
    except (ZoneInfoNotFoundError, ValueError):
        zone = ZoneInfo(FALLBACK_TZ)
    return aware.astimezone(zone)


def _t(text: str) -> time:
    return time(int(text[:2]), int(text[3:5]))


def in_quiet(now: datetime, quiet: QuietHours, tz: str) -> bool:
    """True inside the window [start, end). Off, or start == end, is never quiet."""
    if not quiet.on:
        return False
    start, end = _t(quiet.start), _t(quiet.end)
    if start == end:
        return False
    at = local(now, tz).time().replace(second=0, microsecond=0)
    if start < end:
        return start <= at < end
    return at >= start or at < end


__all__ = ["in_quiet", "local"]
