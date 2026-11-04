# evals/r1d_common.py
"""Shared by the R1 builder-D eval suites (packages, groceries, family, mail_aloud) and their unit
tests: in-memory Gmail and Calendar behind httpx.MockTransport, a connector, and a Brain + Gateway
harness driven by a scripted mock model (so every gate is decided by what the fake Google RECEIVED).

The Tasks fake is `evals/tasks/fake_tasks.py` (extended for list creation in `GroceryTasks`).
"""

from __future__ import annotations

import asyncio
import base64
import dataclasses
import json
import re
import sys
import uuid
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import httpx
from pydantic import SecretStr

from jarvis.config import LLMBackend, get_settings
from jarvis.core.brain import Brain
from jarvis.core.guardrails import ConfirmationGate
from jarvis.integrations.google import TASKS_SCOPE, GoogleConnector
from jarvis.integrations.vault import GoogleTokens, MemoryTokenStore
from jarvis.llm.base import ToolCall
from jarvis.llm.mock_provider import MockProvider
from jarvis.llm.router import ModelRouter, ModelTier
from jarvis.memory.inmemory import InMemorySessionStore
from jarvis.tools.audit import AuditLog
from jarvis.tools.gateway import Gateway
from jarvis.tools.policy import Policy
from jarvis.tools.registry import ToolRegistry

sys.path.insert(0, str(Path(__file__).parent / "tasks"))
from fake_tasks import TASKS, FakeTasks, Mutation  # noqa: E402

OWNER = "owner"
TIERS = {t: f"mock-{t.value}" for t in ModelTier}
LINK = [
    "https://www.googleapis.com/auth/calendar.events",
    "https://www.googleapis.com/auth/calendar.readonly",
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.compose",
]
GM = "/gmail/v1/users/me/messages"


def b64(text: str) -> str:
    return base64.urlsafe_b64encode(text.encode()).decode().rstrip("=")


def gmail_message(mail: dict[str, Any], *, full: bool = True) -> dict[str, Any]:
    """A fixture mail ({id, from, subject, date, body, snippet?, labels?}) as Gmail shows it."""
    headers = [
        {"name": "From", "value": mail["from"]},
        {"name": "To", "value": "akash@example.com"},
        {"name": "Subject", "value": mail["subject"]},
        {"name": "Date", "value": mail["date"]},
        {"name": "Message-ID", "value": f"<{mail['id']}@mail.test>"},
    ]
    payload: dict[str, Any] = {"mimeType": "text/plain", "headers": headers}
    if full:
        payload["body"] = {"data": b64(mail["body"]), "size": len(mail["body"])}
    snippet = mail.get("snippet")
    if snippet is None:
        snippet = " ".join(mail["body"].split())[:200]
    return {"id": mail["id"], "threadId": f"t_{mail['id']}", "snippet": snippet, "payload": payload}


@dataclasses.dataclass
class GmailFake:
    mails: list[dict[str, Any]] = dataclasses.field(default_factory=list)
    fail_list: int | None = None
    requests: list[httpx.Request] = dataclasses.field(default_factory=list)

    def client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=httpx.MockTransport(self.handler))

    def queries(self) -> list[str]:
        return [r.url.params.get("q", "") for r in self.requests if r.url.path == GM]

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        path = request.url.path
        if request.method == "POST":
            return httpx.Response(599, json={"error": "a read-only fake got a write"})
        if path == GM:
            if self.fail_list:
                return httpx.Response(self.fail_list, json={"error": {"message": "fake"}})
            limit = int(request.url.params.get("maxResults", "10"))
            return httpx.Response(
                200,
                json={
                    "messages": [{"id": m["id"]} for m in self.mails][:limit],
                    "resultSizeEstimate": len(self.mails),
                },
            )
        m = re.fullmatch(rf"{GM}/([A-Za-z0-9_-]+)", path)
        if m:
            found = next((x for x in self.mails if x["id"] == m.group(1)), None)
            if found is None:
                return httpx.Response(404, json={"error": {"message": "no"}})
            full = request.url.params.get("format") == "full"
            return httpx.Response(200, json=gmail_message(found, full=full))
        return httpx.Response(599, json={"error": f"unscripted {request.method} {path}"})


