# src/jarvis/localspeech/desk.py
"""The call desk's laptop speech (R5.2 V2; I0 seams "R18 reuse"; plan 3.2, 7a): R18's
`jarvis.calldesk.speech_local.LocalSpeech` over the speech kit on the same laptop, at the kit's
gate `protocol.LOOPBACK_BASE` with the kit's key. The I1 join hands it to the desk app as `local=`.

- `status()` is synchronous (the desk's `hello` and `prepare` read it): it answers from the kit's
  last health, kept `health_s`, and starts a background check when that is older. The desk offers
  only languages the kit both hears and speaks, and nothing while the kit is slow (a long job, a
  loaded graphics card), speaks another protocol, or does not answer.
- `transcribe` hears in the first of the call's languages the kit has an engine for (R18 orders
  them, the card's first language first); too little audio is heard as nothing.
- `speak` answers PCM16 16 kHz mono; text over `TTS_MAX_CHARS` is read in parts.
- Every kit failure is R18's `LocalSpeechUnavailable` in the kit's fixed words (never audio, text
  or the key), and a kit that failed is not offered again until its next check, so the desk falls
  back to cloud speech.

Kit-safe: the standard library, Pydantic, `protocol`, `client` and R18's `speech_local` (until R18
is joined, its shapes as the seams doc names them). Nothing here logs audio or text.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable, Sequence
from typing import Final

from pydantic import SecretStr, ValidationError

from jarvis.calldesk.speech_local import LocalHeard, LocalSpeechUnavailable, LocalStatus
from jarvis.localspeech.client import HttpKit, loopback_kit
from jarvis.localspeech.protocol import (
    MIN_AUDIO_S,
    SAMPLE_BYTES,
    SAMPLE_RATE,
    STT_MAX_S,
    TTS_MAX_CHARS,
    AudioFormat,
    Kind,
    KitClient,
    KitError,
    KitHealth,
    KitUnavailable,
    SttRequest,
    TtsRequest,
    pcm_seconds,
)

log = logging.getLogger(__name__)

HEALTH_S: Final = 30.0  # as the cloud's `local_speech_health_s`
TIMEOUT_S: Final = 8.0  # as the cloud's `local_speech_timeout_s`
NOT_CHECKED: Final = "The laptop speech kit hasn't been checked yet; calls use cloud speech."
SLOW: Final = "The laptop speech kit would be slow just now; calls use cloud speech."
OLD: Final = "The laptop speech kit needs updating; calls use cloud speech."
NO_ENGINE: Final = "The laptop speech kit has no engine ready; calls use cloud speech."
NO_LANGUAGE: Final = "The laptop speech kit has no engine for that language."
REFUSED: Final = "The laptop speech kit couldn't do that."
_MAX_PCM: Final = STT_MAX_S * SAMPLE_RATE * SAMPLE_BYTES


def _parts(text: str, most: int) -> list[str]:
    """`text` in pieces of at most `most` characters, cut between words where it can."""
    out: list[str] = []
    piece = ""
    for word in text.split():
        while len(word) > most:  # a "word" longer than a piece is cut
            if piece:
                out.append(piece)
                piece = ""
            out.append(word[:most])
            word = word[most:]
        joined = f"{piece} {word}" if piece else word
        if len(joined) > most:
            out.append(piece)
            joined = word
        piece = joined
    if piece:
        out.append(piece)
    return out


class KitLocalSpeech:
    """R18's `LocalSpeech` over a `KitClient` (the desk's: `desk_speech(key)`)."""

    def __init__(
        self,
        kit: KitClient,
        *,
        health_s: float = HEALTH_S,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.kit = kit
        self._health_s = health_s
        self._clock = clock
        self._status = LocalStatus(installed=False, languages=(), reason=NOT_CHECKED)
        self._hears: frozenset[str] = frozenset()
        self._speaks: frozenset[str] = frozenset()
        self._checked_at: float | None = None
        self._check: asyncio.Task[LocalStatus] | None = None

    # ---- status -----------------------------------------------------------------------------
    def status(self) -> LocalStatus:
        stale = self._checked_at is None or self._clock() - self._checked_at >= self._health_s
        if stale:
            self._start_check()
        return self._status

    def _start_check(self) -> None:
        if self._check is not None and not self._check.done():
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return  # no event loop (a plain call): the next status() inside the loop checks
        self._check = loop.create_task(self.refresh())

    async def refresh(self) -> LocalStatus:
        """Ask the kit now; never raises (a failure is "not offered", in plain words)."""
        try:
            health = await self.kit.health()
        except KitError as exc:
            self._offer(None, str(exc))
        else:
            self._offer(health, "")
        return self._status

    def _offer(self, health: KitHealth | None, why: str) -> None:
        self._checked_at = self._clock()
        if health is not None:
            self._hears = frozenset(health.languages(Kind.STT))
            self._speaks = frozenset(health.languages(Kind.TTS))
            both = tuple(sorted(self._hears & self._speaks))
            if not health.compatible:
                why = OLD
            elif health.slow:
                why = SLOW
            elif not both:
                why = NO_ENGINE
            else:
                self._status = LocalStatus(installed=True, languages=both)
                return
        self._status = LocalStatus(installed=False, languages=(), reason=why)

    def _failed(self, exc: KitError) -> LocalSpeechUnavailable:
        if isinstance(exc, KitUnavailable):  # not offered again until the next check
            self._offer(None, str(exc))
        log.info("laptop speech: the kit failed", extra={"why": type(exc).__name__})
        return LocalSpeechUnavailable(str(exc) or REFUSED)

    # ---- LocalSpeech ------------------------------------------------------------------------
    async def transcribe(self, pcm16k: bytes, languages: Sequence[str]) -> LocalHeard:
        wanted = list(dict.fromkeys(languages))
        known = [x for x in wanted if x in self._hears] if self._hears else wanted[:1]
        if not known:
            raise LocalSpeechUnavailable(NO_LANGUAGE)
        lang = known[0]
        pcm = pcm16k[: min(len(pcm16k) // SAMPLE_BYTES * SAMPLE_BYTES, _MAX_PCM)]
        if pcm_seconds(len(pcm)) < MIN_AUDIO_S:
            return LocalHeard(lang=lang, text="", confidence=0.0)
        try:
            req = SttRequest.of_pcm(pcm, lang=lang)
        except ValidationError:
            raise LocalSpeechUnavailable(NO_LANGUAGE) from None
        try:
            out = await self.kit.stt(req)
        except KitError as exc:
            raise self._failed(exc) from None
        return LocalHeard(lang=out.lang, text=out.text, confidence=out.confidence)

    async def speak(self, text: str, lang: str) -> bytes:
        if self._speaks and lang not in self._speaks:
            raise LocalSpeechUnavailable(NO_LANGUAGE)
        audio: list[bytes] = []
        for piece in _parts(text, TTS_MAX_CHARS):
            try:
                req = TtsRequest(lang=lang, text=piece, format=AudioFormat.PCM16)
            except ValidationError:
                raise LocalSpeechUnavailable(NO_LANGUAGE) from None
            try:
                out = await self.kit.tts(req)
            except KitError as exc:
                raise self._failed(exc) from None
            if out.format is not AudioFormat.PCM16:
                raise LocalSpeechUnavailable(REFUSED)
            audio.append(out.audio_bytes())
        return b"".join(audio)

    async def aclose(self) -> None:
        if self._check is not None and not self._check.done():
            self._check.cancel()
        close = getattr(self.kit, "aclose", None)
        if close is not None:
            await close()


def desk_speech(
    key: SecretStr, *, timeout_s: float = TIMEOUT_S, health_s: float = HEALTH_S
) -> KitLocalSpeech:
    """The desk's laptop speech: the kit's gate on 127.0.0.1 with the kit's key."""
    kit: HttpKit = loopback_kit(key, timeout_s=timeout_s)
    return KitLocalSpeech(kit, health_s=health_s)


__all__ = ["HEALTH_S", "KitLocalSpeech", "desk_speech"]
