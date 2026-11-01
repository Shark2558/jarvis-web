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
INSERT_SCOPE = "https://www.googleapis.com/auth/gmail.insert"
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


@dataclass
class BriefGoogle:
    """Scriptable fake. `fail[key] = status` makes that route answer with an error, where key
    is one of: tz, events, list, meta, insert. `delay_s` slows every request (race tests)."""

    tz: str = "Asia/Kolkata"
    events: list[dict[str, Any]] = field(default_factory=list)
    messages: list[dict[str, Any]] = field(default_factory=list)
    estimate: int | None = None
    listed_only: list[str] = field(default_factory=list)  # listed, but 404 on metadata
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
        return httpx.Response(599, json={"error": f"unscripted {method} {path}"})

    def inserted_raw(self, i: int = 0) -> bytes:
        import json

        raw = json.loads(self.inserts[i].content)["raw"]
        return base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4))


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


def tokens(*, insert: bool = True, email: str = OWNER_EMAIL) -> GoogleTokens:
    return GoogleTokens(
        email=email,
        access_token=SecretStr("acc"),
        refresh_token=SecretStr("ref"),
        expires_at=4_000_000_000.0,
        scopes=[*BASE_SCOPES, *([INSERT_SCOPE] if insert else [])],
    )


async def connector(
    fake: BriefGoogle, *, uid: str = OWNER_UID, linked: bool = True, insert: bool = True
) -> GoogleConnector:
    store = MemoryTokenStore()
    if linked:
        await store.put(uid, tokens(insert=insert))
    return GoogleConnector(store, client_id="cid", client_secret=SecretStr("s"), http=fake.client())
