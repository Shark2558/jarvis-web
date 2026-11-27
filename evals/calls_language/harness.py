# evals/calls_language/harness.py
"""R18 B mock harness: a scripted "world" where audio stands for its text by its length (the
phone line keeps lengths), fake hearing and voice options with a latency on a fake clock, a fake
clip source and an in-memory billing. No network, no vendor, no model."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import numpy as np

from jarvis.billing import Billing, BudgetStore, FxRates, UsageMeter
from jarvis.calls.langcheck.fleurs import Clip, FleursUnavailable
from jarvis.calls.langcheck.runner import LanguageCheck
from jarvis.calls.langcheck.sentences import Sentence, english
from jarvis.calls.models import Heard
from jarvis.calls.prices import speech_prices
from jarvis.calls.speech.audio import SAMPLE_RATE, from_float
from jarvis.calls.speech.build import SpeechOptions
from jarvis.calls.speech.meter import SpeechMeter
from jarvis.calls.store import MemoryCallStore
from jarvis.config import Settings
from jarvis.llm.brains import BrainRegistry, BrainSpec
from jarvis.llm.mock_provider import MockProvider
from jarvis.llm.router import ModelTier
from jarvis.storage.docs import MemoryDocs

UID = "u_eval"
RATE = 95.24
NOW = datetime(2026, 11, 27, 9, 0, tzinfo=UTC)
TEXTS = [f"दुकान {i + 1}:30 बजे खुलती है और {i + 3} लोग आते हैं।" for i in range(12)] + [
    f"यह एक सादा वाक्य है {chr(0x915 + i)}" for i in range(8)
]


class Clock:
    def __init__(self) -> None:
        self.t = 0.0

    def __call__(self) -> float:
        return self.t


@dataclass
class World:
    clock: Clock = field(default_factory=Clock)
    by_len: dict[int, str] = field(default_factory=dict)
    next_samples: int = 16_000

    def audio(self, text: str) -> bytes:
        n = self.next_samples
        self.next_samples += 160
        t = np.arange(n) / SAMPLE_RATE
        pcm = from_float(0.3 * np.sin(2 * np.pi * 440 * t))
        self.by_len[len(pcm)] = text
        return pcm

    def text(self, pcm: bytes) -> str:
        return self.by_len.get(len(pcm), "")


@dataclass
class Hearing:
    name: str
    world: World
    transform: Callable[[str], str] = lambda t: t
    latency_s: float = 0.2

    async def transcribe(self, pcm16k: bytes, languages: Sequence[str]) -> Heard:
        self.world.clock.t += self.latency_s
        text = self.transform(self.world.text(pcm16k))
        return Heard(lang=languages[0], text=text, confidence=0.9, seconds=len(pcm16k) / 32_000)


@dataclass
class Voice:
    name: str
    world: World
    latency_s: float = 0.3

    async def speak(self, text: str, lang: str) -> bytes:
        self.world.clock.t += self.latency_s
        return self.world.audio(text)


class Clips:
    def __init__(self, world: World, *, down: bool = False) -> None:
        self.world, self.down = world, down

    async def clips(self, lang: str, n: int = 20) -> list[Clip]:
        if self.down:
            raise FleursUnavailable("The test clips could not be fetched from Hugging Face.")
        return [Clip(lang, t, self.world.audio(t)) for t in TEXTS[:n]]


class Sentences:
    async def sentences(self, lang: str) -> list[Sentence]:
        return english()


def plain_settings(**values: Any) -> Settings:
    """Settings from the defaults and `values` only (no .env file), as the voice eval builds it."""
    return Settings(_env_file=None, **values)  # type: ignore[call-arg]  # pydantic-settings


def billing() -> Billing:
    docs = MemoryDocs()
    brains = BrainRegistry(
        [
            BrainSpec(
                id="mock",
                label="Mock",
                provider=MockProvider(),
                tiers=dict.fromkeys(ModelTier, "mock"),
            )
        ],
        default_id="mock",
    )
    return Billing(
        fx=FxRates(docs=None, http=None, default_rate=RATE),
        meter=UsageMeter(docs, tz="Asia/Kolkata"),
        budgets=BudgetStore(docs),
        brains=brains,
        clock=lambda: NOW,
    )


def check(
    world: World,
    hearing: dict[str, Hearing],
    voices: dict[str, Voice],
    *,
    settings: Settings | None = None,
    sarvam_on: bool = False,
    clips: Clips | None = None,
) -> tuple[LanguageCheck, MemoryCallStore, Billing]:
    s = settings or plain_settings()
    store, bill = MemoryCallStore(), billing()
    lc = LanguageCheck(
        speech=SpeechOptions(hearing=dict(hearing), voices=dict(voices)),
        store=store,
        clips=clips or Clips(world),
        sentences=Sentences(),
        meter=SpeechMeter(bill, UID),
        prices=speech_prices(s, RATE),
        sarvam_on=sarvam_on,
        clock=world.clock,
        now=lambda: NOW,
    )
    return lc, store, bill
