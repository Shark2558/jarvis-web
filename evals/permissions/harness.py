# evals/permissions/harness.py
"""Shared rig for the slice 10 D permission evals: the real app in Google sign-in mode (mock
brain, in-process storage, built-in dev tools plus an event-moving tool whose card can change
under it), the owner's browser (a signed cookie from the real /auth routes, Google's half faked),
a software authenticator, a movable clock, and a case recorder.
Self-contained (evals never import from tests/)."""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from authenticator import SoftAuthenticator
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr

from jarvis.api import create_app
from jarvis.config import AuthMode, LLMBackend, SessionBackend, Settings
from jarvis.core.guardrails import ActionRisk, ConfirmationGate
from jarvis.llm.base import ToolCall
from jarvis.llm.mock_provider import MockProvider
from jarvis.memory.inmemory import InMemorySessionStore
from jarvis.tools import AuditLog, Gateway, Policy, Tool, ToolRegistry
from jarvis.tools.base import Preview
from jarvis.tools.builtin import InMemoryWorld, builtin_tools

ORIGIN = "http://jarvis.local"  # the relying party: RP ID "jarvis.local"
OWNER = "owner@example.com"
TOKEN = "eval-cli-token"
CSRF = {"X-Requested-With": "JARVIS"}
BEARER = {"Authorization": f"Bearer {TOKEN}"}


def settings(**kw: Any) -> Settings:
    return Settings(
        _env_file=None,
        env="dev",
        llm_backend=LLMBackend.MOCK,
        session_backend=SessionBackend.MEMORY,
        usd_inr_live=False,
        log_level="CRITICAL",
        auth_mode=AuthMode.GOOGLE,
        google_client_id="eval.apps.googleusercontent.com",
        google_client_secret=SecretStr("eval-secret"),
        owner_emails=[OWNER],
        session_secret=SecretStr("e" * 32),
        public_base_url=ORIGIN,
        api_token=SecretStr(TOKEN),
        **kw,
    )


