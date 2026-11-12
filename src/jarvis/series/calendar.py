# src/jarvis/series/calendar.py
"""What the plans read from and write to Google Calendar (R11.1 O2, O2b; Layer 6). Only the
owner's primary calendar; every write is `sendUpdates=none` (no guests are ever on these events).

- `batch_events`: a batch's events, listed by its private marker (an exact-value filter).
- `other_events`: when the owner is busy between two times, from his own calendar entries (never
  the plan's own, never an all-day note, a declined invitation or an entry marked "free").
- `move_event`: one session to its new time, re-stamped so the event still reads as JARVIS wrote
  it (an Undo of the batch still removes it).
"""

from __future__ import annotations

from collections.abc import Collection
from datetime import datetime, tzinfo
from typing import Any

from jarvis.integrations.google import GoogleConnector
from jarvis.series.models import Move, ReplanRefused
from jarvis.tools.calendar_batch import BATCH_ID_KEY, BATCH_KEY, number_of, stamped
from jarvis.tools.google_calendar import EVENTS_URL

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


async def batch_events(conn: GoogleConnector, uid: str, batch: str) -> dict[int, dict[str, Any]]:
    """The batch's events now in the calendar, by item number."""
    params = {
        "privateExtendedProperty": f"{BATCH_ID_KEY}={batch}",
        "maxResults": PAGE,
        "showDeleted": "false",
    }
    items, _ = await _pages(conn, uid, params, MAX_PAGES)
    found: dict[int, dict[str, Any]] = {}
    for e in items:
        n = number_of(e, batch)
        if n is not None and e.get("status") != "cancelled":
            found.setdefault(n, e)
    return found


def _when(part: Any) -> datetime | None:
    try:
        return datetime.fromisoformat(str(part["dateTime"]).replace("Z", "+00:00"))
    except (KeyError, TypeError, ValueError):
        return None  # an all-day entry has no time: it never blocks a session


def _declined(e: dict[str, Any]) -> bool:
    return any(
        isinstance(a, dict) and a.get("self") and a.get("responseStatus") == "declined"
        for a in e.get("attendees") or []
    )


async def other_events(
    conn: GoogleConnector, uid: str, start: datetime, end: datetime, own: Collection[str]
) -> list[Span]:
    """The owner's busy times between `start` and `end`, without the events in `own`."""
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
    for e in items:
        if e.get("id") in own or e.get("status") == "cancelled" or _declined(e):
            continue
        if e.get("transparency") == "transparent":
            continue
        a, b = _when(e.get("start")), _when(e.get("end"))
        if a is not None and b is not None and b > a:
            busy.append((a, b))
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


__all__ = ["TOO_FULL", "batch_events", "move_event", "other_events"]
