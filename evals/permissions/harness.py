# evals/permissions/harness.py
"""Shared rig for the slice 10 D permission evals: the real app (mock brain, in-process storage,
built-in dev tools), a software authenticator, a movable clock, and a case recorder.
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
from jarvis.config import LLMBackend, SessionBackend, Settings
from jarvis.core.guardrails import ConfirmationGate
from jarvis.llm.base import ToolCall
from jarvis.llm.mock_provider import MockProvider
from jarvis.memory.inmemory import InMemorySessionStore
from jarvis.tools import AuditLog, Gateway, Policy, ToolRegistry
from jarvis.tools.builtin import InMemoryWorld, builtin_tools

ORIGIN = "http://jarvis.local"  # the relying party: RP ID "jarvis.local"
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
class Rig:
    client: AsyncClient
    provider: MockProvider
    world: InMemoryWorld
    clock: Clock
    auth: SoftAuthenticator
    app: Any

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
        args = (
            {"to": "priya@example.com", "body": "3pm works"}
            if tool == "send_message"
            else {"text": "call the bank", "when": "17:00"}
        ) | over
        self.provider.script_tool_calls([ToolCall(id="c1", name=tool, arguments=args)], "Waiting.")
        r = await self.client.post("/v1/chat", json={"message": "please do it"})
        r.raise_for_status()
        body = r.json()
        cards = body["pending_approvals"]
        if not cards:
            raise AssertionError("no approval card was made")
        return str(cards[0]["id"]), str(body["session_id"])

    async def approve(
        self, pid: str, sid: str, proof: dict[str, Any] | None = None, **headers: str
    ) -> Any:
        self.provider.script("Done, Sir.")
        body: dict[str, Any] = {"session_id": sid}
        if proof is not None:
            body["passkey"] = proof
        return await self.client.post(
            f"/v1/approvals/{pid}/approve", json=body, headers=headers or None
        )


@asynccontextmanager
async def rig(*, origin: str = ORIGIN) -> AsyncIterator[Rig]:
    s = settings()
    provider = MockProvider()
    world = InMemoryWorld()
    reg = ToolRegistry()
    for t in builtin_tools(world):
        reg.register(t)
    gw = Gateway(registry=reg, policy=Policy(), gate=ConfirmationGate(), audit=AuditLog())
    app = create_app(s, provider=provider, store=InMemorySessionStore(), gateway=gw)
    clock = Clock()
    async with app.router.lifespan_context(app):
        svc = app.state.permissions
        svc._clock = clock  # noqa: SLF001 — the eval moves time; production uses the wall clock
        svc.challenges._clock = clock  # noqa: SLF001
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url=ORIGIN, headers={**CSRF, **BEARER}
        ) as c:
            yield Rig(c, provider, world, clock, SoftAuthenticator(origin=origin), app)


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

__all__ = ["BEARER", "CSRF", "ORIGIN", "Clock", "Recorder", "Rig", "rig", "settings"]
