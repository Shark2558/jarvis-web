# evals/brief/fake_google.py
"""An in-memory Google for the brief evals: calendar time zone + events, Gmail listing +
metadata, and messages.insert. Behind httpx.MockTransport; records every request so the harness
can assert that collection only ever reads."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import httpx

CAL = "/calendar/v3"
GM = "/gmail/v1/users/me"
TK = "/tasks/v1"


@dataclass
class FakeBriefGoogle:
    tz: str = "Asia/Kolkata"
    events: list[dict[str, Any]] = field(default_factory=list)
    messages: list[dict[str, Any]] = field(default_factory=list)
    estimate: int | None = None
    # tz | events | list | meta | insert | tasklists | tasks
    fail: dict[str, int] = field(default_factory=dict)
    # Google Tasks (slice 10 C): list id → tasks ({"id", "title", "due": "YYYY-MM-DD", …})
    tasklists: list[dict[str, Any]] = field(
        default_factory=lambda: [{"id": "L1", "title": "My Tasks"}]
    )
    todo: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    requests: list[httpx.Request] = field(default_factory=list)

    def client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=httpx.MockTransport(self.handler))

    def _answer(self, key: str, body: dict[str, Any]) -> httpx.Response:
        if key in self.fail:
            return httpx.Response(self.fail[key], json={"error": "eval"})
        return httpx.Response(200, json=body)

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        path, method = request.url.path, request.method
        if path == f"{CAL}/users/me/calendarList/primary":
            return self._answer("tz", {"timeZone": self.tz})
        if path == f"{CAL}/calendars/primary/events":
            return self._answer("events", {"items": self.events})
        if path == f"{GM}/messages" and method == "GET":
            ids = [{"id": m["id"]} for m in self.messages]
            est = self.estimate if self.estimate is not None else len(ids)
            return self._answer("list", {"messages": ids, "resultSizeEstimate": est})
        if path == f"{GM}/messages" and method == "POST":
            return self._answer("insert", {"id": "inserted", "threadId": "t"})
        if path.startswith(f"{GM}/messages/"):
            mid = path.rsplit("/", 1)[1]
            found = next((m for m in self.messages if m["id"] == mid), None)
            return self._answer("meta", found) if found else httpx.Response(404, json={})
        if path == f"{TK}/users/@me/lists" and method == "GET":
            return self._answer("tasklists", {"items": self.tasklists})
        if path.startswith(f"{TK}/lists/") and path.endswith("/tasks") and method == "GET":
            due_max = request.url.params.get("dueMax", "")
            items = [
                {**t, "due": f"{t['due']}T00:00:00.000Z"} if t.get("due") else dict(t)
                for t in self.todo.get(path.split("/")[-2], [])
            ]
            keep = [t for t in items if not due_max or t.get("due", "~") < due_max]
            return self._answer("tasks", {"items": keep})
        return httpx.Response(599, json={"error": f"unscripted {method} {path}"})

    def writes(self) -> list[httpx.Request]:
        return [r for r in self.requests if r.method != "GET"]

    def tasks_reads(self) -> int:
        return sum(1 for r in self.requests if r.url.path.startswith(TK))


def message(
    mid: str, sender: str, subject: str, snippet: str = "", received: str | None = None
) -> dict[str, Any]:
    from datetime import datetime

    internal = str(int(datetime.fromisoformat(received).timestamp() * 1000)) if received else None
    return {
        "id": mid,
        "threadId": f"t_{mid}",
        "snippet": snippet,
        "internalDate": internal,
        "payload": {
            "headers": [
                {"name": "From", "value": sender},
                {"name": "Subject", "value": subject},
                {"name": "Date", "value": "Fri, 15 Jan 2027 07:00:00 +0530"},
            ]
        },
    }
