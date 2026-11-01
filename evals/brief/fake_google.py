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


@dataclass
class FakeBriefGoogle:
    tz: str = "Asia/Kolkata"
    events: list[dict[str, Any]] = field(default_factory=list)
    messages: list[dict[str, Any]] = field(default_factory=list)
    estimate: int | None = None
    fail: dict[str, int] = field(default_factory=dict)  # tz | events | list | meta | insert
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
        return httpx.Response(599, json={"error": f"unscripted {method} {path}"})

    def writes(self) -> list[httpx.Request]:
        return [r for r in self.requests if r.method != "GET"]


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
