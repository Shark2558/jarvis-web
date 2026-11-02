# evals/tasks/fake_tasks.py
"""An in-memory Google Tasks v1 (+ the calendar time-zone look-up) behind httpx.MockTransport.

Shared by the unit tests (tests/test_tasks_tools.py imports it by path) and the eval harness.
It behaves like the real API where that matters for safety and correctness (verified
2026-11-01, docs/plans/phase2-slice10-tools-wave.md §C): `due` keeps the DATE only (any time is
discarded and comes back as T00:00:00.000Z), `@default` is the first list, `showCompleted`
defaults to true, a completed task gets a `completed` stamp. Every request is recorded, and every
change is kept in `mutations` — the eval asserts on what this fake RECEIVED, not on what the
model said.

Slice 11 (undo): insert honours the `parent` / `previous` query parameters (kept in the task as
`parent`, and in the mutation's `params`), `move` re-parents a task, and `cascade` makes a
parent's delete take its subtasks with it — Google's docs don't say whether it does, so the
tests run both ways.

Slice 11 fix: `soft_delete` keeps a deleted task readable with `deleted: true` (the Tasks resource
has that flag) instead of 404; `lost` answers a route with an error AFTER making the change (the
answer was lost on the way back); `after_delete` answers a route with an error once a DELETE was
asked for; insert refuses (400) a `previous` that isn't a sibling under the same parent.
"""

from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass, field
from datetime import date
from typing import Any

import httpx

TASKS = "/tasks/v1"
TZ_PATH = "/calendar/v3/users/me/calendarList/primary"
_DUE = re.compile(r"^(\d{4}-\d{2}-\d{2})")
COMPLETED_AT = "2027-01-15T03:00:00.000Z"


@dataclass
class Mutation:
    kind: str  # insert | patch | complete | delete | move
    list_id: str
    task_id: str
    body: dict[str, Any] = field(default_factory=dict)
    params: dict[str, str] = field(default_factory=dict)


