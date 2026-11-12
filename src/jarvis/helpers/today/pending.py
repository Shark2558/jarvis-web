# src/jarvis/helpers/today/pending.py
""" "Top priority now" and what is pending (docs/plans/r11-free-helpers.md D9, item 10). No model.

`PendingService` asks every part's pending source (`ctx.pending_all()`, read late, so it sees A,
B, C and D), each within `SOURCE_TIMEOUT_S`; one that fails or is slow is left out and named
(`missing`), never failing the answer. `rank` orders them exactly as D9 says: overdue first, then
due today, then by urgency (soon, later), then his pinned item (`weight`), then the due date
(none last); equal items keep their source's order.

Part A's own sources: `BillsPending` (each bill's current unpaid due date, overdue or within a
week: "Electricity ₹1,240 due tomorrow") and `TasksPending` (Google Tasks due by today, through
the existing Tasks client; his To-dos row obeyed, fail closed; a to-do's title is his list's
words, fenced by the tools before a model sees it). In a console tool call the gateway decided,
"Ask first" on his To-do list row reads (he is there); the brief and the tab read on "Allow"
only, and the tab says when the row pauses them (`tasks_pause`). One audit line per read, a cut
one included (`BackgroundReads.reading`).
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Protocol

from jarvis.helpers.paused import PauseCheck
from jarvis.helpers.ports import ORDER, PendingItem, PendingSource, Urgency, rank
from jarvis.helpers.today.bills import BillsService, amount_words, current_due, when_words
from jarvis.helpers.today.birthdays import row_allows
from jarvis.helpers.today.store import BillsOff
from jarvis.integrations.google import GoogleConnector, GoogleNotConnected
from jarvis.logging import get_logger
from jarvis.notify.quiet import local
from jarvis.tools.background import BackgroundReads, NotRead
from jarvis.tools.card import one_line
from jarvis.tools.tasks_api import TasksClient, TasksNotGranted, date_of

log = get_logger(__name__)

SOURCE_TIMEOUT_S = 3.0
TOP = 10
SOON_DAYS = 3
WEEK = 7
LABEL = 80
TASKS_TOOL = "tasks_list"
TASKS_JOB = "pending"  # "top priority" and "what is pending" read his to-dos (and the nudge)
TASKS_WHAT = "To-dos in your top priority"  # the "paused" line's words (jarvis.helpers.paused)


@dataclass(frozen=True)
class Collected:
    items: tuple[PendingItem, ...]
    missing: tuple[str, ...] = ()
    asked: int = 0


class PendingService:
    def __init__(
        self,
        sources: Callable[[], Sequence[PendingSource]],
        *,
        timeout_s: float = SOURCE_TIMEOUT_S,
    ) -> None:
        self._sources = sources
        self._timeout_s = timeout_s

    async def _one(self, src: PendingSource, uid: str, now: datetime) -> list[PendingItem] | None:
        try:
            got = await asyncio.wait_for(src.pending(uid, now), self._timeout_s)
        except Exception as exc:  # noqa: BLE001 - one source never fails the answer
            log.warning("a pending source was left out", extra={"error": type(exc).__name__})
            return None
        return [i for i in got if isinstance(i, PendingItem)]

    async def collect(self, uid: str, now: datetime) -> Collected:
        sources = list(self._sources())
        found = await asyncio.gather(*(self._one(s, uid, now) for s in sources))
        items = [i for chunk in found if chunk for i in chunk]
        missing = tuple(
            str(s.name) for s, chunk in zip(sources, found, strict=True) if chunk is None
        )
        return Collected(tuple(rank(items)), missing, len(sources))

    async def top(self, uid: str, now: datetime) -> tuple[PendingItem | None, Collected]:
        got = await self.collect(uid, now)
        return (got.items[0] if got.items else None), got

    async def grouped(
        self, uid: str, now: datetime, limit: int = TOP
    ) -> list[tuple[str, list[PendingItem]]]:
        """The top `limit` items, grouped by source; groups in the order of their best item."""
        groups: dict[str, list[PendingItem]] = {}
        for item in (await self.collect(uid, now)).items[:limit]:
            groups.setdefault(item.source, []).append(item)
        return list(groups.items())


def _urgency(due: date, today: date) -> Urgency | None:
    gap = (due - today).days
    if gap < 0:
        return "overdue"
    if gap == 0:
        return "today"
    if gap <= SOON_DAYS:
        return "soon"
    return "later" if gap <= WEEK else None


class BillsPending:
    name = "today"

    def __init__(self, service: BillsService) -> None:
        self._svc = service

    async def pending(self, uid: str, now: datetime) -> Sequence[PendingItem]:
        if not self._svc.store.available:
            return []
        try:
            book = await self._svc.book(uid)
        except BillsOff:
            return []
        today = self._svc.today()
        out: list[PendingItem] = []
        for bill in book.bills:
            due = current_due(bill, today)
            urgency = _urgency(due, today) if due is not None else None
            if due is None or urgency is None:
                continue
            label = one_line(f"{bill.label} {amount_words(bill)} {when_words(due, today)}", LABEL)
            at = self._svc.at_local(due, book.prefs.bills_at)
            out.append(PendingItem("today", label, urgency, due=at, ref=bill.id))
        return out


class TasksDue(Protocol):
    async def due(self, uid: str, day: date) -> list[tuple[str, date]]: ...


class GoogleTasksDue:
    """Open Google Tasks due by `day` (title, due date), through the existing Tasks client."""

    def __init__(self, google: GoogleConnector) -> None:
        self._client = TasksClient(google)

    async def due(self, uid: str, day: date) -> list[tuple[str, date]]:
        try:
            await self._client.require(uid)
        except (TasksNotGranted, GoogleNotConnected):
            return []
        scan = await self._client.due_by(uid, day)
        out = [
            (str(t.get("title") or ""), d) for _, t in scan.found if (d := date_of(t.get("due")))
        ]
        return sorted(out, key=lambda row: row[1])


class TasksPending:
    name = "tasks"

    def __init__(self, tasks: TasksDue, *, reads: BackgroundReads | None, tz: str) -> None:
        self._tasks = tasks
        self._reads = reads
        self._tz = tz

    async def _due(self, uid: str, today: date) -> list[tuple[str, date]]:
        """His to-dos due by today, through the gateway's governed path (I1); one audit line."""
        assert self._reads is not None
        async with self._reads.reading(TASKS_TOOL, job=TASKS_JOB):
            return list(await self._tasks.due(uid, today))

    async def pending(self, uid: str, now: datetime) -> Sequence[PendingItem]:
        if not (v := await row_allows(self._reads, uid, TASKS_TOOL, TASKS_JOB)):
            if v.reason == "denied":  # "Never": his own "don't read my to-dos", nothing to say
                return []
            raise NotRead  # "Ask first" or unreadable: the answer names his to-dos as not checked
        today = local(now, self._tz).date()
        zone = local(now, self._tz).tzinfo
        out: list[PendingItem] = []
        for title, due in await self._due(uid, today):
            urgency: Urgency = "overdue" if due < today else "today"
            label = one_line(title, LABEL) or "(a to-do with no title)"
            at = datetime(due.year, due.month, due.day, tzinfo=zone) + timedelta(
                hours=23, minutes=59
            )
            out.append(PendingItem("tasks", label, urgency, due=at))
        return out


async def _always(uid: str) -> bool:
    return True


def tasks_pause(reads: BackgroundReads | None) -> PauseCheck:
    """His to-dos have no switch: "Ask first" (or rows unreadable) pauses them in the brief and
    the tab; "Never" is his own "don't read my to-dos", so it says nothing."""
    return PauseCheck(reads, what=TASKS_WHAT, tools=(TASKS_TOOL,), on=_always, never_too=False)


__all__ = [
    "ORDER",
    "SOURCE_TIMEOUT_S",
    "TASKS_TOOL",
    "TOP",
    "BillsPending",
    "Collected",
    "GoogleTasksDue",
    "NotRead",
    "PendingService",
    "TasksPending",
    "rank",
    "tasks_pause",
]
