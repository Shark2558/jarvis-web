# tests/offline_fakes.py -- shared fakes for the R1 C (offline mode) tests: a scripted "laptop"
# (httpx.MockTransport), a recording alert sink, a manual clock and a ready-made LocalFallback.
from __future__ import annotations

import json
import os
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

import httpx
from pydantic import SecretStr

from jarvis.alerts import AlertKind, AlertResult
from jarvis.integrations.vault import TokenCipher
from jarvis.offline.service import LocalFallback
from jarvis.offline.store import LocalBrainStore
from jarvis.storage.docs import MemoryDocs

URL = "https://laptop.tail1234.ts.net/v1"
KEY = "Zk3y-laptop-secret-0123456789abcdef"
MODEL = "qwen2.5:7b"
OWNER = "u_owner"
T0 = datetime(2026, 11, 5, 9, 0, tzinfo=UTC)


class Clock:
    def __init__(self) -> None:
        self.t = 10_000.0

    def __call__(self) -> float:
        return self.t


class Alerts:
    """Records alerts; `fail` makes send raise (the service must shrug)."""

    def __init__(self, *, fail: bool = False, sent: bool = True) -> None:
        self.sent: list[tuple[str, str, AlertKind]] = []
        self.fail = fail
        self.result = sent

    async def send(self, uid: str, text: str, *, kind: AlertKind) -> AlertResult:
        if self.fail:
            raise RuntimeError("telegram down")
        self.sent.append((uid, text, kind))
        return AlertResult(sent=self.result)


class Laptop:
    """The owner's laptop behind the tunnel: answers /chat/completions and /models."""

    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []
        self.up = True
        self.models = [MODEL]
        self.status: int | None = None  # force one HTTP status for every request
        self.reply: dict[str, Any] | None = None  # force the chat message
        self.queue: list[dict[str, Any]] = []  # one-shot chat messages, used before `reply`
        self.delay_s = 0.0

    def completion(self, text: str = "Right away, Sir.", tool_calls: list[Any] | None = None):  # type: ignore[no-untyped-def]
        msg: dict[str, Any] = {"role": "assistant", "content": text}
        if tool_calls:
            msg["tool_calls"] = tool_calls
        return {"choices": [{"message": msg, "finish_reason": "stop"}], "usage": {}}

    def handler(self) -> Callable[[httpx.Request], Any]:
        async def h(req: httpx.Request) -> httpx.Response:
            self.requests.append(req)
            if self.delay_s:
                import asyncio

                await asyncio.sleep(self.delay_s)
            if not self.up:
                raise httpx.ConnectError("laptop asleep")
            if self.status is not None:
                return httpx.Response(self.status, json={"error": {"message": f"x {KEY}"}})
            if req.url.path.endswith("/models"):
                return httpx.Response(200, json={"data": [{"id": m} for m in self.models]})
            body = self.queue.pop(0) if self.queue else (self.reply or self.completion())
            if json.loads(req.content or b"{}").get("stream"):
                chunks = "".join(
                    "data: " + json.dumps({"choices": [{"delta": {"content": w}}]}) + "\n\n"
                    for w in ("lap ", "top ")
                )
                return httpx.Response(200, content=(chunks + "data: [DONE]\n\n").encode())
            return httpx.Response(200, json=body)

        return h

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handler())

    def chats(self) -> list[dict[str, Any]]:
        return [
            json.loads(r.content) for r in self.requests if r.url.path.endswith("/chat/completions")
        ]


def public_resolver(ips: list[str] | None = None):  # type: ignore[no-untyped-def]
    box = {"ips": ips or ["8.8.8.8"]}

    async def r(host: str) -> list[str]:
        return list(box["ips"])

    r.box = box  # type: ignore[attr-defined]
    return r


class Rig:
    """A LocalFallback over MemoryDocs with a scripted laptop; configured and switched on."""

    def __init__(self, *, configured: bool = True, enabled: bool = True, timeout_s: float = 5.0):
        self.docs = MemoryDocs()
        self.cipher = TokenCipher(bytes(range(32)))
        self.store = LocalBrainStore(self.docs, self.cipher, now=lambda: T0)
        self.laptop = Laptop()
        self.alerts = Alerts()
        self.clock = Clock()
        self.resolver = public_resolver()
        self.svc = LocalFallback(
            self.store,
            alerts=self.alerts,
            timeout_s=timeout_s,
            resolver=self.resolver,
            transport=self.laptop.transport(),
            clock=self.clock,
            now=lambda: T0,
        )
        self._configured = configured
        self._enabled = enabled

    async def ready(self) -> Rig:
        if self._configured:
            await self.store.put(
                url=URL, key=SecretStr(KEY), model=MODEL, enabled=self._enabled, set_by=OWNER
            )
        return self


def random_cipher() -> TokenCipher:
    return TokenCipher(os.urandom(32))