@dataclasses.dataclass
class GroceryTasks(FakeTasks):
    """FakeTasks plus `POST /users/@me/lists` (create a list), with an optional delay so two
    racing adds overlap."""

    create_delay_s: float = 0.0

    def client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=httpx.MockTransport(self.ahandler))

    def created(self) -> list[Mutation]:
        return [m for m in self.mutations if m.kind == "insert_list"]

    async def ahandler(self, request: httpx.Request) -> httpx.Response:
        if request.method == "POST" and request.url.path == f"{TASKS}/users/@me/lists":
            self.requests.append(request)
            await asyncio.sleep(self.create_delay_s)
            if (status := self.fail.get("insert_list")) is not None:
                return httpx.Response(status, json={"error": {"message": "fake failure"}})
            body = json.loads(request.content)
            item = {
                "kind": "tasks#taskList",
                "id": f"G{uuid.uuid4().hex[:8]}",
                "title": body["title"],
            }
            self.lists.append(item)
            self.mutations.append(Mutation("insert_list", item["id"], "", body))
            return httpx.Response(200, json=item)
        return self.handler(request)


CAL = "/calendar/v3"


@dataclasses.dataclass
class FamilyCalendars:
    """The owner's calendar plus family members' calendars behind one MockTransport.

    `roles`: calendar id -> the owner's access role on it (it is "in the owner's calendar list");
    `shared_only`: ids readable via calendars.get but absent from the calendar list;
    `events`: calendar id -> raw Google events; `busy`: calendar id -> [(start, end)] ISO."""

    tz: str = "Asia/Kolkata"
    roles: dict[str, str] = dataclasses.field(default_factory=dict)
    shared_only: set[str] = dataclasses.field(default_factory=set)
    events: dict[str, list[dict[str, Any]]] = dataclasses.field(default_factory=dict)
    busy: dict[str, list[tuple[str, str]]] = dataclasses.field(default_factory=dict)
    fail: dict[str, int] = dataclasses.field(default_factory=dict)
    requests: list[httpx.Request] = dataclasses.field(default_factory=list)
    inserted: list[tuple[str, dict[str, Any], dict[str, str]]] = dataclasses.field(
        default_factory=list
    )

    def client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=httpx.MockTransport(self.handler))

    def sent(self, method: str, suffix: str) -> list[httpx.Request]:
        return [r for r in self.requests if r.method == method and r.url.path.endswith(suffix)]

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        path, method = request.url.path, request.method
        if (status := self.fail.get(f"{method} {path}")) is not None:
            return httpx.Response(status, json={"error": {"message": "fake failure"}})
        if path == f"{CAL}/users/me/calendarList/primary":
            return httpx.Response(200, json={"timeZone": self.tz})
        if m := re.fullmatch(rf"{CAL}/users/me/calendarList/(.+)", path):
            cid = m.group(1)
            if cid in self.roles:
                return httpx.Response(200, json={"id": cid, "accessRole": self.roles[cid]})
            return httpx.Response(404, json={"error": {"message": "not found"}})
        if m := re.fullmatch(rf"{CAL}/calendars/([^/]+)", path):
            if m.group(1) in self.shared_only:
                return httpx.Response(200, json={"id": m.group(1)})
            return httpx.Response(404, json={"error": {"message": "not found"}})
        if m := re.fullmatch(rf"{CAL}/calendars/([^/]+)/events", path):
            return self._events(request, m.group(1))
        if path == f"{CAL}/freeBusy" and method == "POST":
            return self._free_busy(request)
        return httpx.Response(599, json={"error": f"unscripted {method} {path}"})

    def _events(self, request: httpx.Request, cid: str) -> httpx.Response:
        if request.method == "POST":
            body = json.loads(request.content)
            if self.roles.get(cid) not in ("writer", "owner"):
                return httpx.Response(403, json={"error": {"message": "no write"}})
            self.inserted.append((cid, body, dict(request.url.params)))
            return httpx.Response(200, json={"id": "ev1", **body})
        if cid != "primary" and self.roles.get(cid) == "freeBusyReader":
            return httpx.Response(403, json={"error": {"message": "no events"}})
        if cid != "primary" and cid not in self.roles and cid not in self.shared_only:
            return httpx.Response(404, json={"error": {"message": "gone"}})
        return httpx.Response(200, json={"items": self.events.get(cid, [])})

    def _free_busy(self, request: httpx.Request) -> httpx.Response:
        asked = [i["id"] for i in json.loads(request.content)["items"]]
        out: dict[str, Any] = {}
        for cid in asked:
            if cid != "primary" and cid not in self.roles and cid not in self.shared_only:
                out[cid] = {"errors": [{"domain": "global", "reason": "notFound"}], "busy": []}
            else:
                out[cid] = {"busy": [{"start": a, "end": b} for a, b in self.busy.get(cid, [])]}
        return httpx.Response(200, json={"calendars": out})