class Clock:
    def __init__(self) -> None:
        self.now = datetime(2026, 11, 1, 9, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += timedelta(seconds=seconds)


@dataclass
class Calendar:
    """An event whose guests can appear between the card and the approval."""

    guests: bool = False
    moves: list[bool] = field(default_factory=list)  # one entry per move: did it email guests?

    def tool(self) -> Tool:
        async def preview(a: dict[str, Any]) -> Preview:
            who = "and email the guests" if self.guests else "only you"
            risk = ActionRisk.IRREVERSIBLE if self.guests else None
            return Preview(f"Move the dentist to {a['when']} ({who})", risk)

        return Tool(
            "calendar_update_event",
            "Move an event.",
            {"type": "object", "properties": {"when": {"type": "string"}}},
            ActionRisk.REVERSIBLE,
            lambda a: self.moves.append(self.guests),
            preview=preview,
        )


@dataclass
class Rig:
    client: AsyncClient
    provider: MockProvider
    world: InMemoryWorld
    calendar: Calendar
    clock: Clock
    auth: SoftAuthenticator
    app: Any

    def irreversible_runs(self) -> int:
        """Sends, plus event moves that emailed guests."""
        return len(self.world.sent) + sum(self.calendar.moves)

    async def sign_in(self, *, reauth: bool = True) -> None:
        async def google(request: Any) -> dict[str, Any]:
            return {"userinfo": {"email": OWNER, "email_verified": True, "sub": "1"}}

        self.app.state.oauth.google.authorize_access_token = google
        if reauth:
            await self.client.get("/auth/login?reauth=1")
        r = await self.client.get("/auth/callback?code=x&state=y")
        assert r.status_code == 302, r.text

    def cli(self) -> AsyncClient:
        """The command line: the bearer token, no browser cookie."""
        return AsyncClient(transport=ASGITransport(app=self.app), base_url=ORIGIN, headers=BEARER)

    async def register(self, label: str = "Laptop", **body: Any) -> dict[str, Any]:
        r = await self.client.post("/v1/passkeys/register/options", json=body)
        r.raise_for_status()
        opts = r.json()
        cred = self.auth.create(opts["public_key"])
        r = await self.client.post(
            "/v1/passkeys/register",
            json={"challenge_id": opts["challenge_id"], "credential": cred, "label": label},
        )
        r.raise_for_status()
        return dict(r.json())

    async def proof(self, get_kw: dict[str, Any] | None = None, **req: Any) -> dict[str, Any]:
        r = await self.client.post("/v1/passkeys/challenge", json=req)
        r.raise_for_status()
        ch = r.json()
        return {
            "challenge_id": ch["challenge_id"],
            "credential": self.auth.get(ch["public_key"], **(get_kw or {})),
        }

    async def card(self, tool: str = "send_message", **over: Any) -> tuple[str, str]:
        """A waiting approval card for `tool`, made by a (mock) model turn."""
        base = {
            "send_message": {"to": "priya@example.com", "body": "3pm works"},
            "calendar_update_event": {"when": "15:00"},
        }.get(tool, {"text": "call the bank", "when": "17:00"})
        args = base | over
        self.provider.script_tool_calls([ToolCall(id="c1", name=tool, arguments=args)], "Waiting.")
        r = await self.client.post("/v1/chat", json={"message": "please do it"})
        r.raise_for_status()
        body = r.json()
        cards = body["pending_approvals"]
        if not cards:
            raise AssertionError("no approval card was made")
        return str(cards[0]["id"]), str(body["session_id"])

    async def approve(
        self, pid: str, sid: str, proof: dict[str, Any] | None = None, *, cli: bool = False
    ) -> Any:
        self.provider.script("Done, Sir.")
        body: dict[str, Any] = {"session_id": sid}
        if proof is not None:
            body["passkey"] = proof
        if cli:
            async with self.cli() as c:
                return await c.post(f"/v1/approvals/{pid}/approve", json=body)
        return await self.client.post(f"/v1/approvals/{pid}/approve", json=body)


@asynccontextmanager
async def rig(*, origin: str = ORIGIN, passkey: bool = True) -> AsyncIterator[Rig]:
    """The owner signed in again (fresh) and — unless `passkey=False` — with a first passkey."""
    s = settings()
    provider = MockProvider()
    world, calendar = InMemoryWorld(), Calendar()
    reg = ToolRegistry()
    for t in [*builtin_tools(world), calendar.tool()]:
        reg.register(t)
    gw = Gateway(registry=reg, policy=Policy(), gate=ConfirmationGate(), audit=AuditLog())
    app = create_app(s, provider=provider, store=InMemorySessionStore(), gateway=gw)
    clock = Clock()
    async with app.router.lifespan_context(app):
        svc = app.state.permissions
        svc._clock = clock  # noqa: SLF001 — the eval moves time; production uses the wall clock
        svc.challenges._clock = clock  # noqa: SLF001
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url=ORIGIN, headers=CSRF
        ) as c:
            r = Rig(c, provider, world, calendar, clock, SoftAuthenticator(origin=origin), app)
            await r.sign_in()
            if passkey:
                await r.register()
            yield r


@dataclass
class Recorder:
    results: list[dict[str, Any]] = field(default_factory=list)

    def case(self, cid: str, why: str, checks: list[tuple[bool, str]]) -> None:
        failures = [msg for ok, msg in checks if not ok]
        self.results.append({"id": cid, "why": why, "passed": not failures, "failures": failures})

    def summary(self, **extra: Any) -> dict[str, Any]:
        n = len(self.results)
        passed = sum(1 for r in self.results if r["passed"])
        return {
            "cases": n,
            "pass_rate": passed / n if n else 0.0,
            "results": self.results,
            **extra,
        }


Check = Callable[[], bool]

__all__ = ["BEARER", "CSRF", "ORIGIN", "Calendar", "Clock", "Recorder", "Rig", "rig", "settings"]