@dataclass
class FakeTasks:
    tz: str = "Asia/Kolkata"
    lists: list[dict[str, Any]] = field(default_factory=lambda: [{"id": "L1", "title": "My Tasks"}])
    tasks: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    # route key → HTTP status to answer with: tz | lists | tasks | get | insert | patch | delete
    fail: dict[str, int] = field(default_factory=dict)
    requests: list[httpx.Request] = field(default_factory=list)
    mutations: list[Mutation] = field(default_factory=list)
    cascade: bool = False  # deleting a parent also deletes its subtasks
    soft_delete: bool = False  # a deleted task stays readable, flagged `deleted: true`
    lost: dict[str, int] = field(default_factory=dict)  # route key → status AFTER the change
    after_delete: dict[str, int] = field(default_factory=dict)  # route key → status after a DELETE

    # ---- set-up ---------------------------------------------------------------------------

    def add(self, list_id: str, title: str, **extra: Any) -> str:
        """Plant a task (as another app or the owner made it). Returns its id."""
        tid = extra.pop("id", None) or f"t{uuid.uuid4().hex[:10]}"
        task = {"kind": "tasks#task", "id": tid, "title": title, "status": "needsAction", **extra}
        if "due" in task and task["due"] is not None:
            task["due"] = _date_only(str(task["due"]))
        self.tasks.setdefault(list_id, []).append(task)
        return tid

    def client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=httpx.MockTransport(self.handler))

    # ---- what tests assert on --------------------------------------------------------------

    def changes(self, *kinds: str) -> list[Mutation]:
        return [m for m in self.mutations if not kinds or m.kind in kinds]

    def task(self, list_id: str, task_id: str) -> dict[str, Any] | None:
        return next((t for t in self.tasks.get(list_id, []) if t["id"] == task_id), None)

    # ---- transport -------------------------------------------------------------------------

    def _err(self, key: str) -> httpx.Response | None:
        status = self.fail.get(key)
        if status is None and any(r.method == "DELETE" for r in self.requests):
            status = self.after_delete.get(key)  # once a delete was asked for (done or not)
        if status is not None:
            return httpx.Response(status, json={"error": {"message": "fake failure"}})
        return None

    def _answer(self, key: str, ok: httpx.Response) -> httpx.Response:
        """The change was made; its answer may still be lost (`lost`)."""
        if key in self.lost:
            return httpx.Response(self.lost[key], json={"error": {"message": "fake lost"}})
        return ok

    def _list_id(self, raw: str) -> str | None:
        if raw == "@default":
            return self.lists[0]["id"] if self.lists else None
        return raw if any(item["id"] == raw for item in self.lists) else None

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        path, method = request.url.path, request.method
        if path == TZ_PATH:
            return self._err("tz") or httpx.Response(200, json={"timeZone": self.tz})
        if path == f"{TASKS}/users/@me/lists" and method == "GET":
            return self._err("lists") or _paged(request, self.lists, "tasks#taskLists", 1000)
        m = re.fullmatch(rf"{TASKS}/lists/([^/]+)/tasks(?:/([^/]+))?(/move)?", path)
        if m is None:
            return httpx.Response(599, json={"error": f"unscripted {method} {path}"})
        list_id = self._list_id(m.group(1))
        if list_id is None:
            return httpx.Response(404, json={"error": {"message": "list not found"}})
        if m.group(3) is not None and method == "POST":
            return self._err("move") or self._move(request, list_id, m.group(2))
        if m.group(2) is None:
            if method == "GET":
                return self._err("tasks") or self._list(request, list_id)
            if method == "POST":
                return self._err("insert") or self._insert(request, list_id)
            return httpx.Response(405)
        return self._one(request, list_id, m.group(2))

    def _list(self, request: httpx.Request, list_id: str) -> httpx.Response:
        p = request.url.params
        show_completed = p.get("showCompleted", "true") == "true"
        show_hidden = p.get("showHidden", "false") == "true"
        due_max = p.get("dueMax")
        items = []
        for t in self.tasks.get(list_id, []):
            if t.get("deleted"):
                continue
            if t["status"] == "completed" and not (show_completed and show_hidden):
                continue
            if due_max and (not t.get("due") or t["due"] >= due_max):
                continue  # strictly before dueMax: the client must not rely on the bound
            items.append(t)
        return _paged(request, items, "tasks#tasks", 20)

    def _sibling(self, list_id: str, previous: str, parent: str | None) -> bool:
        t = self.task(list_id, previous)
        return t is not None and not t.get("deleted") and t.get("parent") == parent

    def _insert(self, request: httpx.Request, list_id: str) -> httpx.Response:
        body = json.loads(request.content)
        params = {k: v for k, v in request.url.params.items() if k in ("parent", "previous")}
        if (p := params.get("parent")) and self.task(list_id, p) is None:
            return httpx.Response(400, json={"error": {"message": "parent not found"}})
        if (prev := params.get("previous")) and not self._sibling(
            list_id, prev, params.get("parent")
        ):
            return httpx.Response(400, json={"error": {"message": "previous is not a sibling"}})
        tid = f"n{uuid.uuid4().hex[:10]}"
        task = {"kind": "tasks#task", "id": tid, "status": "needsAction", **body}
        task.pop("parent", None)  # read-only in the body: only the query parameter sets it
        if params.get("parent"):
            task["parent"] = params["parent"]
        if task.get("due"):
            task["due"] = _date_only(str(task["due"]))
        self.tasks.setdefault(list_id, []).append(task)
        self.mutations.append(Mutation("insert", list_id, tid, body, params))
        return httpx.Response(200, json=task)

    def _move(self, request: httpx.Request, list_id: str, task_id: str) -> httpx.Response:
        task = self.task(list_id, task_id)
        if task is None:
            return httpx.Response(404, json={"error": {"message": "task not found"}})
        params = {k: v for k, v in request.url.params.items() if k in ("parent", "previous")}
        if params.get("parent"):
            task["parent"] = params["parent"]
        else:
            task.pop("parent", None)
        self.mutations.append(Mutation("move", list_id, task_id, {}, params))
        return httpx.Response(200, json=task)

    def _delete(self, list_id: str, task_id: str) -> None:
        gone = {task_id} | (self._descendants(list_id, task_id) if self.cascade else set())
        if self.soft_delete:
            for t in self.tasks[list_id]:
                if t["id"] in gone:
                    t.update(deleted=True, hidden=True)
        else:
            self.tasks[list_id] = [t for t in self.tasks[list_id] if t["id"] not in gone]
        self.mutations.append(Mutation("delete", list_id, task_id))

    def _descendants(self, list_id: str, task_id: str) -> set[str]:
        found, frontier = set(), {task_id}
        while frontier:
            kids = {t["id"] for t in self.tasks.get(list_id, []) if t.get("parent") in frontier}
            frontier = kids - found
            found |= kids
        return found

    def _one(self, request: httpx.Request, list_id: str, task_id: str) -> httpx.Response:
        task = self.task(list_id, task_id)
        method = request.method
        key = {"GET": "get", "PATCH": "patch", "DELETE": "delete"}.get(method, "")
        if (bad := self._err(key)) is not None:
            return bad
        if task is not None and task.get("deleted") and method == "GET" and self.soft_delete:
            return httpx.Response(200, json=task)
        if task is None or task.get("deleted"):
            return httpx.Response(404, json={"error": {"message": "task not found"}})
        if method == "GET":
            return httpx.Response(200, json=task)
        if method == "DELETE":
            self._delete(list_id, task_id)
            return self._answer("delete", httpx.Response(204))
        if method == "PATCH":
            body = json.loads(request.content)
            for k, v in body.items():
                if v is None:
                    task.pop(k, None)
                elif k == "due":
                    task["due"] = _date_only(str(v))
                else:
                    task[k] = v
            if body.get("status") == "completed":
                task["completed"] = COMPLETED_AT
            kind = "complete" if body == {"status": "completed"} else "patch"
            self.mutations.append(Mutation(kind, list_id, task_id, body))
            return httpx.Response(200, json=task)
        return httpx.Response(405)


def _paged(request: httpx.Request, items: list[Any], kind: str, default: int) -> httpx.Response:
    """Google-style pages: `maxResults`, and an opaque `pageToken` (here: the offset)."""
    p = request.url.params
    limit, start = int(p.get("maxResults", default)), int(p.get("pageToken", "0") or 0)
    body: dict[str, Any] = {"kind": kind, "items": items[start : start + limit]}
    if start + limit < len(items):
        body["nextPageToken"] = str(start + limit)
    return httpx.Response(200, json=body)


def _date_only(value: str) -> str:
    """What Google keeps of a due value: the date, at midnight UTC."""
    m = _DUE.match(value)
    if m is None:
        raise ValueError(f"bad due value {value!r}")
    date.fromisoformat(m.group(1))
    return f"{m.group(1)}T00:00:00.000Z"


__all__ = ["COMPLETED_AT", "FakeTasks", "Mutation"]
