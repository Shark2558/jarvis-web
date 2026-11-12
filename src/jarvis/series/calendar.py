# src/jarvis/series/calendar.py
"""What the plans read from and write to Google Calendar (R11.1 O2, O2b; Layer 6). Only the
owner's primary calendar; every write is `sendUpdates=none` (no guests are ever on these events).

- `batch_events` / `batch_listing`: a batch's events, listed by its private marker (an exact-value
  filter), and whether the listing held all of them (a cut listing is logged and never taken to
  mean an event was deleted).
- `other_events`: when the owner is busy between two times, from his own calendar entries
  (never the events that are moving, a declined invitation or an entry marked "free"). An
  all-day entry marked busy blocks its whole days; an entry whose time can't be read is
  skipped and logged.
- `move_event`: one session to its new time, re-stamped so the event still reads as JARVIS wrote
  it (an Undo of the batch still removes it).
"""

from __future__ import annotations

from collections.abc import Collection
from datetime import date, datetime, time, tzinfo
from typing import Any

from jarvis.integrations.google import GoogleConnector
from jarvis.logging import get_logger
from jarvis.series.models import Move, ReplanRefused
from jarvis.tools.calendar_batch import BATCH_ID_KEY, BATCH_KEY, number_of, stamped
from jarvis.tools.google_calendar import EVENTS_URL

log = get_logger(__name__)

PAGE = 250
MAX_PAGES = 4  # a batch's events: at most 1,000
BUSY_PAGES = 8  # other entries while a re-plan looks ahead: at most 2,000
TOO_FULL = "Your calendar is too full for me to re-plan safely over that time, Sir."
Span = tuple[datetime, datetime]


async def _pages(
    conn: GoogleConnector, uid: str, params: dict[str, Any], pages: int
) -> tuple[list[dict[str, Any]], bool]:
    """(the items of up to `pages` pages, whether more were left)."""
    items: list[dict[str, Any]] = []
    for _ in range(pages):
        got = await conn.request(uid, "GET", EVENTS_URL, params=params)
        data = got if isinstance(got, dict) else {}
        items += [e for e in data.get("items") or [] if isinstance(e, dict)]
        token = data.get("nextPageToken")
        if not token:
            return items, False
        params = {**params, "pageToken": token}
    return items, True


async def batch_listing(
    conn: GoogleConnector, uid: str, batch: str
) -> tuple[dict[int, dict[str, Any]], bool]:
    """(the batch's events now in the calendar by item number, whether that is all of them)."""
    params = {
        "privateExtendedProperty": f"{BATCH_ID_KEY}={batch}",
        "maxResults": PAGE,
        "showDeleted": "false",
    }
    items, more = await _pages(conn, uid, params, MAX_PAGES)
    if more:
        log.warning("a batch listing was cut at its page limit", extra={"pages": MAX_PAGES})
    found: dict[int, dict[str, Any]] = {}
    for e in items:
        n = number_of(e, batch)
        if n is not None and e.get("status") != "cancelled":
            found.setdefault(n, e)
    return found, not more


async def batch_events(conn: GoogleConnector, uid: str, batch: str) -> dict[int, dict[str, Any]]:
    """The batch's events now in the calendar, by item number."""
    return (await batch_listing(conn, uid, batch))[0]


def _when(part: Any) -> datetime | None:
    try:
        return datetime.fromisoformat(str(part["dateTime"]).replace("Z", "+00:00"))
    except (KeyError, TypeError, ValueError):
        return None


def _day(part: Any, tz: tzinfo) -> datetime | None:
    """An all-day entry's day boundary (its `date`, at midnight in the owner's zone)."""
    try:
        return datetime.combine(date.fromisoformat(str(part["date"])), time(0), tzinfo=tz)
    except (KeyError, TypeError, ValueError):
        return None


def _span(e: dict[str, Any], tz: tzinfo) -> tuple[datetime | None, datetime | None]:
    start, end = e.get("start"), e.get("end")
    if isinstance(start, dict) and "date" in start and "dateTime" not in start:
        return _day(start, tz), _day(end, tz)  # a busy all-day entry blocks its days
    return _when(start), _when(end)


def _declined(e: dict[str, Any]) -> bool:
    return any(
        isinstance(a, dict) and a.get("self") and a.get("responseStatus") == "declined"
        for a in e.get("attendees") or []
    )


async def other_events(
    conn: GoogleConnector,
    uid: str,
    start: datetime,
    end: datetime,
    own: Collection[str],
    tz: tzinfo,
) -> list[Span]:
    """The owner's busy times between `start` and `end`, without the events in `own` (the
    sessions that move). Everything else counts, the plan's other sessions at their real
    times included."""
    params = {
        "timeMin": start.isoformat(),
        "timeMax": end.isoformat(),
        "singleEvents": "true",
        "orderBy": "startTime",
        "maxResults": PAGE,
    }
    items, more = await _pages(conn, uid, params, BUSY_PAGES)
    if more:
        raise ReplanRefused(TOO_FULL)
    busy: list[Span] = []
    unread = 0
    for e in items:
        if e.get("id") in own or e.get("status") == "cancelled" or _declined(e):
            continue
        if e.get("transparency") == "transparent":
            continue
        a, b = _span(e, tz)
        if a is not None and b is not None and b > a:
            busy.append((a, b))
        else:
            unread += 1
    if unread:
        log.warning("calendar entries whose time could not be read", extra={"count": unread})
    return busy


async def move_event(
    conn: GoogleConnector, uid: str, event: dict[str, Any], move: Move, tz: tzinfo
) -> None:
    """Patch one event to its new time. The batch markers are kept and the fingerprint is made
    again over the new time, with every private property the event already has."""
    zone = getattr(tz, "key", None)
    body: dict[str, Any] = {
        "start": {"dateTime": move.start.astimezone(tz).isoformat()},
        "end": {"dateTime": move.end.astimezone(tz).isoformat()},
    }
    if zone:
        body["start"]["timeZone"] = body["end"]["timeZone"] = zone
    mark = str(((event.get("extendedProperties") or {}).get("private") or {}).get(BATCH_KEY) or "")
    batch, _, n = mark.rpartition(":")
    if batch and n.isdigit():
        body = stamped(body, batch, int(n), event)
    await conn.request(
        uid, "PATCH", f"{EVENTS_URL}/{event['id']}", params={"sendUpdates": "none"}, json=body
    )


__all__ = ["TOO_FULL", "batch_events", "batch_listing", "move_event", "other_events"]
