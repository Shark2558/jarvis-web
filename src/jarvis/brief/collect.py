# src/jarvis/brief/collect.py
"""Collect today's facts for the brief (Layer 6 → 7): fixed, read-only GETs through
`GoogleConnector.request` plus a count of the owner's waiting approvals.

R11.1 O12 (plan D20): the inbox is the WHOLE inbox (`tools.gmail_digest.read_inbox`): the unread
count is the INBOX label's own, every category is read (people first on the brief; promotions
and social counted only), codes and bank messages are withheld in every category (never listed,
their preview never reaches the AI: only their number), messages that could not be read are
counted and said, and with `reads` the read is a governed background read that obeys the
owner's mail row.

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
from jarvis.tools.background import BackgroundReads, NotRead
from jarvis.tools.calendar_alerts import is_reminder, reminder_text
from jarvis.tools.card import one_line
from jarvis.tools.gmail_digest import (
    GROUP_LABELS,
    INBOX_QUERY,
    SUMMARY_TOOL,
    Inbox,
    read_inbox,
)
from jarvis.tools.gmail_mime import headers_of
from jarvis.tools.google_calendar import EVENTS_URL, TZ_URL, compute_free_slots
from jarvis.tools.tasks_api import TaskList, TasksClient, TasksNotGranted, date_of

log = get_logger(__name__)
T = TypeVar("T")

MAX_EVENTS = 50
MAX_MAIL = 10  # messages listed on the brief
MAX_READS = 30  # unread messages read to count and group them (`mail_summary_max_reads`)
LISTED_GROUPS = ("people", "bills", "updates")  # promotions and social: counted, never listed
READ_JOB = "brief"  # the background read's name in the audit chain
SAYS_UNREAD = "failed"  # the section's field for "couldn't read N of M" (INTEGRATION-A 3.4)
TITLE_LIMIT = 120
LOCATION_LIMIT = 80
NAME_LIMIT = 80
SUBJECT_LIMIT = 120
SNIPPET_LIMIT = 200
MAX_TODO = 10
TODO_TIMEOUT_S = 20.0  # all to-do reads together (each call already has its own 15 s)
TODO_LIST_LIMIT = 60
FREE_MIN = timedelta(minutes=30)
WORK_FROM, WORK_TO = time(9, 0), time(18, 0)


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
    """`span` None = all-day. `bounds` = the local day the event is listed under. A reminder
    JARVIS set is labelled as one (and loses the ⏰ in its title: the label says it)."""
    attendees = [a for a in e.get("attendees") or [] if isinstance(a, dict)]
    reminder = is_reminder(e)
    title = reminder_text(e.get("summary")) if reminder else e.get("summary")
    common: dict[str, Any] = {
        "title": one_line(title, TITLE_LIMIT) or "(no title)",
        "location": one_line(e.get("location"), LOCATION_LIMIT) or None,
        "attendees": len(attendees),
        "has_video": bool(e.get("hangoutLink") or e.get("conferenceData")),
        "overlaps_with": overlaps,
        "reminder": reminder,
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
    for i, (s1, e1, ev1) in enumerate(timed):
        if is_reminder(ev1):  # a reminder is a pop-up, never a clash
            continue
        for j in range(i + 1, len(timed)):
            s2, e2, ev2 = timed[j]
            if s1 < e2 and s2 < e1 and not is_reminder(ev2):
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


class InboxUncertain(Exception):
    """No listed message could be read and the brief's section has no field to say so."""


def _say_plainly(box: Inbox) -> None:
    """Never "none of them is from a person" when the reads failed: an `InboxSection` without
    the `failed` field (before INTEGRATION-A 3.4) can't say "couldn't read any of the N", so
    the section is unavailable instead ("Your inbox could not be read just now.")."""
    if SAYS_UNREAD not in InboxSection.model_fields and box.failed and not box.letters:
        raise InboxUncertain("no message could be read")


