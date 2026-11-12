# tests/r11_1_fakes_a.py -- R11.1 Part A fakes: a scripted brain that can also say HOW an answer
# stopped (cut off by the output cap, or simply empty), and an in-memory Google (Calendar events
# with private markers, free/busy, Gmail labels and messages) for the batch, the series and the
# inbox tests. A plain module (not conftest) so tests and evals import it as a top-level module.
from __future__ import annotations

import asyncio
import json
import re
from collections import deque
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any

import httpx
from pydantic import SecretStr

from jarvis.config import Settings
from jarvis.core.guardrails import ConfirmationGate
from jarvis.fixes.ports import FixContext
from jarvis.integrations.google import GoogleConnector
from jarvis.integrations.vault import GoogleTokens, MemoryTokenStore
from jarvis.llm.base import ChatMessage, Completion, Effort, StreamUsage, ToolCall, ToolSpec, Usage
from jarvis.llm.mock_provider import MockProvider, RecordedCall
from jarvis.notify.ports import Delivery, Signal
from jarvis.storage.docs import MemoryDocs
from jarvis.tools.audit import AuditLog
from jarvis.tools.gateway import Gateway, GatewayOutcome
from jarvis.tools.policy import Policy, PolicyRule
from jarvis.tools.registry import ToolRegistry
from jarvis.tools.taint import context_trust
from jarvis.undo.service import UndoBin
from jarvis.undo.store import DeletedStore

UID = "u_owner"
MAIL_NOW_MS = 1_794_303_600_000  # an hour after `letter`'s default time
CUT = "max_tokens"
CAL = "/calendar/v3"
EVENTS = f"{CAL}/calendars/primary/events"
GM = "/gmail/v1/users/me"
SCOPES = [
    "https://www.googleapis.com/auth/calendar.events",
    "https://www.googleapis.com/auth/calendar.readonly",
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.compose",
]


@dataclass(frozen=True)
class Said:
    """One scripted answer: its words, its tool calls and how it stopped (`CUT`: the cap)."""

    text: str = ""
    calls: tuple[ToolCall, ...] = ()
    stop: str | None = None
    cost_usd: float = 0.0


