# evals/r13/wired.py
"""R13 I1: the four parts through the REAL app, for the `e2e` and `needles` suites (not a suite
itself: the runner loads only the names in `run.PARTS`).

`running()` builds `create_app` with the owner's token and a token key (so A is on), a FIXED clock
(`app.state.wardrobe_now`, the wardrobe's one clock), a recording notifier and a recording log
handler, and starts the app's lifespan. A `World` then calls the 18 tools through the real gateway
(cards approved exactly as he saw them) and reads the panel's routes through the real HTTP stack.

Everything is in memory: no Firestore, no Google, no network, no provider call.
"""

from __future__ import annotations

import base64
import json
import logging
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))
from httpx import ASGITransport, AsyncClient  # noqa: E402
from pydantic import SecretStr  # noqa: E402
from r13_fakes import FixedClock, ist  # noqa: E402

from jarvis.api import create_app  # noqa: E402
from jarvis.api.identity import primary_user_id  # noqa: E402
from jarvis.api.r13_wiring import wardrobe_store  # noqa: E402
from jarvis.config import LLMBackend, SessionBackend, Settings  # noqa: E402
from jarvis.llm.base import ToolCall  # noqa: E402
from jarvis.llm.mock_provider import MockProvider  # noqa: E402
from jarvis.memory.inmemory import InMemorySessionStore  # noqa: E402
from jarvis.notify.ports import Delivery, Signal  # noqa: E402
from jarvis.tools.budget import turn_budget  # noqa: E402
from jarvis.tools.gateway import GatewayOutcome, GatewayResult  # noqa: E402
from jarvis.tools.taint import context_trust  # noqa: E402

TOKEN = "t" * 40
AUTH = {"Authorization": f"Bearer {TOKEN}"}
KEY = bytes(range(64, 96))
SCOPE = "eval"


class Recorder(logging.Handler):
    """Every log record: its message and every extra field, as text."""

    def __init__(self) -> None:
        super().__init__(logging.DEBUG)
        self.lines: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.lines.append(json.dumps(record.__dict__, default=str) + record.getMessage())


@dataclass
class Alerts:
    sent: list[tuple[str, str]] = field(default_factory=list)

    async def notify(self, uid: str, signal: Signal, message: str, **_: Any) -> Delivery:
        self.sent.append((signal.kind, message))
        return Delivery(action="ring", reason="eval")


def owner_settings() -> Settings:
    return Settings(
        _env_file=None,
        env="prod",
        llm_backend=LLMBackend.MOCK,
        session_backend=SessionBackend.MEMORY,
        usd_inr_live=False,
        api_token=SecretStr(TOKEN),
        token_key=SecretStr(base64.b64encode(KEY).decode()),
    )


@dataclass
class World:
    app: Any
    client: AsyncClient
    clock: FixedClock
    alerts: Alerts
    log: Recorder
    uid: str
    results: list[Any] = field(default_factory=list)  # every tool result the model would see
    planted: list[tuple[str, bool]] = field(default_factory=list)  # (what was planted, accepted)

    @property
    def store(self) -> Any:
        store = wardrobe_store(self.app)
        assert store is not None, "the wardrobe is off in this app"
        return store

    @property
    def docs(self) -> Any:
        return self.store.docs

    async def call(
        self, name: str, *, spoken: bool = False, untrusted: bool = False, **args: Any
    ) -> GatewayResult:
        gw = self.app.state.gateway
        call = ToolCall(id=f"e{len(self.results)}", name=name, arguments=dict(args))
        with turn_budget(), context_trust(untrusted=untrusted, spoken=spoken, owner_text=None):
            res = await gw.execute(call, scope=f"{self.uid}:{SCOPE}")
        self.results.append(res.result if res.result is not None else res.error)
        return res

    async def ok(self, name: str, **args: Any) -> dict[str, Any]:
        """A call that runs now (a card is approved as he saw it); its result."""
        res = await self.call(name, **args)
        if res.outcome is GatewayOutcome.AWAITING_CONFIRMATION and res.pending is not None:
            res = await self.approve(res)
        assert res.outcome is GatewayOutcome.EXECUTED, (name, args, res.outcome, res.error)
        assert isinstance(res.result, dict), (name, res.result)
        return res.result

    async def approve(self, asked: GatewayResult) -> GatewayResult:
        card = asked.pending
        assert card is not None
        again = ToolCall(id="approve", name=card.tool, arguments=card.arguments)
        gw = self.app.state.gateway
        with turn_budget(), context_trust(untrusted=False, spoken=False, owner_text=None):
            res = await gw.execute(again, confirmation_id=card.id, scope=f"{self.uid}:{SCOPE}")
        self.results.append(res.result if res.result is not None else res.error)
        return res

    async def get(self, path: str) -> Any:
        got = await self.client.get(path, headers=AUTH)
        assert got.status_code == 200, (path, got.status_code, got.text[:200])
        return got.json()

    async def send(self, method: str, path: str, **kw: Any) -> Any:
        return await self.client.request(
            method, path, headers={**AUTH, **kw.pop("headers", {})}, **kw
        )

    async def pieces(self) -> dict[str, dict[str, Any]]:
        view = await self.get("/v1/wardrobe?private=1")
        return {p["id"]: p for p in view["pieces"]}

    async def state(self, pid: str) -> str:
        return str((await self.pieces())[pid]["state"])


@asynccontextmanager
async def running(at: datetime | None = None) -> AsyncIterator[World]:
    """The real app, started, on a fixed clock (default Mon 16 Nov 2026, 10:00 IST)."""
    s = owner_settings()
    app = create_app(s, provider=MockProvider(), store=InMemorySessionStore())
    clock = FixedClock(at or ist(2026, 11, 16, 10, 0))
    app.state.wardrobe_now = clock
    log = Recorder()
    logging.getLogger().addHandler(log)
    try:
        async with app.router.lifespan_context(app):
            alerts = Alerts()
            app.state.notify = alerts
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                yield World(app, client, clock, alerts, log, primary_user_id(s))
    finally:
        logging.getLogger().removeHandler(log)


def want(ok: bool, words: str) -> list[str]:
    """A failure line when `ok` is false (the suites' one assertion)."""
    return [] if ok else [words]


__all__ = ["AUTH", "Alerts", "World", "running", "want"]
