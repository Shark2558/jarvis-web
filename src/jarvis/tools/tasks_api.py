# src/jarvis/tools/tasks_api.py
"""Google Tasks v1 over the REST connector (Layer 6): ids, due dates, and one thin client the
to-do tools (`tools/google_tasks.py`) and the morning brief (`brief/collect.py`) share.

Verified 2026-11-01 (docs/plans/phase2-slice10-tools-wave.md §C): `due` is written as an
RFC 3339 timestamp but Google keeps the DATE only — the time is discarded and can be neither read
nor written. So a due value is a calendar date here, never an instant: it is sent as
`YYYY-MM-DDT00:00:00.000Z` and read back as its date part, never shifted by a time zone. Every
call goes through `GoogleConnector.request` (bearer, 15 s, one refresh, retry only for GETs,
vendor text never leaves); every response is checked for shape before it is used.
"""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from jarvis.integrations.google import (
    NOT_CONNECTED_MSG,
    RECONNECT_MSG,
    GoogleAPIError,
    GoogleConnector,
    GoogleNotConnected,
    can_use_tasks,
)
from jarvis.logging import get_logger
from jarvis.tools.card import one_line
from jarvis.tools.google_calendar import TZ_URL

log = get_logger(__name__)

BASE = "https://tasks.googleapis.com/tasks/v1"
LISTS_URL = f"{BASE}/users/@me/lists"
DEFAULT_LIST = "@default"
MAX_LISTS = 10  # lists read per call (the owner's own; Google allows 1000 per page)
PAGE_SIZE = 100  # Google's maximum page of tasks
LIST_TITLE_LIMIT = 100
TITLE_MAX = 1024  # Google: title ≤ 1024, notes ≤ 8192 characters
NOTES_MAX = 8192
EARLIEST, LATEST = date(1970, 1, 1), date(2100, 12, 31)

GRANT_MSG = (
    "JARVIS has no permission for your to-do list (Google Tasks) yet. Open Integrations and "
    "press Grant next to 'To-do list', then ask again."
)

# Google ids are base64-style strings. No "/", ".", "%", "?", ":" or space: an id can never walk
# to another URL path or carry a query.
_ID = re.compile(r"[A-Za-z0-9_=-]{1,256}")
_DATE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")
_DUE_PREFIX = re.compile(r"^([0-9]{4}-[0-9]{2}-[0-9]{2})")


class TasksNotGranted(RuntimeError):
    """The link exists but the owner has not granted the Tasks scope."""


# ---- ids --------------------------------------------------------------------------------------


@dataclass(frozen=True)
class TaskRef:
    list_id: str
    task_id: str

    @property
    def composite(self) -> str:
        return f"{self.list_id}:{self.task_id}"


def valid_list_id(raw: str) -> bool:
    return raw == DEFAULT_LIST or bool(_ID.fullmatch(raw))


def parse_task_id(raw: Any) -> TaskRef:
    """'<list id>:<task id>' (what tasks_list returns) or a bare task id (the default list)."""
    text = raw if isinstance(raw, str) else ""
    list_id, sep, task_id = text.rpartition(":")
    if not sep:
        list_id = DEFAULT_LIST
    if not _ID.fullmatch(task_id) or not valid_list_id(list_id):
        raise ValueError("task_id is not a valid to-do id (use an id from tasks_list)")
    return TaskRef(list_id, task_id)


def tasks_url(list_id: str) -> str:
    if not valid_list_id(list_id):
        raise ValueError("not a valid to-do list id")
    return f"{BASE}/lists/{list_id}/tasks"


def task_url(ref: TaskRef) -> str:
    return f"{tasks_url(ref.list_id)}/{ref.task_id}"


# ---- due dates --------------------------------------------------------------------------------


def _in_range(d: date) -> date:
    if not EARLIEST <= d <= LATEST:
        raise ValueError("due must be a date between 1970 and 2100")
    return d


def parse_due(value: Any, tz: ZoneInfo) -> tuple[date, bool]:
    """→ (the due date in the owner's zone, whether a time of day was given and dropped).

    'YYYY-MM-DD' is a date. A date-time is read in the owner's zone (naive) or converted into it
    (with an offset), and its time is dropped — except midnight exactly, which is how models
    write a plain date ('2027-01-20T00:00:00Z'): that is taken as that date, unshifted."""
    if not isinstance(value, str) or not value.strip():
        raise ValueError("due must be a date like 2027-01-20")
    text = value.strip()
    if _DATE.fullmatch(text):
        try:
            return _in_range(date.fromisoformat(text)), False
        except ValueError:
            raise ValueError(f"due is not a real date: {one_line(text, 40)}") from None
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        raise ValueError("due must be a date like 2027-01-20 (YYYY-MM-DD)") from None
    if (dt.hour, dt.minute, dt.second, dt.microsecond) == (0, 0, 0, 0):
        return _in_range(dt.date()), False
    local = dt.replace(tzinfo=tz) if dt.tzinfo is None else dt.astimezone(tz)
    return _in_range(local.date()), True


def due_to_api(d: date) -> str:
    return f"{d.isoformat()}T00:00:00.000Z"


def date_of(value: Any) -> date | None:
    """The date part of a Google timestamp ('2027-01-20T00:00:00.000Z' → 20 Jan); None when
    absent or malformed. Never converted between zones: Tasks stores a date."""
    m = _DUE_PREFIX.match(value) if isinstance(value, str) else None
    if m is None:
        return None
    try:
        return date.fromisoformat(m.group(1))
    except ValueError:
        return None


