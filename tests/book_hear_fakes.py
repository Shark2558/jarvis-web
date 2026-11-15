# tests/book_hear_fakes.py -- R6.2 Part 1: app.state.voice for POST /v1/book/show/hear. Records how
# it was asked to transcribe (the owner's words or not, the book's own words) and whether the
# owner's "Words to recognise" were read; answers with `heard` or raises `error`. No network.
from __future__ import annotations

import io
import wave
from dataclasses import dataclass, field
from typing import Any


def wav(seconds: float = 1.0) -> bytes:
    """A valid, silent 16 kHz mono PCM16 WAV."""
    out = io.BytesIO()
    with wave.open(out, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16_000)
        w.writeframes(b"\x00\x00" * int(16_000 * seconds))
    return out.getvalue()


@dataclass(frozen=True)
class Heard:
    """The fields of voice.service.TranscriptView the hear route reads."""

    text: str
    cost_inr: float = 0.0

    @property
    def no_speech(self) -> bool:
        return not self.text


@dataclass(frozen=True)
class OwnerWords:
    phrases: tuple[str, ...] = ()


@dataclass
class Ears:
    """`heard`: what the recogniser says; `error`: raised instead; `phrases`: the owner's words."""

    heard: str = "how does voice work"
    cost_inr: float = 0.0
    error: Exception | None = None
    phrases: tuple[str, ...] = ()
    asked: list[dict[str, Any]] = field(default_factory=list)
    settings_reads: list[str] = field(default_factory=list)

    async def aclose(self) -> None:
        return None

    async def settings_of(self, uid: str) -> OwnerWords:
        self.settings_reads.append(uid)
        return OwnerWords(self.phrases)

    async def transcribe(
        self,
        uid: str,
        blob: bytes,
        *,
        owner_phrases: bool = True,
        turn_hints: tuple[str, ...] = (),
        public_hints: tuple[str, ...] = (),
    ) -> Heard:
        self.asked.append(
            {"owner_phrases": owner_phrases, "turn_hints": turn_hints, "public_hints": public_hints}
        )
        if self.error is not None:
            raise self.error
        return Heard(self.heard, self.cost_inr)


__all__ = ["Ears", "Heard", "OwnerWords", "wav"]
