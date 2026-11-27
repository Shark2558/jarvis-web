# tests/calls_speech_fakes.py — R18 B helpers: an in-memory Billing at a fixed rate, PCM tones,
# a scripted vendor transport and fake Hearing / Voice options. A plain module (not conftest) so
# the tests and evals/calls_language import it.
from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any

import httpx
import numpy as np
from billing_fakes import RATE, UID, registry
from billing_fakes import billing as _billing

from jarvis.billing import Billing, BudgetPatch
from jarvis.calls.models import Heard
from jarvis.calls.speech.audio import SAMPLE_RATE, from_float
from jarvis.storage.docs import MemoryDocs

__all__ = ["RATE", "UID"]


def billing(docs: MemoryDocs | None = None) -> Billing:
    """In-memory billing at ₹95.24 a dollar, mid-November (IST), no limit."""
    return _billing(registry(), docs=docs)


async def set_limit(b: Billing, uid: str, inr: int) -> None:
    await b.budgets.update(uid, BudgetPatch(monthly_limit_inr=inr, confirm_raise=True))


def tone(seconds: float, freq: float = 440.0, amp: float = 0.3) -> bytes:
    t = np.arange(int(seconds * SAMPLE_RATE)) / SAMPLE_RATE
    return from_float(amp * np.sin(2 * np.pi * freq * t))


Answer = Callable[[httpx.Request], httpx.Response]


@dataclass
class Vendor:
    """A scripted vendor: answers in order (the last one repeats), every request kept."""

    answers: list[Answer]
    requests: list[httpx.Request] = field(default_factory=list)

    def client(self) -> httpx.AsyncClient:
        def handler(req: httpx.Request) -> httpx.Response:
            self.requests.append(req)
            return self.answers[min(len(self.requests), len(self.answers)) - 1](req)

        return httpx.AsyncClient(transport=httpx.MockTransport(handler))

    def body(self, i: int = -1) -> Any:
        return json.loads(self.requests[i].content)


def respond(status: int = 200, **kw: Any) -> Answer:
    return lambda _req: httpx.Response(status, **kw)


async def no_sleep(_s: float) -> None:
    return None


@dataclass
class FakeHearing:
    """A Hearing that answers from a script keyed by the language asked first."""

    name: str
    texts: dict[str, str] = field(default_factory=dict)
    confidence: float = 0.9
    detected: str | None = None
    calls: list[tuple[int, tuple[str, ...]]] = field(default_factory=list)

    async def transcribe(self, pcm16k: bytes, languages: Sequence[str]) -> Heard:
        self.calls.append((len(pcm16k), tuple(languages)))
        lang = self.detected if self.detected in languages else languages[0]
        return Heard(
            lang=lang,
            text=self.texts.get(lang, ""),
            confidence=self.confidence,
            seconds=len(pcm16k) / 32_000,
        )


@dataclass
class FakeVoice:
    name: str
    seconds_per_char: float = 0.06
    spoken: list[tuple[str, str]] = field(default_factory=list)

    async def speak(self, text: str, lang: str) -> bytes:
        self.spoken.append((text, lang))
        return tone(max(0.2, len(text) * self.seconds_per_char))
