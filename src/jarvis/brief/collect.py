# src/jarvis/brief/collect.py
"""Collect today's facts for the brief (Layer 6 → 7): fixed, read-only GETs through
`GoogleConnector.request` plus a count of the owner's waiting approvals.

No model is in the loop, so the tool gateway (which polices model-initiated calls) is not used;
the service writes the audit entry. Everything other people wrote (titles, locations, names,
subjects) is flattened to one capped line by `one_line`; mail snippets are returned separately
and only ever reach the AI summary. One section failing never fails the others.

To-do (slice 10 C): open Google Tasks due on or before today across the owner's lists (≤ 10
lists), only when the optional Tasks scope is granted — otherwise "not_granted" and no call.
"""

from __future__ import annotations

import asyncio
import html
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from email.utils import parseaddr, parsedate_to_datetime
from typing import Any, TypeVar
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from jarvis.brief.models import (
    BriefData,
    BriefEvent,
    CalendarSection,
    FreeBlock,
    InboxItem,
    InboxSection,
    JarvisSection,
    SectionsStatus,
    SectionState,
    TodoItem,
    TodoSection,
    TodoState,
)
from jarvis.core.guardrails import ApprovalStore
from jarvis.integrations.google import GoogleAPIError, GoogleConnector, GoogleNotConnected
from jarvis.logging import get_logger
from jarvis.tools.addresses import loose_address
from jarvis.tools.card import one_line
from jarvis.tools.gmail import MESSAGES_URL
from jarvis.tools.gmail_mime import headers_of
from jarvis.tools.google_calendar import EVENTS_URL, TZ_URL, compute_free_slots
from jarvis.tools.tasks_api import TaskList, TasksClient, TasksNotGranted, date_of

log = get_logger(__name__)
T = TypeVar("T")

INBOX_QUERY = "is:unread in:inbox category:primary newer_than:1d"
MAX_EVENTS = 50
MAX_MAIL = 10
TITLE_LIMIT = 120
LOCATION_LIMIT = 80
NAME_LIMIT = 80
SUBJECT_LIMIT = 120
SNIPPET_LIMIT = 200
MAX_TODO = 10
TODO_LIST_LIMIT = 60
FREE_MIN = timedelta(minutes=30)
WORK_FROM, WORK_TO = time(9, 0), time(18, 0)
META_HEADERS = ("From", "Subject", "Date")
_MESSAGE_ID = re.compile(r"[A-Za-z0-9_-]{1,128}")


@dataclass(frozen=True)
class Collected:
    data: BriefData
    snippets: tuple[str, ...] = ()  # aligned with data.inbox.items; for the AI only


# ---- calendar (pure) --------------------------------------------------------------------------


def _when(part: Any, tz: ZoneInfo) -> datetime | date | None:
    if not isinstance(part, dict):
        return None
    try:
        if part.get("dateTime"):
            raw = str(part["dateTime"]).replace("Z", "+00:00")
            return datetime.fromisoformat(raw).astimezone(tz)
        if part.get("date"):
            return date.fromisoformat(str(part["date"]))
    except ValueError:
        return None
    return None


def _declined(e: dict[str, Any]) -> bool:
    return any(
        isinstance(a, dict) and a.get("self") and a.get("responseStatus") == "declined"
        for a in e.get("attendees") or []
    )


def _hhmm(d: datetime) -> str:
    return d.strftime("%H:%M")


def _event(
    e: dict[str, Any],
    span: tuple[datetime, datetime] | None,
    bounds: tuple[datetime, datetime],
    overlaps: tuple[str, ...] = (),
) -> BriefEvent:
    """`span` None = all-day. `bounds` = the local day the event is listed under."""
    attendees = [a for a in e.get("attendees") or [] if isinstance(a, dict)]
    common: dict[str, Any] = {
        "title": one_line(e.get("summary"), TITLE_LIMIT) or "(no title)",
        "location": one_line(e.get("location"), LOCATION_LIMIT) or None,
        "attendees": len(attendees),
        "has_video": bool(e.get("hangoutLink") or e.get("conferenceData")),
        "overlaps_with": overlaps,
    }
    if span is None:
        return BriefEvent(start="", end="", all_day=True, **common)
    s, en = span
    return BriefEvent(
        start=_hhmm(s),
        end=_hhmm(en),
        starts_earlier=s < bounds[0],
        ends_later=en > bounds[1],
        **common,
    )


