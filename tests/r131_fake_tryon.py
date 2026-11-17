# tests/r131_fake_tryon.py -- R13.1 I0's scripted try-on provider (docs/plans/r13-1-try-on.md D10,
# seam 5; imported bare: `from r131_fake_tryon import ScriptedTryOn`). It never calls anything.
#
#   JPEG, PNG          tiny made-up pictures with the right magic bytes (no person in them);
#                      PNG is a drawn picture a browser can decode (I1)
#   Step(...)          one scripted answer: a picture (the default), `blocked` (a billed 200 with no
#                      picture), or `error` (TryOnNotBilled / TryOnMaybeBilled raised)
#   Call               what one request carried: the person picture and the garments' words
#   ScriptedTryOn      a TryOnProvider. `max_garments=1` (the default) proves adapter-side chaining:
#                      n garments are n requests, each on the previous step's picture, and the
#                      caller sees ONE result; `max_garments=3` answers the whole look at once.
#                      `calls` records every request; `script` is consumed in order (an empty
#                      script answers pictures). Usage is Gemini-like (1,120 tokens an image).
from __future__ import annotations

import struct
import zlib
from collections.abc import Sequence
from dataclasses import dataclass, field

from jarvis.llm.tryon import (
    PROVIDER_WORDS,
    Garment,
    TryOnAsk,
    TryOnDescription,
    TryOnError,
    TryOnResult,
    TryOnUsage,
)

JPEG = b"\xff\xd8\xff\xe0" + b"\x00\x10JFIF\x00" + b"r131-person" + b"\xff\xd9"


def _png(w: int = 120, h: int = 160) -> bytes:
    """A small drawn picture a browser can decode (I1: I0's was a signature and text, so the
    console showed it broken): a plain figure in a navy top and charcoal trousers on light grey."""

    def px(x: int, y: int) -> bytes:
        cx = w // 2
        if (x - cx) ** 2 + (y - 24) ** 2 <= 13**2:
            return bytes((200, 190, 180))  # the head, a plain oval
        if 40 <= y < 92 and abs(x - cx) <= 26:
            return bytes((30, 40, 80))  # the new navy top
        if 92 <= y < 150 and 4 <= abs(x - cx) <= 20:
            return bytes((64, 66, 70))  # charcoal trousers
        return bytes((232, 232, 228))

    raw = b"".join(b"\x00" + b"".join(px(x, y) for x in range(w)) for y in range(h))

    def chunk(kind: bytes, body: bytes) -> bytes:
        return (
            struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body))
        )

    ihdr = struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", ihdr)
        + chunk(b"IDAT", zlib.compress(raw, 9))
        + (chunk(b"IEND", b""))
    )


PNG = _png()
TOKENS_A_IMAGE = 1120
STEP_USD = 0.0759  # one Gemini-like request (top + trousers), before the rate and GST
WORST_USD = 0.0998


@dataclass(frozen=True)
class Step:
    blocked: str | None = None
    error: TryOnError | None = None
    picture: bytes = PNG
    mime: str = "image/png"


@dataclass(frozen=True)
class Call:
    person: bytes
    garments: tuple[str, ...]
    timeout_s: float


@dataclass
class ScriptedTryOn:
    max_garments: int = 1
    script: Sequence[Step] = ()
    model: str = "fake-try-on-1"
    location: str = "us"
    calls: list[Call] = field(default_factory=list)
    _at: int = 0

    def describe(self) -> TryOnDescription:
        return TryOnDescription(
            provider=PROVIDER_WORDS, model=self.model, model_words="A made-up try-on model",
            location=self.location, location_words="processed in the United States",
            max_garments=self.max_garments, retires_on="2027-05-28",
        )  # fmt: skip

    def estimate(self, n: int) -> tuple[float, float]:
        steps = -(-max(1, n) // self.max_garments)
        return steps * STEP_USD, steps * WORST_USD

    def _next(self) -> Step:
        step = self.script[self._at] if self._at < len(self.script) else Step()
        self._at += 1
        return step

    async def _one(self, person: bytes, garments: tuple[Garment, ...], timeout_s: float) -> Step:
        self.calls.append(Call(person, tuple(g.words for g in garments), timeout_s))
        step = self._next()
        if step.error is not None:
            raise step.error
        return step

    async def make(self, ask: TryOnAsk) -> TryOnResult:
        person, last = ask.person, Step()
        chunks = [
            ask.garments[i : i + self.max_garments]
            for i in range(0, len(ask.garments), self.max_garments)
        ]
        for chunk in chunks or [()]:
            last = await self._one(person, tuple(chunk), ask.timeout_s)
            if last.blocked is not None:
                break  # a blocked step ends the chain: it is billed, no picture
            person = last.picture  # the next garment goes on this step's picture
        usage = TryOnUsage(
            input_tokens=(1 + len(ask.garments)) * TOKENS_A_IMAGE + 150,
            image_tokens=0 if last.blocked else TOKENS_A_IMAGE,
        )
        if last.blocked is not None:
            return TryOnResult(None, None, usage, last.blocked)
        return TryOnResult(last.picture, last.mime, usage, None)


__all__ = ["JPEG", "PNG", "STEP_USD", "WORST_USD", "Call", "ScriptedTryOn", "Step"]
