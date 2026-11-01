# tests/voice_fakes.py — slice 9 helpers: WAV builders, a fake token source, fake TTS / STT
# engines and a scripted Google transport. A plain module (not conftest) so test files and the
# voice evals import it.
from __future__ import annotations

import asyncio
import base64
import json
import math
import struct
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import httpx

from jarvis.voice.ports import Transcript, VoiceUnavailable

RATE = 16_000


def pcm(seconds: float, *, rate: int = RATE, channels: int = 1, freq: float = 440.0) -> bytes:
    """A tone as 16-bit little-endian PCM."""
    n = int(seconds * rate)
    frames = []
    for i in range(n):
        v = int(8000 * math.sin(2 * math.pi * freq * i / rate))
        frames.append(struct.pack("<h", v) * channels)
    return b"".join(frames)


def wav(
    seconds: float = 1.0,
    *,
    rate: int = RATE,
    channels: int = 1,
    bits: int = 16,
    fmt: int = 1,
    extra_chunks: bytes = b"",
    data: bytes | None = None,
) -> bytes:
    """A RIFF/WAVE file; every field can be made wrong on purpose."""
    body = data if data is not None else pcm(seconds, rate=rate, channels=channels)
    block = channels * bits // 8
    fields = struct.pack("<IHHIIHH", 16, fmt, channels, rate, rate * block, block, bits)
    fmt_chunk = b"fmt " + fields
    data_chunk = b"data" + struct.pack("<I", len(body)) + body
    payload = b"WAVE" + fmt_chunk + extra_chunks + data_chunk
    return b"RIFF" + struct.pack("<I", len(payload)) + payload


class FakeTokens:
    def __init__(self, *, missing: bool = False) -> None:
        self.missing = missing
        self.calls = 0
        self.invalidated = 0

    async def headers(self) -> dict[str, str]:
        self.calls += 1
        if self.missing:
            raise VoiceUnavailable("not_configured")
        return {"Authorization": "Bearer test-token"}

    def invalidate(self) -> None:
        self.invalidated += 1

    @property
    def not_configured(self) -> bool:
        return self.missing


@dataclass
class FakeTTS:
    """Records what it was asked to say (in memory only) and returns fixed MP3-ish bytes."""

    known: frozenset[str] | None = None
    fail: Exception | None = None
    voices_fail: Exception | None = None
    calls: list[dict[str, Any]] = field(default_factory=list)
    voice_lists: int = 0
    delay: float = 0.0  # seconds each synthesis takes (lets calls overlap)
    voices_delay: float = 0.0

    async def synthesize(self, text: str, *, voice: str, language: str, rate: float) -> bytes:
        self.calls.append({"text": text, "voice": voice, "language": language, "rate": rate})
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.fail is not None:
            raise self.fail
        return b"ID3" + text.encode("utf-8")[:16]

    async def voices(self, language: str) -> frozenset[str]:
        self.voice_lists += 1
        if self.voices_delay:
            await asyncio.sleep(self.voices_delay)
        if self.voices_fail is not None:
            raise self.voices_fail
        if self.known is not None:
            return self.known
        from jarvis.voice.catalogue import VOICES

        return frozenset(v.id for v in VOICES)


@dataclass
class FakeSTT:
    text: str = "what's on my calendar today"
    confidence: float | None = 0.93
    billed: float | None = None
    fail: Exception | None = None
    calls: list[dict[str, Any]] = field(default_factory=list)
    delay: float = 0.0

    async def recognize(
        self, pcm: bytes, *, sample_rate: int, language: str, phrases: tuple[str, ...]
    ) -> Transcript:
        self.calls.append(
            {"bytes": len(pcm), "rate": sample_rate, "language": language, "phrases": phrases}
        )
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.fail is not None:
            raise self.fail
        billed = self.billed if self.billed is not None else math.ceil(len(pcm) / (2 * sample_rate))
        return Transcript(self.text, self.confidence, billed, language.lower())


def google_error(status: int, reason: str = "", grpc: str = "") -> httpx.Response:
    details = [{"@type": "type.googleapis.com/google.rpc.ErrorInfo", "reason": reason}]
    body = {"error": {"code": status, "message": "vendor text", "status": grpc, "details": details}}
    return httpx.Response(status, json=body)


class GoogleScript:
    """An httpx transport answering like Google; `routes` maps a URL path to a handler."""

    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []
        self.routes: dict[str, Callable[[httpx.Request], httpx.Response]] = {
            "/v1/text:synthesize": lambda r: httpx.Response(
                200, json={"audioContent": base64.b64encode(b"ID3audio").decode()}
            ),
            "/v1/voices": lambda r: httpx.Response(
                200,
                json={
                    "voices": [
                        {"name": "en-GB-Chirp3-HD-Algieba", "languageCodes": ["en-GB"]},
                        {"name": "en-GB-Studio-B", "languageCodes": ["en-GB"]},
                    ]
                },
            ),
            "/v1/speech:recognize": lambda r: httpx.Response(
                200,
                json={
                    "results": [
                        {
                            "alternatives": [{"transcript": "hello jarvis", "confidence": 0.9}],
                            "languageCode": "en-in",
                        }
                    ],
                    "totalBilledTime": "2s",
                },
            ),
        }

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return self.routes[request.url.path](request)

    def client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=httpx.MockTransport(self))

    def body(self, i: int = -1) -> dict[str, Any]:
        data: dict[str, Any] = json.loads(self.requests[i].content)
        return data
