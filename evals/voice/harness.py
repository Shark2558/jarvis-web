# evals/voice/harness.py
"""Shared rig for the slice 9 voice evals: settings, scripted engines, a Google-shaped transport,
WAV builders and an app client. Self-contained (evals never import from tests/)."""

from __future__ import annotations

import base64
import math
import struct
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any

import httpx
from httpx import ASGITransport, AsyncClient

from jarvis.api import create_app
from jarvis.config import LLMBackend, SessionBackend, Settings
from jarvis.llm.mock_provider import MockProvider
from jarvis.memory.inmemory import InMemorySessionStore
from jarvis.voice.catalogue import VOICES
from jarvis.voice.ports import Transcript, VoiceUnavailable
from jarvis.voice.service import VoiceEngines

UID = "owner"  # dev / token mode
RATE = 95.24
WAV = {"Content-Type": "audio/wav"}


def settings(**kw: Any) -> Settings:
    return Settings(
        _env_file=None,
        env="dev",
        llm_backend=LLMBackend.MOCK,
        session_backend=SessionBackend.MEMORY,
        usd_inr_live=False,
        log_level="CRITICAL",  # create_app configures logging from this
        **kw,
    )


def wav(
    seconds: float = 1.0,
    *,
    rate: int = 16_000,
    channels: int = 1,
    bits: int = 16,
    fmt: int = 1,
    data: bytes | None = None,
) -> bytes:
    body = data if data is not None else b"\x01\x00" * channels * int(seconds * rate)
    block = channels * bits // 8
    fields = struct.pack("<IHHIIHH", 16, fmt, channels, rate, rate * block, block, bits)
    payload = b"WAVE" + b"fmt " + fields + b"data" + struct.pack("<I", len(body)) + body
    return b"RIFF" + struct.pack("<I", len(payload)) + payload


class Tokens:
    def __init__(self, *, missing: bool = False) -> None:
        self.missing = missing
        self.invalidated = 0

    async def headers(self) -> dict[str, str]:
        if self.missing:
            raise VoiceUnavailable("not_configured")
        return {"Authorization": "Bearer eval-token"}

    def invalidate(self) -> None:
        self.invalidated += 1

    @property
    def not_configured(self) -> bool:
        return self.missing


@dataclass
class ScriptedTTS:
    calls: list[dict[str, Any]] = field(default_factory=list)

    async def synthesize(self, text: str, *, voice: str, language: str, rate: float) -> bytes:
        self.calls.append({"chars": len(text), "voice": voice})
        return b"ID3eval"

    async def voices(self, language: str) -> frozenset[str]:
        return frozenset(v.id for v in VOICES)


@dataclass
class ScriptedSTT:
    calls: list[int] = field(default_factory=list)

    async def recognize(
        self, pcm: bytes, *, sample_rate: int, language: str, phrases: tuple[str, ...]
    ) -> Transcript:
        self.calls.append(len(pcm))
        return Transcript("set a timer", 0.9, float(math.ceil(len(pcm) / (2 * sample_rate))), None)


class GoogleShaped:
    """An httpx transport answering like Google's speech APIs, scriptable per path."""

    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []
        self.routes: dict[str, Callable[[httpx.Request], httpx.Response]] = {
            "/v1/text:synthesize": lambda r: httpx.Response(
                200, json={"audioContent": base64.b64encode(b"ID3ok").decode()}
            ),
            "/v1/voices": lambda r: httpx.Response(
                200, json={"voices": [{"name": v.id} for v in VOICES]}
            ),
            "/v1/speech:recognize": lambda r: httpx.Response(
                200,
                json={
                    "results": [{"alternatives": [{"transcript": "ok", "confidence": 0.9}]}],
                    "totalBilledTime": "1s",
                },
            ),
        }

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return self.routes[request.url.path](request)

    def client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=httpx.MockTransport(self))


@asynccontextmanager
async def app_client(engines: VoiceEngines, **overrides: Any) -> AsyncIterator[AsyncClient]:
    app = create_app(
        settings(**overrides),
        provider=MockProvider(),
        store=InMemorySessionStore(),
        voice_engines=engines,
    )
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://eval") as c:
            c.app = app  # type: ignore[attr-defined]
            yield c


__all__ = [
    "RATE",
    "UID",
    "WAV",
    "GoogleShaped",
    "ScriptedSTT",
    "ScriptedTTS",
    "Tokens",
    "app_client",
    "settings",
    "wav",
]
