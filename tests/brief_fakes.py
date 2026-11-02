# tests/brief_fakes.py — an in-memory Google (Calendar tz + events, Gmail list/metadata/insert)
# for the morning-brief tests. A plain module (not conftest) so test files can import it.
from __future__ import annotations

import asyncio
import base64
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import httpx
from pydantic import SecretStr

from jarvis.integrations.google import GoogleConnector
from jarvis.integrations.vault import GoogleTokens, MemoryTokenStore
from jarvis.storage.docs import Doc, DocTx, MemoryDocs, Op, Query, T

OWNER_EMAIL = "akash@example.com"
OWNER_UID = "u_owner"
CAL = "/calendar/v3"
GM = "/gmail/v1/users/me"
TK = "/tasks/v1"
INSERT_SCOPE = "https://www.googleapis.com/auth/gmail.insert"
TASKS_SCOPE = "https://www.googleapis.com/auth/tasks"
BASE_SCOPES = [
    "https://www.googleapis.com/auth/calendar.events",
    "https://www.googleapis.com/auth/calendar.readonly",
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.compose",
]


def timed(
    eid: str, title: str, start: str, end: str, *, tz: str = "+05:30", **extra: Any
) -> dict[str, Any]:
    """A timed event on a given local ISO date-time ('2027-01-15T09:00')."""
    return {
        "id": eid,
        "status": "confirmed",
        "summary": title,
        "start": {"dateTime": f"{start}:00{tz}"},
        "end": {"dateTime": f"{end}:00{tz}"},
        **extra,
    }


def all_day(eid: str, title: str, start: str, end: str, **extra: Any) -> dict[str, Any]:
    return {
        "id": eid,
        "status": "confirmed",
        "summary": title,
        "start": {"date": start},
        "end": {"date": end},
        **extra,
    }


def mail(
    mid: str, sender: str, subject: str, *, snippet: str = "", internal_ms: int | None = None
) -> dict[str, Any]:
    return {
        "id": mid,
        "threadId": f"t_{mid}",
        "snippet": snippet,
        "internalDate": str(internal_ms) if internal_ms is not None else None,
        "payload": {
            "headers": [
                {"name": "From", "value": sender},
                {"name": "Subject", "value": subject},
                {"name": "Date", "value": "Fri, 15 Jan 2027 07:42:00 +0530"},
            ]
        },
    }


def ms(iso: str) -> int:
    return int(datetime.fromisoformat(iso).timestamp() * 1000)


def todo(tid: str, title: str, due: str | None = None, **extra: Any) -> dict[str, Any]:
    """A Google Tasks task; `due` 'YYYY-MM-DD' (Google keeps the date only)."""
    task: dict[str, Any] = {"id": tid, "title": title, "status": "needsAction", **extra}
    if due is not None:
        task["due"] = f"{due}T00:00:00.000Z"
    return task