def shape_inbox(box: Inbox, tz: ZoneInfo, day: date) -> tuple[InboxSection, tuple[str, ...]]:
    """R11.1 D20: the brief's inbox from the whole-inbox read: Gmail's own unread count, and the
    newest mail from people first, then bills and orders, then other updates (at most
    `MAX_MAIL`). In every category a message that looks like a code or a bank message is not
    listed and its preview never reaches the AI; only their number is kept. The per-group
    counts, the withheld count, whether the count is Gmail's own and how many messages could
    not be read travel in `groups` / `withheld` / `exact` / `failed` / `listed`: an
    `InboxSection` that has those fields keeps them (INTEGRATION-A 3.4)."""
    _say_plainly(box)
    listed = [x for group in LISTED_GROUPS for x in box.shown(group)][:MAX_MAIL]
    shaped = [shape_message(dict(x.raw), tz, day) for x in listed]
    counts = box.counts
    section = InboxSection.model_validate(
        {
            "total": box.total,
            "items": tuple(i for i, _ in shaped),
            "groups": tuple(
                {"key": k, "label": label, "unread": counts[k]} for k, label in GROUP_LABELS.items()
            ),
            "withheld": box.withheld,
            "exact": box.unread is not None,
            "failed": box.failed,
            "listed": box.listed,
        }
    )
    return section, tuple(snippet for _, snippet in shaped)


# ---- to-do (pure) ----------------------------------------------------------------------------


def shape_todo(
    found: list[tuple[TaskList, dict[str, Any]]], n_lists: int, day: date, *, complete: bool = True
) -> TodoSection:
    """Open tasks due on or before `day` → oldest first (overdue leads), ≤ MAX_TODO shown. The
    list's name only when the owner has more than one list. `complete` False (the read budget
    ran out) makes the counts "at least"."""
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
        total=len(dated),
        overdue=sum(1 for d, _, _ in dated if d < day),
        items=items,
        complete=complete,
    )


# ---- the collector ---------------------------------------------------------------------------


def _zone(name: str) -> ZoneInfo | None:
    try:
        return ZoneInfo(name) if name else None
    except (ZoneInfoNotFoundError, ValueError):
        return None


class Collector:
    """`reads` (R11.1 D20): the gateway's governed path for a background read
    (`jarvis.tools.background`). With it, the inbox is read only when the owner's "Search and
    read email" row allows it for `gmail_inbox_summary` ("Ask first" can't be asked at 07:00 and
    "Never" is total), and each read or refusal leaves one kind-only audit line. Without it the
    inbox is read as the brief always has."""

    def __init__(
        self,
        google: GoogleConnector | None,
        approvals: ApprovalStore | None,
        *,
        reads: BackgroundReads | None = None,
        max_reads: int = MAX_READS,
    ) -> None:
        self._google = google
        self._approvals = approvals
        self._reads = reads
        self._max_reads = max_reads

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
            scan = await asyncio.wait_for(client.due_by(uid, day), TODO_TIMEOUT_S)
        except GoogleNotConnected:
            return "not_connected", None
        except TasksNotGranted:
            return "not_granted", None
        except Exception as exc:  # noqa: BLE001 — one section failing never fails the brief
            log.warning("brief to-do section unavailable", extra={"reason": type(exc).__name__})
            return "unavailable", None
        return "ok", shape_todo(scan.found, scan.lists, day, complete=scan.complete)

    async def _section(self, fn: Callable[[], Awaitable[T]]) -> tuple[SectionState, T | None]:
        if self._google is None:
            return "not_connected", None
        try:
            return "ok", await fn()
        except GoogleNotConnected:
            return "not_connected", None
        except NotRead:  # R11.1 I1 (code M4): his mail row, not a fault
            return "paused", None
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
        """R11.1 D20: the whole inbox (`gmail_digest.read_inbox`): every category, a fixed
        number of reads, the exact count from the INBOX label."""
        assert self._google is not None
        if self._reads is None:
            return shape_inbox(await self._read(uid), tz, day)
        if not await self._reads.allowed(uid, SUMMARY_TOOL, job=READ_JOB):
            raise NotRead("the mail row does not allow a background read")
        async with self._reads.reading(SUMMARY_TOOL, job=READ_JOB):
            box = await self._read(uid)
        return shape_inbox(box, tz, day)

    async def _read(self, uid: str) -> Inbox:
        assert self._google is not None
        return await read_inbox(self._google, uid, max_reads=self._max_reads)

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
    "MAX_MAIL",
    "MAX_READS",
    "MAX_TODO",
    "Collected",
    "Collector",
    "InboxUncertain",
    "shape_calendar",
    "shape_inbox",
    "shape_message",
    "shape_todo",
]
