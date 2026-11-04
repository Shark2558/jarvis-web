# src/jarvis/groceries/service.py
"""The Groceries list on Google Tasks (R1 D14): find or create it, list, add with dedupe, tick off.

The list is found by its exact title "Groceries" (and made on the first add: creation is part of the
R2 add). Its id is cached in `groceries/{uid}`; if Google says the cached list is gone, it is
searched for again. One lock per owner serialises list creation and the read-modify-write of an add,
so two adds racing make exactly one list and one line per item. Everything goes through
`GoogleConnector.request` via `TasksClient`.

Provenance (slice 11 D8): a list read vouches only when every line is the owner's own; what a round
that read outside content wrote is marked outside (`tools.task_marks`) like any to-do JARVIS writes.
"""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from jarvis.groceries.items import Action, Item, format_title, merge, norm_key, parse_title
from jarvis.groceries.store import TITLE, GroceryStore
from jarvis.integrations.google import GoogleAPIError, GoogleNotFound
from jarvis.logging import get_logger
from jarvis.tools.card import one_line
from jarvis.tools.task_marks import OutsideSet, OutsideTasks, owner_authored_task
from jarvis.tools.tasks_api import (
    _ID,
    LISTS_URL,
    TaskList,
    TaskRef,
    TasksClient,
    _dicts,
)

log = get_logger(__name__)

MAX_LIST_PAGES = 5
LIST_PAGE = 100
MAX_PAGES_OF_ITEMS = 3


class GroceryClient(TasksClient):
    """TasksClient plus the two list-level calls Groceries needs."""

    async def find_by_title(self, uid: str, title: str) -> TaskList | None:
        token: str | None = None
        for _ in range(MAX_LIST_PAGES):
            params: dict[str, Any] = {"maxResults": LIST_PAGE}
            if token:
                params["pageToken"] = token
            data = await self._call(uid, "GET", LISTS_URL, params=params)
            if not isinstance(data, dict):
                raise GoogleAPIError("Google returned an unreadable list of lists.")
            for item in _dicts(data.get("items")):
                lid = str(item.get("id") or "")
                if _ID.fullmatch(lid) and item.get("title") == title:
                    return TaskList(lid, title)
            token = (
                data.get("nextPageToken") if isinstance(data.get("nextPageToken"), str) else None
            )
            if not token:
                return None
        return None

    async def create_list(self, uid: str, title: str) -> TaskList:
        data = await self._call(uid, "POST", LISTS_URL, json={"title": title})
        lid = str(data.get("id") or "") if isinstance(data, dict) else ""
        if not _ID.fullmatch(lid):
            raise GoogleAPIError("Google did not confirm the new list.")
        return TaskList(lid, title)


@dataclass(frozen=True)
class Line:
    item: Item
    task: dict[str, Any]

    @property
    def ref_id(self) -> str:
        return str(self.task["id"])


@dataclass
class AddOutcome:
    results: list[dict[str, Any]]
    tasks: list[dict[str, Any]]  # every task written, as Google returned it
    created_list: bool = False