def tokens_for(*, tasks: bool = True) -> GoogleTokens:
    return GoogleTokens(
        email="owner@example.com",
        access_token=SecretStr("a"),
        refresh_token=SecretStr("r"),
        expires_at=4_000_000_000.0,
        scopes=[*LINK, *([TASKS_SCOPE] if tasks else [])],
    )


async def connector(http: httpx.AsyncClient, *, tasks: bool = True) -> GoogleConnector:
    store = MemoryTokenStore()
    await store.put(OWNER, tokens_for(tasks=tasks))
    return GoogleConnector(store, client_id="e", client_secret=SecretStr("e"), http=http)


@dataclasses.dataclass
class Harness:
    brain: Brain
    gateway: Gateway
    provider: MockProvider

    def script(self, rounds: Sequence[Sequence[dict[str, Any]]], final: str) -> None:
        for i, calls in enumerate(rounds):
            self.provider.script_tool_calls(
                [ToolCall(id=f"c{i}_{j}", **c) for j, c in enumerate(calls)]
            )
        self.provider.script(final)

    def results_seen(self) -> str:
        out: list[str] = []
        for call in self.provider.calls:
            for m in call.messages:
                if isinstance(m.content, list):
                    out += [b.content for b in m.content if getattr(b, "type", "") == "tool_result"]
        return "\n".join(str(x) for x in out)

    async def unconfirmed_r3(self) -> int:
        from jarvis.core.guardrails import ActionRisk

        tail = await self.gateway.audit.tail(500)
        return sum(
            1
            for e in tail.entries
            if e.outcome == "executed"
            and e.risk is ActionRisk.IRREVERSIBLE
            and e.detail != "confirmed"
        )


def harness(tools: Sequence[Any], *, rules: Any = None) -> Harness:
    reg = ToolRegistry()
    for t in tools:
        reg.register(t)
    gateway = Gateway(registry=reg, policy=Policy(), gate=ConfirmationGate(), audit=AuditLog())
    if rules is not None:
        gateway.rules = rules
    s = get_settings().model_copy(update={"llm_backend": LLMBackend.MOCK, "tools_enabled": True})
    provider = MockProvider()
    brain = Brain(
        router=ModelRouter(provider, TIERS),
        store=InMemorySessionStore(),
        settings=s,
        gateway=gateway,
    )
    return Harness(brain, gateway, provider)


__all__ = [
    "GM",
    "LINK",
    "OWNER",
    "TIERS",
    "FakeTasks",
    "FamilyCalendars",
    "GmailFake",
    "GroceryTasks",
    "Harness",
    "b64",
    "connector",
    "gmail_message",
    "harness",
    "json",
    "tokens_for",
]
