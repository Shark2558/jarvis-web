# tests/telegram_fakes.py -- a fake Telegram Bot API (httpx.MockTransport) and a small world
# (Brain + Gateway + store + service) for the R1 Telegram tests. Never imported from conftest.
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
from pydantic import SecretStr

from jarvis.config import LLMBackend, SessionBackend, Settings
from jarvis.core.brain import Brain
from jarvis.core.guardrails import ConfirmationGate
from jarvis.llm.mock_provider import MockProvider
from jarvis.llm.router import ModelRouter, ModelTier
from jarvis.memory.inmemory import InMemorySessionStore
from jarvis.storage.docs import MemoryDocs
from jarvis.telegram.client import TelegramClient
from jarvis.telegram.models import parse_update
from jarvis.telegram.rules import wrap_rules
from jarvis.telegram.service import TelegramService
from jarvis.telegram.store import TelegramStore
from jarvis.tools import AuditLog, Gateway, Policy, ToolRegistry
from jarvis.tools.base import Tool
from jarvis.tools.builtin import InMemoryWorld, builtin_tools

TOKEN = "123456789:AAH-secret-token-value_xyz"
SECRET = "hook-secret-0123456789abcdefghij"
OWNER_TG = 555001234
OWNER_CHAT = 555001234
STRANGER_TG = 777000111
UID = "owner"
TIERS = {t: f"mock-{t.value}" for t in ModelTier}
NOW = datetime(2027, 1, 15, 3, 0, tzinfo=UTC)


class Clock:
    """A settable clock the store, the service and the alerts share."""

    def __init__(self, now: datetime = NOW) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now

    def advance(self, **kw: float) -> None:
        self.now = self.now + timedelta(**kw)


class FakeBot:
    """Records every Bot API call; answers like Telegram. `fail` makes methods return ok:false."""

    def __init__(self, username: str = "jarvis_test_bot") -> None:
        self.username = username
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.paths: list[str] = []
        self.fail: set[str] = set()
        self.raise_transport = False
        self.status = 200
        self.pending = 0
        self.webhook_url = "https://example.test/telegram/webhook"
        self.webhook_error = False
        self.big = False
        self._next = 100

    def _reply(self, method: str, payload: dict[str, Any]) -> dict[str, Any]:
        if method in self.fail:
            return {"ok": False, "error_code": 400, "description": "Bad Request: VENDOR TEXT"}
        if method == "getMe":
            return {"ok": True, "result": {"id": 1, "is_bot": True, "username": self.username}}
        if method == "sendMessage":
            self._next += 1
            return {"ok": True, "result": {"message_id": self._next}}
        if method == "getWebhookInfo":
            info: dict[str, Any] = {"url": self.webhook_url, "pending_update_count": self.pending}
            if self.webhook_error:
                info["last_error_message"] = "Wrong response from the webhook: 500 VENDOR"
            return {"ok": True, "result": info}
        return {"ok": True, "result": True}

    def handle(self, request: httpx.Request) -> httpx.Response:
        if self.raise_transport:
            raise httpx.ConnectError("boom " + str(request.url))
        self.paths.append(request.url.path)
        method = request.url.path.rsplit("/", 1)[1]
        payload = json.loads(request.content) if request.content else {}
        self.calls.append((method, payload))
        if self.big:
            return httpx.Response(200, content=b"x" * 1_100_000)
        if self.status in (301, 302):
            return httpx.Response(self.status, headers={"location": "https://evil.example/"})
        return httpx.Response(self.status, json=self._reply(method, payload))

    def client(self) -> TelegramClient:
        http = httpx.AsyncClient(transport=httpx.MockTransport(self.handle))
        return TelegramClient(SecretStr(TOKEN), http=http)

    def of(self, method: str) -> list[dict[str, Any]]:
        return [p for m, p in self.calls if m == method]

    @property
    def texts(self) -> list[str]:
        return [str(p.get("text", "")) for p in self.of("sendMessage")]


def message(
    update_id: int,
    text: str | None = "hello",
    *,
    user: int = OWNER_TG,
    chat: int = OWNER_CHAT,
    chat_type: str = "private",
    is_bot: bool = False,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    msg: dict[str, Any] = {
        "message_id": update_id,
        "date": 1_800_000_000,
        "from": {"id": user, "is_bot": is_bot, "first_name": "X"},
        "chat": {"id": chat, "type": chat_type},
    }
    if text is not None:
        msg["text"] = text
    msg.update(extra or {})
    return {"update_id": update_id, "message": msg}


def callback(
    update_id: int,
    data: str,
    *,
    user: int = OWNER_TG,
    chat: int = OWNER_CHAT,
    message_id: int = 7,
) -> dict[str, Any]:
    return {
        "update_id": update_id,
        "callback_query": {
            "id": f"cb{update_id}",
            "from": {"id": user, "is_bot": False, "first_name": "X"},
            "message": {"message_id": message_id, "chat": {"id": chat, "type": "private"}},
            "data": data,
        },
    }


def dev_settings(**kw: Any) -> Settings:
    base: dict[str, Any] = {
        "_env_file": None,
        "env": "dev",
        "llm_backend": LLMBackend.MOCK,
        "session_backend": SessionBackend.MEMORY,
        "model_fast": TIERS[ModelTier.FAST],
        "model_balanced": TIERS[ModelTier.BALANCED],
        "model_strong": TIERS[ModelTier.STRONG],
        "max_input_chars": 500,
        "usd_inr_live": False,
    }
    base.update(kw)
    return Settings(**base)


@dataclass
class World:
    bot: FakeBot
    docs: MemoryDocs
    store: TelegramStore
    service: TelegramService
    brain: Brain
    provider: MockProvider
    gateway: Gateway
    audit: AuditLog
    things: InMemoryWorld
    clock: Clock

    async def pair(self, tg: int = OWNER_TG, chat: int = OWNER_CHAT, uid: str = UID) -> None:
        code, _ = await self.store.start_pairing(uid)
        assert await self.store.finish_pairing(code, tg_user_id=tg, chat_id=chat) == uid

    async def send(self, update: dict[str, Any]) -> None:
        parsed = parse_update(update)
        assert parsed is not None
        await self.service.handle(parsed)

    def audited(self, tool: str) -> list[Any]:
        return [e for e in self.audit._entries if e.tool == tool]


def build_world(
    *,
    policy: Policy | None = None,
    extra_tools: list[Tool] | None = None,
    rules: Any = "wired",
) -> World:
    bot = FakeBot()
    docs = MemoryDocs()
    audit = AuditLog()
    things = InMemoryWorld()
    clock = Clock()
    reg = ToolRegistry()
    for t in [*builtin_tools(things), *(extra_tools or [])]:
        reg.register(t)
    gateway = Gateway(registry=reg, policy=policy or Policy(), gate=ConfirmationGate(), audit=audit)
    provider = MockProvider()
    brain = Brain(
        router=ModelRouter(provider, TIERS),
        store=InMemorySessionStore(ttl_s=3600),
        settings=dev_settings(),
        gateway=gateway,
    )
    store = TelegramStore(docs, prefix="jarvis_", clock=clock)
    # "wired" is the one supported way (what the app does): rules wrapped by wrap_rules
    gateway.rules = wrap_rules(None, store) if rules == "wired" else rules
    service = TelegramService(bot.client(), store, audit, brain=brain, clock=clock)
    return World(bot, docs, store, service, brain, provider, gateway, audit, things, clock)
