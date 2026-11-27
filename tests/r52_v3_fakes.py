# tests/r52_v3_fakes.py -- R5.2 V3: shared fakes for the voice session's tests. Imported as a
# sibling module (CI runs plain pytest; tests/ is not a package). Synthetic audio only: tones
# made here, never a recording; no personal data.
from __future__ import annotations

import hashlib
import struct
import unicodedata
from dataclasses import dataclass, field

from jarvis.billing.service import BudgetReached, FreeAllowanceUsed
from jarvis.voice.ports import VoiceUnavailable
from jarvis.voice.session import GoogleHeard

UID = "owner-1"
RATE = 16_000


def normalise(text: str) -> str:
    """A stand-in with R18's contract (NFKC, case folded, punctuation and symbols as spaces)."""
    folded = unicodedata.normalize("NFKC", text).casefold()
    kept = "".join(" " if unicodedata.category(c)[0] in "PSZC" else c for c in folded)
    return " ".join(kept.split())


def pcm(seed: int, seconds: float = 0.5) -> bytes:
    """A distinct synthetic square wave per seed (so the fakes can tell clips apart)."""
    level = 1000 + 37 * seed
    period = struct.pack("<h", level) * 20 + struct.pack("<h", -level) * 20
    return (period * int(RATE * seconds / 40 + 1))[: int(RATE * seconds) * 2]


def wav(data: bytes, rate: int = RATE) -> bytes:
    head = struct.pack(
        "<4sI4s4sIHHIIHH4sI",
        b"RIFF",
        36 + len(data),
        b"WAVE",
        b"fmt ",
        16,
        1,
        1,
        rate,
        rate * 2,
        2,
        16,
        b"data",
        len(data),
    )
    return head + data


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@dataclass
class FakeGoogle:
    """Google with his words: what it hears is scripted per clip (by the WAV's PCM hash)."""

    heard: dict[str, str] = field(default_factory=dict)
    free_left: float = 3_240.0
    per_minute: float = 2.2858
    is_ready: bool = True
    fail: Exception | None = None
    free_used_after: int | None = None  # FreeAllowanceUsed once this many free calls were made
    calls: list[bool] = field(default_factory=list)  # free_only of each call

    def ready(self) -> bool:
        return self.is_ready

    async def free_seconds_left(self) -> float:
        return self.free_left

    async def inr_per_minute(self) -> float:
        return self.per_minute

    async def hear(self, uid: str, wav_bytes: bytes, *, free_only: bool) -> GoogleHeard:
        self.calls.append(free_only)
        if self.fail is not None:
            raise self.fail
        if free_only and self.free_used_after is not None:
            if sum(self.calls) > self.free_used_after:
                raise FreeAllowanceUsed()
        text = self.heard.get(sha(wav_bytes[44:]), "")
        return GoogleHeard(text=text, ms=420)


@dataclass
class FakeWords:
    """His "words to recognise" (R5's VoiceSettings.phrases)."""

    words: list[str] = field(default_factory=list)
    broken: bool = False

    async def read(self, uid: str) -> tuple[str, ...]:
        if self.broken:
            raise RuntimeError("store down")
        return tuple(self.words)

    async def add(self, uid: str, new: tuple[str, ...]) -> tuple[str, ...]:
        room = 50 - len(self.words)
        added = list(new)[: max(0, room)]
        self.words += added
        return tuple(added)


def budget_reached() -> BudgetReached:
    return BudgetReached(limit_inr=500, used_inr=500.0, free_brain=False)


def google_down() -> VoiceUnavailable:
    return VoiceUnavailable("upstream_error")
