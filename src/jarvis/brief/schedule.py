# src/jarvis/brief/schedule.py
"""When is a brief due? Pure functions of (now, settings, time zone, today's record) — no I/O,
so the eval suite can pin every edge (catch-up, stale claims, DST, the day boundary).

Cloud Scheduler wakes the app every 30 minutes from 04:00 to 11:30; the app decides. A brief
missed at its time (cold start, outage) is made at the next tick up to CATCH_UP later. A brief
made while Google was failing (calendar or inbox "unavailable") is made again by the next
ticks, at most MAX_SECTION_RETRIES times; "not_connected" is never retried (only the owner can
fix it).
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from jarvis.brief.models import LATEST, BriefRecord, BriefSettings

CATCH_UP = timedelta(hours=4)
STALE_CLAIM = timedelta(minutes=10)  # a generation never legitimately takes this long
MAX_SECTION_RETRIES = 2
TICK_EVERY = timedelta(minutes=30)  # Cloud Scheduler: "0,30 4-11 * * *"
TICK_SLACK = timedelta(minutes=5)  # a tick may fire a little early or late


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


def has_unavailable_section(record: BriefRecord) -> bool:
    """A ready brief whose calendar or inbox could not be read (a Google error, not a missing
    link)."""
    if record.status != "ready" or record.data is None:
        return False
    st = record.data.sections_status
    return "unavailable" in (st.calendar, st.inbox)


def retryable(record: BriefRecord) -> bool:
    return has_unavailable_section(record) and record.retries < MAX_SECTION_RETRIES


def is_last_tick(now: datetime, settings: BriefSettings, tz: ZoneInfo) -> bool:
    """No later scheduler tick falls inside today's window: the next one (≈ now + 30 min) is
    past the catch-up end, or past the scheduler's last wake-up of the day (LATEST, 11:30)."""
    local = now.astimezone(tz)
    day = local.date()
    end = min(
        due_at(settings, day, tz) + CATCH_UP,
        datetime.combine(day, LATEST, tzinfo=tz) + TICK_EVERY,
    )
    return local + TICK_EVERY + TICK_SLACK > end


def is_due(
    *,
    now: datetime,
    settings: BriefSettings,
    tz: ZoneInfo,
    existing: BriefRecord | None = None,
) -> bool:
    """A scheduled generation should run now: enabled, inside the catch-up window, and today's
    brief is absent, failed, held by a claim nobody finished within STALE_CLAIM, or ready with
    an unavailable section and retries left."""
    if not settings.enabled or not in_delivery_window(now, settings, tz):
        return False
    if existing is None or existing.status == "failed":
        return True
    return claim_is_stale(existing, now) or retryable(existing)


__all__ = [
    "CATCH_UP",
    "MAX_SECTION_RETRIES",
    "STALE_CLAIM",
    "TICK_EVERY",
    "claim_is_stale",
    "due_at",
    "has_unavailable_section",
    "in_delivery_window",
    "is_due",
    "is_last_tick",
    "local_date",
    "retryable",
]
