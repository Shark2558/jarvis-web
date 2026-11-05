# tests/r3_app.py -- R3 I1: the WHOLE app as `create_app` wires it (api/home_wiring.py), with the
# token key, a paired Telegram owner whose Bot API calls are recorded (never sent), a linked home
# whose laptop is asleep (every call to it fails like a closed lid), and helpers that sign events
# the way the bridge does. Shared by tests/test_r3_wiring.py and evals/r3_needles.
from __future__ import annotations

import base64
import json
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any

import httpx
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr

from jarvis.api import create_app
from jarvis.config import LLMBackend, SessionBackend, Settings
from jarvis.home import signing
from jarvis.home.ports import WEBHOOK_PATH
from jarvis.llm.mock_provider import MockProvider
from jarvis.llm.router import ModelTier
from jarvis.memory.inmemory import InMemorySessionStore
from jarvis.storage.docs import MemoryDocs

KEY = SecretStr(base64.b64encode(bytes(range(1, 33))).decode())
UID = "owner"
H = {"X-Requested-With": "JARVIS"}
HOME_ID = "h_0a1b2c3d"
BRIDGE_URL = "https://laptop.tail1234.ts.net:8443"
SEED = bytes(range(101, 133))  # the link seed: never in a document, log or audit entry
CHAT_ID = 4242
TIERS = {
    ModelTier.FAST: "mock-fast",
    ModelTier.BALANCED: "mock-balanced",
    ModelTier.STRONG: "mock-strong",
}


def r3_settings(**over: Any) -> Settings:
    base: dict[str, Any] = {
        "_env_file": None,
        "env": "dev",
        "llm_backend": LLMBackend.MOCK,
        "session_backend": SessionBackend.MEMORY,
        "model_fast": TIERS[ModelTier.FAST],
        "model_balanced": TIERS[ModelTier.BALANCED],
        "model_strong": TIERS[ModelTier.STRONG],
        "usd_inr_live": False,
        "token_key": KEY,
        "tools_enabled": True,
        "telegram_bot_token": SecretStr("123:bot-token-for-tests"),
        "telegram_webhook_secret": SecretStr("webhook-secret-for-tests"),
        "public_base_url": "https://jarvis-abc.a.run.app",
    }
    return Settings(**{**base, **over})


@dataclass
class R3App:
    app: Any
    client: AsyncClient
    docs: MemoryDocs
    telegram: list[httpx.Request] = field(default_factory=list)
    clock: list[float] = field(default_factory=lambda: [time.time()])

    @property
    def state(self) -> Any:
        return self.app.state

    def sent_texts(self) -> list[str]:
        """Every text and caption Telegram was asked to show."""
        out: list[str] = []
        for req in self.telegram:
            if req.url.path.endswith("/sendMessage"):
                out.append(json.loads(req.content)["text"])
            elif req.url.path.endswith("/sendPhoto"):
                out.append(req.content.decode("latin-1"))
        return out

    def photos(self) -> list[bytes]:
        return [r.content for r in self.telegram if r.url.path.endswith("/sendPhoto")]

    async def event(self, event: dict[str, Any]) -> httpx.Response:
        """POST one event to /home/webhook, signed with the home's up key like the bridge."""
        body = json.dumps(event, separators=(",", ":")).encode()
        header = signing.sign(
            signing.derive_keys(SEED),
            "up",
            home_id=HOME_ID,
            method="POST",
            target=WEBHOOK_PATH,
            body=body,
            now=time.time(),
        )
        return await self.client.post(
            WEBHOOK_PATH,
            content=body,
            headers={signing.HEADER: header, "content-type": "application/json"},
        )


def _telegram_fake(calls: list[httpx.Request]) -> httpx.AsyncClient:
    def handler(request: httpx.Request) -> httpx.Response:
        request.read()
        calls.append(request)
        if request.url.path.endswith("/getMe"):
            return httpx.Response(200, json={"ok": True, "result": {"username": "jarvis_bot"}})
        return httpx.Response(200, json={"ok": True, "result": {"message_id": len(calls)}})

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def _laptop_asleep() -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("the laptop is asleep")

    return httpx.MockTransport(handler)


async def _public(host: str) -> list[str]:
    return ["100.64.10.20"]


@asynccontextmanager
async def r3_app(settings: Settings | None = None, *, link: bool = True) -> AsyncIterator[R3App]:
    s = settings or r3_settings()
    app = create_app(s, provider=MockProvider(), store=InMemorySessionStore())
    async with app.router.lifespan_context(app):
        calls: list[httpx.Request] = []
        tg = app.state.telegram
        if tg is not None:
            await tg.client.aclose()
            tg.client._http = _telegram_fake(calls)  # noqa: SLF001 - record, never send
            code, _ = await tg.store.start_pairing(UID)
            await tg.store.finish_pairing(code, tg_user_id=77, chat_id=CHAT_ID)
        docs = app.state.home_store._d if app.state.home_store is not None else MemoryDocs()  # noqa: SLF001
        if app.state.home_client is not None:
            app.state.home_client._inner = _laptop_asleep()  # noqa: SLF001
            app.state.home_client._resolver = _public  # noqa: SLF001
        if link and app.state.home_store is not None:
            await app.state.home_store.link(UID, HOME_ID, BRIDGE_URL, SEED)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            yield R3App(app, c, docs, calls)


def heartbeat(**parts: Any) -> dict[str, Any]:
    return {
        "type": "heartbeat",
        "id": f"hb-{time.time_ns()}",
        "at": time.time(),
        "bridge_version": "0.1.0",
        "state_rev": 0,
        "parts": {"ha": False, "frigate": True, **parts},
    }


def detection(**over: Any) -> dict[str, Any]:
    now = time.time()
    return {
        "type": "detection",
        "id": f"det:{time.time_ns()}",
        "camera": "gate",
        "zones": ["gate"],
        "label": "person",
        "start": now,
        "score": 0.91,
        **over,
    }


__all__ = [
    "BRIDGE_URL",
    "CHAT_ID",
    "H",
    "HOME_ID",
    "KEY",
    "SEED",
    "UID",
    "R3App",
    "detection",
    "heartbeat",
    "r3_app",
    "r3_settings",
]