@dataclass
class BriefGoogle:
    """Scriptable fake. `fail[key] = status` makes that route answer with an error, where key
    is one of: tz, events, list, meta, insert, tasklists, tasks. `delay_s` slows every request
    (race tests). `todo` maps a task list id to its tasks (Google Tasks, slice 10 C)."""

    tz: str = "Asia/Kolkata"
    events: list[dict[str, Any]] = field(default_factory=list)
    messages: list[dict[str, Any]] = field(default_factory=list)
    estimate: int | None = None
    listed_only: list[str] = field(default_factory=list)  # listed, but 404 on metadata
    tasklists: list[dict[str, Any]] = field(
        default_factory=lambda: [{"id": "L1", "title": "My Tasks"}]
    )
    todo: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    fail: dict[str, int] = field(default_factory=dict)
    delay_s: float = 0.0
    requests: list[httpx.Request] = field(default_factory=list)
    inserts: list[httpx.Request] = field(default_factory=list)

    def client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=httpx.MockTransport(self.handler))

    def _err(self, key: str) -> httpx.Response | None:
        return httpx.Response(self.fail[key], json={"error": "x"}) if key in self.fail else None

    async def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.delay_s:
            await asyncio.sleep(self.delay_s)
        path, method = request.url.path, request.method
        if path == f"{CAL}/users/me/calendarList/primary":
            return self._err("tz") or httpx.Response(200, json={"timeZone": self.tz})
        if path == f"{CAL}/calendars/primary/events":
            return self._err("events") or httpx.Response(200, json={"items": self.events})
        if path == f"{GM}/messages" and method == "GET":
            ids = [{"id": m["id"]} for m in self.messages] + [{"id": i} for i in self.listed_only]
            est = self.estimate if self.estimate is not None else len(ids)
            body = {"messages": ids, "resultSizeEstimate": est}
            return self._err("list") or httpx.Response(200, json=body)
        if path == f"{GM}/messages" and method == "POST":
            if (bad := self._err("insert")) is not None:
                return bad
            self.inserts.append(request)
            return httpx.Response(200, json={"id": f"ins{len(self.inserts)}", "threadId": "t"})
        if path.startswith(f"{GM}/messages/") and method == "GET":
            mid = path.rsplit("/", 1)[1]
            found = next((m for m in self.messages if m["id"] == mid), None)
            if found is None:
                return httpx.Response(404, json={"error": "nf"})
            return self._err("meta") or httpx.Response(200, json=found)
        if path == f"{TK}/users/@me/lists" and method == "GET":
            return self._err("tasklists") or _paged(request, self.tasklists, 1000)
        if path.startswith(f"{TK}/lists/") and path.endswith("/tasks") and method == "GET":
            lid = path.split("/")[-2]
            due_max = request.url.params.get("dueMax", "")
            items = [
                t
                for t in self.todo.get(lid, [])
                if t.get("status") != "completed" and (not due_max or t.get("due", "~") < due_max)
            ]
            return self._err("tasks") or _paged(request, items, 20)
        return httpx.Response(599, json={"error": f"unscripted {method} {path}"})

    def tasks_reads(self) -> list[httpx.Request]:
        return [r for r in self.requests if r.url.path.startswith(TK)]

    def inserted_raw(self, i: int = 0) -> bytes:
        import json

        raw = json.loads(self.inserts[i].content)["raw"]
        return base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4))


def _paged(request: httpx.Request, items: list[Any], default: int) -> httpx.Response:
    """Google-style pages: maxResults + an opaque pageToken (here: the offset)."""
    p = request.url.params
    limit, start = int(p.get("maxResults", default)), int(p.get("pageToken", "0") or 0)
    body: dict[str, Any] = {"items": items[start : start + limit]}
    if start + limit < len(items):
        body["nextPageToken"] = str(start + limit)
    return httpx.Response(200, json=body)


class SlowDocs(MemoryDocs):
    """Every database call yields for a few ms, so concurrent callers really interleave."""

    delay_s = 0.003

    async def get(self, path: str) -> Doc | None:
        await asyncio.sleep(self.delay_s)
        return await super().get(path)

    async def query(self, q: Query) -> list[tuple[str, Doc]]:
        await asyncio.sleep(self.delay_s)
        return await super().query(q)

    async def write(self, ops: Sequence[Op]) -> None:
        await asyncio.sleep(self.delay_s)
        await super().write(ops)

    async def transaction(self, fn: Callable[[DocTx], Awaitable[T]]) -> T:
        await asyncio.sleep(self.delay_s)
        return await super().transaction(fn)


def tokens(*, insert: bool = True, email: str = OWNER_EMAIL, tasks: bool = False) -> GoogleTokens:
    return GoogleTokens(
        email=email,
        access_token=SecretStr("acc"),
        refresh_token=SecretStr("ref"),
        expires_at=4_000_000_000.0,
        scopes=[
            *BASE_SCOPES,
            *([INSERT_SCOPE] if insert else []),
            *([TASKS_SCOPE] if tasks else []),
        ],
    )


async def connector(
    fake: BriefGoogle,
    *,
    uid: str = OWNER_UID,
    linked: bool = True,
    insert: bool = True,
    tasks: bool = False,
) -> GoogleConnector:
    store = MemoryTokenStore()
    if linked:
        await store.put(uid, tokens(insert=insert, tasks=tasks))
    return GoogleConnector(store, client_id="cid", client_secret=SecretStr("s"), http=fake.client())