Timed = tuple[datetime, datetime, dict[str, Any]]


def _split(
    items: list[Any], tz: ZoneInfo, day: date
) -> tuple[list[dict[str, Any]], list[Timed], list[Timed]]:
    """→ (all-day events covering `day`, timed events touching `day`, timed events starting
    the next day). Cancelled events and events the owner declined are dropped."""
    d0 = datetime.combine(day, time(0), tzinfo=tz)
    d1 = datetime.combine(day + timedelta(days=1), time(0), tzinfo=tz)
    d2 = datetime.combine(day + timedelta(days=2), time(0), tzinfo=tz)
    all_days: list[dict[str, Any]] = []
    today: list[Timed] = []
    tomorrow: list[Timed] = []
    for e in items[:MAX_EVENTS]:
        if not isinstance(e, dict) or e.get("status") == "cancelled" or _declined(e):
            continue
        s, en = _when(e.get("start"), tz), _when(e.get("end"), tz)
        if isinstance(s, datetime):
            en = en if isinstance(en, datetime) and en >= s else s
            if s < d1 and (en > d0 or s >= d0):
                today.append((s, en, e))
            elif d1 <= s < d2:
                tomorrow.append((s, en, e))
        elif isinstance(s, date):
            last = en if isinstance(en, date) and en > s else s + timedelta(days=1)
            if s <= day < last:
                all_days.append(e)
    return all_days, sorted(today, key=lambda t: t[0]), sorted(tomorrow, key=lambda t: t[0])


def _overlaps(timed: list[Timed]) -> tuple[list[tuple[str, ...]], int]:
    titles = [one_line(e.get("summary"), TITLE_LIMIT) or "(no title)" for _, _, e in timed]
    found: list[list[str]] = [[] for _ in timed]
    pairs = 0
    for i, (s1, e1, _) in enumerate(timed):
        for j in range(i + 1, len(timed)):
            s2, e2, _ = timed[j]
            if s1 < e2 and s2 < e1:
                found[i].append(titles[j])
                found[j].append(titles[i])
                pairs += 1
    return [tuple(f) for f in found], pairs