@dataclass
class GroceryService:
    client: GroceryClient
    store: GroceryStore
    marks: OutsideTasks
    _locks: dict[str, asyncio.Lock] = field(default_factory=dict)

    def lock(self, uid: str) -> asyncio.Lock:
        return self._locks.setdefault(uid, asyncio.Lock())

    # ---- the list ---------------------------------------------------------------------------

    async def _find(self, uid: str) -> TaskList | None:
        """The cached list if Google still has it, else the one titled "Groceries"."""
        cached = await self.store.list_id(uid)
        if cached:
            try:
                await self.client.page(uid, cached, due_through=None, completed=False)
                return TaskList(cached, TITLE)
            except GoogleNotFound:
                await self.store.forget(uid)
        found = await self.client.find_by_title(uid, TITLE)
        if found is not None:
            await self.store.remember(uid, found.id)
        return found

    async def ensure(self, uid: str, *, create: bool) -> tuple[TaskList | None, bool]:
        """→ (the list or None, whether it was just made). Caller holds the owner's lock."""
        found = await self._find(uid)
        if found is not None or not create:
            return found, False
        made = await self.client.create_list(uid, TITLE)
        await self.store.remember(uid, made.id)
        return made, True

    async def lines(self, uid: str, tl: TaskList) -> list[Line]:
        page = await self.client.read(
            uid, tl.id, due_through=None, completed=False, max_pages=MAX_PAGES_OF_ITEMS
        )
        return [
            Line(parse_title(one_line(t.get("title"), 300)), t)
            for t in page.items
            if t.get("status") != "completed" and one_line(t.get("title"), 300)
        ]

    # ---- read -------------------------------------------------------------------------------

    async def read(self, uid: str) -> tuple[list[Line], OutsideSet | None, bool]:
        """→ (open lines, the outside set, whether the list exists)."""
        tl, _ = await self.ensure(uid, create=False)
        if tl is None:
            return [], await self.marks.read(uid), False
        return await self.lines(uid, tl), await self.marks.read(uid), True

    # ---- add --------------------------------------------------------------------------------

    async def add(self, uid: str, wanted: Sequence[Item], *, outside: bool) -> AddOutcome:
        async with self.lock(uid):
            tl, created = await self.ensure(uid, create=True)
            assert tl is not None
            open_lines = {norm_key(ln.item.name): ln for ln in await self.lines(uid, tl)}
            token = await self.marks.begin(uid) if outside else None
            results: list[dict[str, Any]] = []
            tasks: list[dict[str, Any]] = []
            new_ids: list[str] = []
            try:
                for want in wanted:
                    await self._add_one(uid, tl, want, open_lines, results, tasks, new_ids, outside)
            except Exception as exc:
                if token is not None:
                    await self.marks.failed(uid, token, exc)
                raise
            if token is not None:
                await self.marks.finish(uid, token, new_ids)
            return AddOutcome(results, tasks, created)

    async def _add_one(
        self,
        uid: str,
        tl: TaskList,
        want: Item,
        open_lines: dict[str, Line],
        results: list[dict[str, Any]],
        tasks: list[dict[str, Any]],
        new_ids: list[str],
        outside: bool,
    ) -> None:
        key = norm_key(want.name)
        have = open_lines.get(key)
        if have is None:
            t = await self.client.insert(uid, tl.id, {"title": format_title(want)})
            new_ids.append(str(t["id"]))
            tasks.append(t)
            open_lines[key] = Line(want, t)
            results.append({"action": "added", "title": format_title(want)})
            return
        merged, action = merge(have.item, want)
        if action == "already_on_list":
            tasks.append(have.task)
            results.append({"action": action, "title": format_title(have.item)})
            return
        ref = TaskRef(tl.id, have.ref_id)
        if outside:  # marked BEFORE it changes (D8)
            await self.marks.add(uid, [ref.task_id])
        t = await self.client.patch(uid, ref, {"title": format_title(merged)})
        t = t or {**have.task, "title": format_title(merged)}
        tasks.append(t)
        open_lines[key] = Line(merged, t)
        row: dict[str, Any] = {"action": action, "title": format_title(merged)}
        if action == "replaced":
            row["was"] = format_title(have.item)
        results.append(row)

    # ---- remove (tick off) ------------------------------------------------------------------

    async def remove(
        self, uid: str, names: Sequence[str]
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """→ (a row per name, the tasks ticked off as Google had them)."""
        async with self.lock(uid):
            tl, _ = await self.ensure(uid, create=False)
            if tl is None:
                return [{"action": "not_found", "name": n} for n in names], []
            open_lines = {norm_key(ln.item.name): ln for ln in await self.lines(uid, tl)}
            out: list[dict[str, Any]] = []
            ticked: list[dict[str, Any]] = []
            for name in names:
                have = open_lines.pop(norm_key(name), None)
                if have is None:
                    out.append({"action": "not_found", "name": name})
                    continue
                await self.client.patch(uid, TaskRef(tl.id, have.ref_id), {"status": "completed"})
                ticked.append(have.task)
                out.append({"action": "ticked_off", "title": format_title(have.item)})
            return out, ticked

    def owner_authored(self, tasks: Sequence[dict[str, Any]], marks: OutsideSet | None) -> bool:
        return all(owner_authored_task(t, marks) for t in tasks)


__all__ = ["Action", "AddOutcome", "GroceryClient", "GroceryService", "Line"]