@dataclass
class ScriptedBrain(MockProvider):
    """A MockProvider whose `said` answers come first, each with its own stop reason; with none
    left it behaves as the mock does (its own script, then an echo)."""

    said: deque[Said] = field(default_factory=deque)

    def say(self, *answers: Said) -> None:
        self.said.extend(answers)

    async def complete(
        self,
        *,
        system: str,
        system_dynamic: str | None = None,
        messages: list[ChatMessage],
        model: str,
        max_tokens: int,
        effort: Effort | None = None,
        tools: list[ToolSpec] | None = None,
    ) -> Completion:
        if not self.said:
            return await super().complete(
                system=system,
                system_dynamic=system_dynamic,
                messages=messages,
                model=model,
                max_tokens=max_tokens,
                effort=effort,
                tools=tools,
            )
        full = system + ("\n" + system_dynamic if system_dynamic else "")
        self.calls.append(RecordedCall(full, list(messages), model, max_tokens, effort, tools))
        s = self.said.popleft()
        out = max_tokens if s.stop == CUT else max(1, len(s.text) // 4)
        return Completion(
            text=s.text,
            tool_calls=list(s.calls),
            model=model,
            provider=self.name,
            usage=Usage(input_tokens=10, output_tokens=out),
            stop_reason=s.stop or ("tool_use" if s.calls else "end_turn"),
            latency_ms=1,
            cost_usd=s.cost_usd,
        )

    async def stream(
        self,
        *,
        system: str,
        system_dynamic: str | None = None,
        messages: list[ChatMessage],
        model: str,
        max_tokens: int,
        effort: Effort | None = None,
        usage: StreamUsage | None = None,
    ) -> AsyncIterator[str]:
        """The next `said` answer as a stream: its words, then the vendor's closing count (the
        whole cap when it was cut off, as a real provider reports it)."""
        done = await self.complete(
            system=system,
            system_dynamic=system_dynamic,
            messages=messages,
            model=model,
            max_tokens=max_tokens,
            effort=effort,
        )
        if usage is not None:
            usage.started(
                input_tokens=10, output_tokens=0, cache_read_tokens=0, cache_write_tokens=0
            )
        for word in done.text.split(" "):
            if word:
                yield word + " "
        if usage is not None:
            usage.finished(output_tokens=done.usage.output_tokens)


def call(name: str, i: int = 0, **arguments: Any) -> ToolCall:
    return ToolCall(id=f"{name}_{i}", name=name, arguments=arguments)


# ---- Google ------------------------------------------------------------------------------------


def _matches(mail: dict[str, Any], asked: str, now_ms: int) -> bool:
    """What Gmail's search does with the two operators the tools use."""
    if m := re.search(r"category:(\w+)", asked):
        want = "PERSONAL" if m.group(1) == "primary" else m.group(1).upper()
        if f"CATEGORY_{want}" not in mail.get("labelIds", []):
            return False
    if m := re.search(r"newer_than:(\d+)d", asked):
        return int(mail.get("internalDate", "0")) >= now_ms - int(m.group(1)) * 86_400_000
    return True


def _at(part: dict[str, Any]) -> str:
    """An event's start or end as comparable text: its dateTime, or its day at midnight IST."""
    return str(part.get("dateTime") or f"{part.get('date', '')}T00:00:00+05:30")


def _private(event: dict[str, Any]) -> dict[str, str]:
    props = event.get("extendedProperties") or {}
    return dict(props.get("private") or {})


@dataclass
class PlanGoogle:
    """An in-memory Google behind httpx.MockTransport.

    Calendar: `POST events` makes an event (ids `ev00001`...; `fail_creates` fails the n-th create,
    1-based, with that status; `lose_answers` creates it but answers 503), `GET events` lists them
    (by `privateExtendedProperty=key=value` when given, else by time window), `GET / PATCH /
    DELETE events/<id>`, and `POST freeBusy` answers from `busy` (ISO pairs) plus every event.
    Gmail: `labels/INBOX` (`unread`: messagesUnread), `messages` (ids of the `mails` the query
    matches, as Gmail reads `category:` and `newer_than:Nd`; at most maxResults) and
    `messages/<id>` (metadata with `labelIds`)."""

    tz: str = "Asia/Kolkata"
    events: dict[str, dict[str, Any]] = field(default_factory=dict)
    busy: list[tuple[str, str]] = field(default_factory=list)
    fail_creates: dict[int, int] = field(default_factory=dict)
    lose_answers: set[int] = field(default_factory=set)
    lose_patches: set[str] = field(default_factory=set)  # event ids: patched, then 503
    fail: dict[str, int] = field(default_factory=dict)  # "<METHOD> <path>" -> status
    mails: list[dict[str, Any]] = field(default_factory=list)
    mail_now_ms: int = MAIL_NOW_MS  # "now" for `newer_than:`
    unread: int | None = None
    requests: list[httpx.Request] = field(default_factory=list)
    creates: int = 0
    delay_s: float = 0.0  # every write takes this long, so writes at a time can be counted
    in_flight: int = 0
    most_at_once: int = 0

    def client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=httpx.MockTransport(self.slow_handler))

    async def slow_handler(self, request: httpx.Request) -> httpx.Response:
        if request.method == "GET" or not self.delay_s:
            return self.handler(request)
        self.in_flight += 1
        self.most_at_once = max(self.most_at_once, self.in_flight)
        try:
            await asyncio.sleep(self.delay_s)
            return self.handler(request)
        finally:
            self.in_flight -= 1

    def sent(self, method: str, suffix: str = "") -> list[httpx.Request]:
        return [r for r in self.requests if r.method == method and r.url.path.endswith(suffix)]

    def gmail_reads(self) -> list[httpx.Request]:
        return [r for r in self.requests if r.url.path.startswith(GM)]

    def live(self) -> list[dict[str, Any]]:
        return [e for e in self.events.values() if e.get("status") != "cancelled"]

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        path, method = request.url.path, request.method
        if (status := self.fail.get(f"{method} {path}")) is not None:
            return httpx.Response(status, json={"error": {"message": "fake failure"}})
        if path == f"{CAL}/users/me/calendarList/primary":
            return httpx.Response(200, json={"timeZone": self.tz})
        if path == EVENTS:
            return self._create(request) if method == "POST" else self._list(request)
        if path == f"{CAL}/freeBusy" and method == "POST":
            return self._free_busy(request)
        if m := re.fullmatch(rf"{EVENTS}/([A-Za-z0-9_]+)", path):
            return self._one(request, m.group(1))
        if path.startswith(GM):
            return self._gmail(request)
        return httpx.Response(599, json={"error": f"unscripted {method} {path}"})

    # ---- calendar -------------------------------------------------------------------------
    def _create(self, request: httpx.Request) -> httpx.Response:
        self.creates += 1
        n = self.creates
        if (status := self.fail_creates.get(n)) is not None:
            return httpx.Response(status, json={"error": {"message": "fake failure"}})
        body = json.loads(request.content)
        eid = f"ev{len(self.events) + 1:05d}"
        event = {
            "id": eid,
            "status": "confirmed",
            "organizer": {"email": "owner@example.com", "self": True},
            "creator": {"email": "owner@example.com", "self": True},
            "updated": "2026-11-12T06:00:00.000Z",
            "etag": f'"{eid}-1"',
            **body,
        }
        self.events[eid] = event
        if n in self.lose_answers:
            return httpx.Response(503, json={"error": {"message": "lost"}})
        return httpx.Response(200, json=event)

    def _list(self, request: httpx.Request) -> httpx.Response:
        p = request.url.params
        items = self.live()
        if wanted := p.get("privateExtendedProperty"):
            key, _, value = wanted.partition("=")
            items = [e for e in items if _private(e).get(key) == value]
        lo, hi = p.get("timeMin"), p.get("timeMax")
        if lo and hi:  # an all-day entry ("date") is compared by its day
            items = [e for e in items if _at(e["start"]) < hi and _at(e["end"]) > lo]
        items.sort(key=lambda e: _at(e["start"]))
        limit = int(p.get("maxResults", "250"))
        start = int(p.get("pageToken", "0") or 0)
        body: dict[str, Any] = {"items": items[start : start + limit]}
        if start + limit < len(items):
            body["nextPageToken"] = str(start + limit)
        return httpx.Response(200, json=body)

    def _one(self, request: httpx.Request, eid: str) -> httpx.Response:
        event = self.events.get(eid)
        if event is None or (event.get("status") == "cancelled" and request.method != "GET"):
            return httpx.Response(404, json={"error": {"message": "not found"}})
        if request.method == "GET":
            return httpx.Response(200, json=event)
        if request.method == "DELETE":
            event["status"] = "cancelled"
            return httpx.Response(204)
        if request.method == "PATCH":
            event.update(json.loads(request.content))
            n = int(event["etag"].strip('"').rsplit("-", 1)[1]) + 1
            event["etag"] = f'"{eid}-{n}"'
            event["updated"] = f"2026-11-12T07:00:{n:02d}.000Z"
            if eid in self.lose_patches:
                return httpx.Response(503, json={"error": {"message": "lost"}})
            return httpx.Response(200, json=event)
        return httpx.Response(405, json={"error": {"message": "no"}})

    def owner_edits(self, eid: str, **changes: Any) -> None:
        """The owner changed the event himself in Google Calendar (a later `updated`)."""
        self.events[eid].update(changes)
        self.events[eid]["updated"] = "2026-11-13T09:00:00.000Z"

    def _free_busy(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        lo, hi = body["timeMin"], body["timeMax"]
        blocks = [{"start": a, "end": b} for a, b in self.busy]
        blocks += [
            {"start": e["start"]["dateTime"], "end": e["end"]["dateTime"]}
            for e in self.live()
            if "dateTime" in e.get("start", {}) and "dateTime" in e.get("end", {})
        ]
        del lo, hi  # the fake answers every block; the caller clips
        return httpx.Response(200, json={"calendars": {"primary": {"busy": blocks}}})

    # ---- gmail ----------------------------------------------------------------------------
    def _gmail(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if request.method != "GET":
            return httpx.Response(599, json={"error": "a read-only fake got a write"})
        if path == f"{GM}/labels/INBOX":
            n = self.unread if self.unread is not None else len(self.mails)
            return httpx.Response(200, json={"id": "INBOX", "messagesUnread": n})
        if path == f"{GM}/messages":
            limit = int(request.url.params.get("maxResults", "100"))
            asked = request.url.params.get("q", "")
            ids = [{"id": m["id"]} for m in self.mails if _matches(m, asked, self.mail_now_ms)]
            ids = ids[:limit]
            return httpx.Response(200, json={"messages": ids, "resultSizeEstimate": len(ids)})
        if m := re.fullmatch(rf"{GM}/messages/([A-Za-z0-9_-]+)", path):
            found = next((x for x in self.mails if x["id"] == m.group(1)), None)
            if found is None:
                return httpx.Response(404, json={"error": {"message": "no"}})
            return httpx.Response(200, json=found)
        return httpx.Response(599, json={"error": f"unscripted GET {path}"})


def letter(
    mid: str,
    sender: str,
    subject: str,
    *,
    category: str = "PERSONAL",
    snippet: str = "",
    internal_ms: int = 1_794_300_000_000,
) -> dict[str, Any]:
    """An unread inbox message as Gmail's metadata format shows it (`category`: PERSONAL,
    UPDATES, PROMOTIONS, SOCIAL or FORUMS)."""
    return {
        "id": mid,
        "threadId": f"t_{mid}",
        "labelIds": ["UNREAD", "INBOX", f"CATEGORY_{category}"],
        "snippet": snippet,
        "internalDate": str(internal_ms),
        "payload": {
            "headers": [
                {"name": "From", "value": sender},
                {"name": "Subject", "value": subject},
                {"name": "Date", "value": "Thu, 12 Nov 2026 07:42:00 +0530"},
            ]
        },
    }


async def connector(fake: PlanGoogle, uid: str = UID) -> GoogleConnector:
    store = MemoryTokenStore()
    await store.put(
        uid,
        GoogleTokens(
            email="owner@example.com",
            access_token=SecretStr("a"),
            refresh_token=SecretStr("r"),
            expires_at=4_000_000_000.0,
            scopes=SCOPES,
        ),
    )
    return GoogleConnector(store, client_id="e", client_secret=SecretStr("e"), http=fake.client())


# ---- the plan part on fakes ----------------------------------------------------------------------


class Clock:
    """A clock a test moves (`at`), in the owner's zone."""

    def __init__(self, at: datetime) -> None:
        self.at = at

    def __call__(self) -> datetime:
        return self.at


class Told:
    """A Notifier that records what it was asked to say and answers as the policy would
    (`action`: ring by day, hold at night, drop when the kind is switched off). `reached`:
    whether a ring reached a channel (False: Telegram and push both failed). `cancel`: the send
    is cancelled while it is in flight (the clock's time budget ran out)."""

    def __init__(self, action: str = "ring") -> None:
        self.action = action
        self.sent: list[tuple[str, str, str]] = []
        self.fail = False
        self.reached = True
        self.cancel = False

    async def notify(
        self,
        uid: str,
        signal: Signal,
        message: str,
        *,
        named_message: str | None = None,
        photo: bytes | None = None,
    ) -> Delivery:
        if self.fail:
            raise RuntimeError("the notifier is down")
        if self.cancel:
            raise asyncio.CancelledError()
        self.sent.append((uid, signal.kind, message))
        rang = self.action == "ring" and self.reached
        return Delivery(action=self.action, reason="test", telegram=rang)  # type: ignore[arg-type]


class PlanRig:
    """Part A built by its own `build(ctx)` over fakes: the batch and series tools behind a real
    Gateway, the check-in job, the store, a clock and a notifier."""

    def __init__(
        self,
        fake: PlanGoogle,
        conn: GoogleConnector | None,
        *,
        now: datetime,
        settings: Settings | None = None,
        rules: Sequence[PolicyRule] = (),
    ) -> None:
        from jarvis.series.part import build

        self.fake, self.clock, self.told = fake, Clock(now), Told()
        self.docs, self.audit = MemoryDocs(), AuditLog()
        self.bin = UndoBin(DeletedStore(self.docs))
        self.state: dict[str, Any] = {
            "google": conn,
            "undo": self.bin,
            "helpers_now": self.clock,
        }
        self.s = settings or Settings(_env_file=None, env="dev")
        self.ctx = FixContext(
            s=self.s,
            docs=self.docs,
            audit=self.audit,
            state=self.state.get,
            notifier=lambda: self.told,
        )
        self.part = build(self.ctx)
        reg = ToolRegistry()
        for t in self.part.tools:
            reg.register(t)
        self.gw = Gateway(
            registry=reg, policy=Policy(list(rules)), gate=ConfirmationGate(), audit=self.audit
        )
        self.state["gateway"] = self.gw

    @property
    def svc(self) -> Any:
        return self.part.services["series"]

    async def run(self, name: str, args: dict[str, Any], *, scope: str = "", **kw: Any) -> Any:
        call_ = ToolCall(id="c", name=name, arguments=args)
        return await self.gw.execute(call_, scope=scope or f"{UID}:sess_1", **kw)

    async def approved(self, name: str, args: dict[str, Any], **kw: Any) -> Any:
        asked = await self.run(name, args, **kw)
        assert asked.pending is not None, asked.error
        return await self.run(name, args, confirmation_id=asked.pending.id, **kw)

    async def approve(self, card_id: str) -> Any:
        """Approve a card that is already waiting (as the Approvals panel does)."""
        card = await self.gw.gate.get(card_id)
        assert card is not None
        call_ = ToolCall(id="approve", name=card.tool, arguments=card.arguments)
        return await self.gw.execute(call_, confirmation_id=card.id, scope=card.scope)


def weekday_sessions(n: int = 60, *, first: str = "2026-11-16") -> list[dict[str, Any]]:
    """`n` one-hour sessions, Monday to Friday at 19:00 IST, from Monday 16 Nov 2026."""
    out: list[dict[str, Any]] = []
    day = date.fromisoformat(first)
    while len(out) < n:
        if day.weekday() < 5:
            out.append(
                {
                    "summary": f"Topic {len(out) + 1}",
                    "start": f"{day.isoformat()}T19:00:00+05:30",
                    "end": f"{day.isoformat()}T20:00:00+05:30",
                }
            )
        day += timedelta(days=1)
    return out


async def plan_rig(now: datetime, **kw: Any) -> PlanRig:
    fake = PlanGoogle()
    return PlanRig(fake, await connector(fake), now=now, **kw)


async def followed(rig: PlanRig, n: int = 60, name: str = "CCA") -> dict[str, Any]:
    """A followed plan of `n` weekday sessions, made the real way: one approved batch."""
    args = {"events": weekday_sessions(n), "title_prefix": name, "series": {"name": name}}
    with context_trust(untrusted=False):  # the owner typed it himself
        asked = await rig.run("calendar_create_events", args)
    assert asked.pending is not None, asked.error
    out = await rig.run("calendar_create_events", args, confirmation_id=asked.pending.id)
    assert out.outcome is GatewayOutcome.EXECUTED, out.error
    return dict(out.result)


__all__ = [
    "CUT",
    "EVENTS",
    "GM",
    "UID",
    "Clock",
    "PlanGoogle",
    "PlanRig",
    "Said",
    "ScriptedBrain",
    "Told",
    "call",
    "connector",
    "followed",
    "letter",
    "plan_rig",
    "weekday_sessions",
]