def _free_blocks(timed: list[Timed], tz: ZoneInfo, day: date) -> tuple[FreeBlock, ...]:
    d0 = datetime.combine(day, time(0), tzinfo=tz)
    d1 = datetime.combine(day + timedelta(days=1), time(0), tzinfo=tz)
    busy = sorted((s, en) for s, en, e in timed if e.get("transparency") != "transparent")
    slots = compute_free_slots(d0, d1, busy, FREE_MIN, WORK_FROM, WORK_TO)
    return tuple(
        FreeBlock(start=_hhmm(a), end=_hhmm(b), minutes=int((b - a).total_seconds() // 60))
        for a, b in slots
    )


def shape_calendar(items: list[Any], tz: ZoneInfo, day: date) -> CalendarSection:
    all_days, today, tomorrow = _split(items, tz, day)
    d0 = datetime.combine(day, time(0), tzinfo=tz)
    d1 = d0 + timedelta(days=1)
    t_bounds = (
        datetime.combine(day + timedelta(days=1), time(0), tzinfo=tz),
        datetime.combine(day + timedelta(days=2), time(0), tzinfo=tz),
    )
    overlaps, clashes = _overlaps(today)
    events = [_event(e, None, (d0, d1)) for e in all_days] + [
        _event(e, (s, en), (d0, d1), overlaps[i]) for i, (s, en, e) in enumerate(today)
    ]
    first = next(iter(tomorrow), None)
    return CalendarSection(
        today=tuple(events),
        clashes=clashes,
        free_blocks=_free_blocks(today, tz, day),
        tomorrow_first=_event(first[2], (first[0], first[1]), t_bounds) if first else None,
    )


# ---- inbox (pure) ----------------------------------------------------------------------------


def _received(m: dict[str, Any], h: dict[str, str], tz: ZoneInfo) -> datetime | None:
    """Gmail's own receipt time first (the Date header is whatever the sender wrote)."""
    raw = m.get("internalDate")
    if raw is not None and str(raw).isdigit():
        return datetime.fromtimestamp(int(str(raw)) / 1000, tz)
    try:
        return parsedate_to_datetime(one_line(h.get("date"), 200)).astimezone(tz)
    except (TypeError, ValueError, IndexError, OverflowError):
        return None


def _when_label(at: datetime | None, day: date) -> str:
    if at is None:
        return ""
    if at.date() == day:
        return _hhmm(at)
    if at.date() == day - timedelta(days=1):
        return f"yesterday {_hhmm(at)}"
    return at.strftime("%d %b %H:%M")


def shape_message(m: dict[str, Any], tz: ZoneInfo, day: date) -> tuple[InboxItem, str]:
    h = headers_of(m.get("payload") or {})
    flat_from = one_line(h.get("from"), 1_000)
    name, addr = parseaddr(flat_from)
    bare = loose_address(addr)
    at = _received(m, h, tz)
    item = InboxItem(
        from_name=one_line(name if bare else flat_from, NAME_LIMIT),
        from_address=bare,
        subject=one_line(h.get("subject"), SUBJECT_LIMIT) or "(no subject)",
        date=at.isoformat() if at else "",
        when=_when_label(at, day),
    )
    return item, one_line(html.unescape(str(m.get("snippet") or "")), SNIPPET_LIMIT)


# ---- to-do (pure) ----------------------------------------------------------------------------


def shape_todo(
    found: list[tuple[TaskList, dict[str, Any]]], n_lists: int, day: date
) -> TodoSection:
    """Open tasks due on or before `day` → oldest first (overdue leads), ≤ MAX_TODO shown. The
    list's name only when the owner has more than one list."""
    dated = [(d, tl, t) for tl, t in found if (d := date_of(t.get("due"))) is not None and d <= day]
    dated.sort(key=lambda row: row[0])  # stable: same date keeps list and position order
    items = tuple(
        TodoItem(
            title=one_line(t.get("title"), TITLE_LIMIT) or "(no title)",
            due=d.isoformat(),
            overdue=d < day,
            list=one_line(tl.title, TODO_LIST_LIMIT) if n_lists > 1 else "",
        )
        for d, tl, t in dated[:MAX_TODO]
    )
    return TodoSection(
        total=len(dated), overdue=sum(1 for d, _, _ in dated if d < day), items=items
    )


# ---- the collector ---------------------------------------------------------------------------


def _zone(name: str) -> ZoneInfo | None:
    try:
        return ZoneInfo(name) if name else None
    except (ZoneInfoNotFoundError, ValueError):
        return None


class Collector:
    def __init__(self, google: GoogleConnector | None, approvals: ApprovalStore | None) -> None:
        self._google = google
        self._approvals = approvals

    async def time_zone(self, uid: str, fallback: str) -> ZoneInfo:
        """The primary calendar's zone when Google is linked, else `fallback` (else UTC)."""
        fb = _zone(fallback) or ZoneInfo("UTC")
        if self._google is None:
            return fb
        try:
            info = await self._google.request(uid, "GET", TZ_URL)
        except (GoogleNotConnected, GoogleAPIError):
            return fb
        zone = _zone(str(info.get("timeZone") or "")) if isinstance(info, dict) else None
        return zone or fb

    async def collect(self, uid: str, tz: ZoneInfo, day: date) -> Collected:
        (
            (cal_state, cal),
            (in_state, inbox),
            (j_state, waiting),
            (t_state, todo),
        ) = await asyncio.gather(
            self._section(lambda: self._calendar(uid, tz, day)),
            self._section(lambda: self._inbox(uid, tz, day)),
            self._jarvis(uid),
            self._todo(uid, day),
        )
        items, snippets = inbox if inbox is not None else (InboxSection(), ())
        data = BriefData(
            date=day.isoformat(),
            tz=tz.key,
            calendar=cal or CalendarSection(),
            inbox=items,
            jarvis=JarvisSection(approvals_waiting=waiting),
            todo=todo,
            sections_status=SectionsStatus(
                calendar=cal_state, inbox=in_state, jarvis=j_state, todo=t_state
            ),
        )
        return Collected(data=data, snippets=snippets)

    async def _todo(self, uid: str, day: date) -> tuple[TodoState, TodoSection | None]:
        """Never raises: its own state, like the other sections (and no call without the
        optional scope)."""
        if self._google is None:
            return "not_connected", None
        client = TasksClient(self._google)
        try:
            await client.require(uid)
            found, n_lists = await client.due_by(uid, day)
        except GoogleNotConnected:
            return "not_connected", None
        except TasksNotGranted:
            return "not_granted", None
        except Exception as exc:  # noqa: BLE001 — one section failing never fails the brief
            log.warning("brief to-do section unavailable", extra={"reason": type(exc).__name__})
            return "unavailable", None
        return "ok", shape_todo(found, n_lists, day)

    async def _section(self, fn: Callable[[], Awaitable[T]]) -> tuple[SectionState, T | None]:
        if self._google is None:
            return "not_connected", None
        try:
            return "ok", await fn()
        except GoogleNotConnected:
            return "not_connected", None
        except Exception as exc:  # noqa: BLE001 — one section failing never fails the brief
            log.warning("brief section unavailable", extra={"reason": type(exc).__name__})
            return "unavailable", None

    async def _calendar(self, uid: str, tz: ZoneInfo, day: date) -> CalendarSection:
        assert self._google is not None
        d0 = datetime.combine(day, time(0), tzinfo=tz)
        params = {
            "timeMin": d0.isoformat(),
            "timeMax": datetime.combine(day + timedelta(days=2), time(0), tzinfo=tz).isoformat(),
            "singleEvents": "true",
            "orderBy": "startTime",
            "maxResults": MAX_EVENTS,
        }
        data = await self._google.request(uid, "GET", EVENTS_URL, params=params)
        return shape_calendar(list(data.get("items") or []), tz, day)

    async def _inbox(
        self, uid: str, tz: ZoneInfo, day: date
    ) -> tuple[InboxSection, tuple[str, ...]]:
        assert self._google is not None
        params = {"q": INBOX_QUERY, "maxResults": MAX_MAIL}
        listing = await self._google.request(uid, "GET", MESSAGES_URL, params=params)
        ids = [
            str(m["id"])
            for m in listing.get("messages") or []
            if isinstance(m, dict) and _MESSAGE_ID.fullmatch(str(m.get("id") or ""))
        ][:MAX_MAIL]
        metas = await asyncio.gather(*(self._meta(uid, i) for i in ids), return_exceptions=True)
        shaped = [shape_message(m, tz, day) for m in metas if isinstance(m, dict) and m]
        total = max(int(listing.get("resultSizeEstimate") or 0), len(ids))
        section = InboxSection(total=total, items=tuple(i for i, _ in shaped))
        return section, tuple(s for _, s in shaped)

    async def _meta(self, uid: str, mid: str) -> dict[str, Any]:
        assert self._google is not None
        params = {"format": "metadata", "metadataHeaders": list(META_HEADERS)}
        data = await self._google.request(uid, "GET", f"{MESSAGES_URL}/{mid}", params=params)
        return dict(data) if isinstance(data, dict) else {}

    async def _jarvis(self, uid: str) -> tuple[SectionState, int]:
        if self._approvals is None:
            return "ok", 0
        try:
            pending = await self._approvals.list_pending()
        except Exception as exc:  # noqa: BLE001
            log.warning("brief approvals unavailable", extra={"reason": type(exc).__name__})
            return "unavailable", 0
        mine = f"{uid}:"
        return "ok", sum(1 for a in pending if (a.scope or "").startswith(mine))


__all__ = [
    "INBOX_QUERY",
    "MAX_TODO",
    "Collected",
    "Collector",
    "shape_calendar",
    "shape_message",
    "shape_todo",
]