def show_date(d: date | None) -> str:
    return d.strftime("%a %d %b %Y") if d is not None else "(no date)"


# ---- the client -------------------------------------------------------------------------------


@dataclass(frozen=True)
class TaskList:
    id: str
    title: str


@dataclass(frozen=True)
class Page:
    items: list[dict[str, Any]]
    more: bool


def _dicts(value: Any) -> list[dict[str, Any]]:
    return [x for x in value if isinstance(x, dict)] if isinstance(value, list) else []


def _zone(name: str) -> ZoneInfo | None:
    try:
        return ZoneInfo(name) if name else None
    except (ZoneInfoNotFoundError, ValueError):
        return None


@dataclass
class TasksClient:
    conn: GoogleConnector

    async def require(self, uid: str) -> None:
        """Linked, usable, and the Tasks scope granted — from the stored link, no Google call."""
        st = await self.conn.status(uid)
        if not st["connected"]:
            raise GoogleNotConnected(RECONNECT_MSG if st["needs_reconnect"] else NOT_CONNECTED_MSG)
        if st["needs_reconnect"]:
            raise GoogleNotConnected(RECONNECT_MSG)
        if not can_use_tasks(st["scopes"]):
            raise TasksNotGranted(GRANT_MSG)

    async def owner_tz(self, uid: str, fallback: str) -> ZoneInfo:
        """The primary calendar's zone (the owner's), else `fallback`, else UTC."""
        fb = _zone(fallback) or ZoneInfo("UTC")
        try:
            info = await self.conn.request(uid, "GET", TZ_URL)
        except (GoogleAPIError, GoogleNotConnected):
            log.info("calendar time zone unavailable; using the configured zone")
            return fb
        zone = _zone(str(info.get("timeZone") or "")) if isinstance(info, dict) else None
        return zone or fb

    async def lists(self, uid: str) -> list[TaskList]:
        data = await self.conn.request(
            uid, "GET", LISTS_URL, params={"maxResults": MAX_LISTS}
        )
        out: list[TaskList] = []
        for item in _dicts(data.get("items") if isinstance(data, dict) else None):
            lid = str(item.get("id") or "")
            if _ID.fullmatch(lid):
                out.append(TaskList(lid, one_line(item.get("title"), LIST_TITLE_LIMIT) or "(list)"))
        return out[:MAX_LISTS]

    async def page(
        self, uid: str, list_id: str, *, due_through: date | None, completed: bool
    ) -> Page:
        """One page (≤ 100) of a list. `due_through` asks Google for tasks due on or before that
        date (dueMax is the next midnight; the caller filters again, whatever Google's bound)."""
        params: dict[str, Any] = {
            "maxResults": PAGE_SIZE,
            "showCompleted": "true" if completed else "false",
            "showHidden": "true" if completed else "false",
        }
        if due_through is not None:
            params["dueMax"] = due_to_api(due_through + timedelta(days=1))
        data = await self.conn.request(uid, "GET", tasks_url(list_id), params=params)
        if not isinstance(data, dict):
            raise GoogleAPIError("Google returned an unreadable to-do list.")
        items = [t for t in _dicts(data.get("items")) if _ID.fullmatch(str(t.get("id") or ""))]
        return Page(items, bool(data.get("nextPageToken")))

    async def due_by(self, uid: str, day: date) -> tuple[list[tuple[TaskList, dict[str, Any]]], int]:
        """Open tasks due on or before `day` in every list (≤ MAX_LISTS) → ((list, task), …),
        number of lists. One failing list fails the call (the brief marks the section)."""
        lists = await self.lists(uid)
        pages = await asyncio.gather(
            *(self.page(uid, tl.id, due_through=day, completed=False) for tl in lists)
        )
        found = [
            (tl, t)
            for tl, pg in zip(lists, pages, strict=True)
            for t in pg.items
            if t.get("status") != "completed" and (d := date_of(t.get("due"))) and d <= day
        ]
        return found, len(lists)

    async def get(self, uid: str, ref: TaskRef) -> dict[str, Any]:
        t = await self.conn.request(uid, "GET", task_url(ref))
        if not isinstance(t, dict) or not t.get("id"):
            raise GoogleAPIError("Google returned no details for that to-do.")
        return t

    async def insert(self, uid: str, list_id: str, body: dict[str, Any]) -> dict[str, Any]:
        t = await self.conn.request(uid, "POST", tasks_url(list_id), json=body)
        if not isinstance(t, dict) or not _ID.fullmatch(str(t.get("id") or "")):
            raise GoogleAPIError("Google did not confirm the new to-do.")
        return t

    async def patch(self, uid: str, ref: TaskRef, body: dict[str, Any]) -> dict[str, Any]:
        t = await self.conn.request(uid, "PATCH", task_url(ref), json=body)
        return t if isinstance(t, dict) else {}

    async def delete(self, uid: str, ref: TaskRef) -> None:
        await self.conn.request(uid, "DELETE", task_url(ref))


__all__ = [
    "BASE",
    "DEFAULT_LIST",
    "GRANT_MSG",
    "LISTS_URL",
    "MAX_LISTS",
    "NOTES_MAX",
    "TITLE_MAX",
    "Page",
    "TaskList",
    "TaskRef",
    "TasksClient",
    "TasksNotGranted",
    "date_of",
    "due_to_api",
    "parse_due",
    "parse_task_id",
    "show_date",
    "task_url",
    "tasks_url",
    "valid_list_id",
]
