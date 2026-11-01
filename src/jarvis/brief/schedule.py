# src/jarvis/brief/schedule.py
"""When is a brief due? Pure functions of (now, settings, time zone, today's record) — no I/O,
so the eval suite can pin every edge (catch-up, stale claims, DST, the day boundary).

Cloud Scheduler wakes the app every 30 minutes from 04:00 to 11:30; the app decides. A brief
missed at its time (cold start, outage) is made at the next tick up to CATCH_UP later.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from jarvis.brief.models import BriefRecord, BriefSettings

CATCH_UP = timedelta(hours=4)
STALE_CLAIM = timedelta(minutes=10)  # a generation never legitimately takes this long


def local_date(now: datetime, tz: ZoneInfo) -> date:
    return now.astimezone(tz).date()


def due_at(settings: BriefSettings, day: date, tz: ZoneInfo) -> datetime:
    """The scheduled local wall-clock time on `day` (DST-correct: ZoneInfo picks the offset)."""
    return datetime.combine(day, settings.at, tzinfo=tz)


def in_delivery_window(now: datetime, settings: BriefSettings, tz: ZoneInfo) -> bool:
    """now ∈ [scheduled time, scheduled time + CATCH_UP) on the local day of `now`."""
    start = due_at(settings, local_date(now, tz), tz)
    return start <= now.astimezone(tz) < start + CATCH_UP


def claim_is_stale(record: BriefRecord, now: datetime) -> bool:
    return record.status == "generating" and now - record.claimed_at > STALE_CLAIM


def is_due(
    *,
    now: datetime,
    settings: BriefSettings,
    tz: ZoneInfo,
    existing: BriefRecord | None = None,
) -> bool:
    """A scheduled generation should run now: enabled, inside the catch-up window, and today's
    brief is absent, failed, or held by a claim nobody finished within STALE_CLAIM."""
    if not settings.enabled or not in_delivery_window(now, settings, tz):
        return False
    if existing is None or existing.status == "failed":
        return True
    return claim_is_stale(existing, now)


__all__ = [
    "CATCH_UP",
    "STALE_CLAIM",
    "claim_is_stale",
    "due_at",
    "in_delivery_window",
    "is_due",
    "local_date",
]
