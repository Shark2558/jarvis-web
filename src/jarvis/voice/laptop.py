# src/jarvis/voice/laptop.py
"""The laptop speech kit for the console's voice (R5.2 row 383, V2; plan 3.2, D7; I0 seams).

`LaptopVoice` is the cloud's view of the kit (`app.state.voice_laptop`, `profile_ports.LaptopApi`):

- the kit's health, kept `local_speech_health_s`. A kit found down is not asked again in that
  time; once it is older, a "down" is answered at once and checked again in the background (no
  turn waits for an absent laptop), an "up" is checked before use within `HEALTH_WAIT_S`.
- `stt` / `tts`: adapters on `jarvis.voice.ports` (`STTProvider`, `TTSProvider`). English of any
  region is the kit's English (`protocol`'s languages are R18's); the console's voice is MP3.
- failures: a kit that is off, slow, refusing the key, answering oddly or refusing a request is
  `LaptopUnavailable` (the voice service falls back silently to Google, then the browser, with the
  existing messages: a kit failure is never shown as a Google error); a recording the kit can't
  use is `BadAudio`. A kit failure marks the kit down for the rest of the period.
- `note_served` / `last_served`: which engine served the last listen and the last voice (the
  laptop's own or Google), for `status` and the Vitals line (`vitals_line`), at ₹0 for the laptop
  (`jarvis.calls.prices.speech_prices(...)[SpeechOption.LAPTOP]`).

Nothing here logs audio, text, the kit's key or the laptop's name.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final, Literal

from pydantic import BaseModel, Field, ValidationError

from jarvis.calls.models import ENGLISH, SpeechOption, is_language
from jarvis.calls.prices import speech_prices
from jarvis.localspeech.client import cloud_kit
from jarvis.localspeech.protocol import (
    PHRASES_MAX,
    SAMPLE_RATE,
    SLOT_KIND,
    UNAVAILABLE_REASONS,
    AudioFormat,
    EngineSlot,
    Kind,
    KitClient,
    KitError,
    KitHealth,
    KitRefused,
    KitUnavailable,
    SttRequest,
    TtsRequest,
)
from jarvis.logging import get_logger
from jarvis.voice.ports import BadAudio, Transcript, VoiceError
from jarvis.voice.wav import MSG_FORMAT

if TYPE_CHECKING:
    from jarvis.config import Settings

log = get_logger(__name__)

HEALTH_WAIT_S: Final = 2.0  # the longest a turn waits for the kit's health
PHRASE_CHARS: Final = 40  # protocol.PHRASE_CHARS, = voice.settings.PHRASE_CHARS
RATE_MIN, RATE_MAX = 0.5, 2.0  # what the kit's TtsRequest takes
GOOGLE: Final = "google"
KitState = Literal["off", "unknown", "ready", "slow", "old", "down"]
REFUSED: Final = "The laptop speech kit couldn't do that."
STATE_WORDS: Final[dict[str, str]] = {
    "off": "The laptop speech kit is not set up; JARVIS uses Google's speech, then the browser's.",
    "unknown": "The laptop speech kit hasn't been checked yet.",
    "ready": "The laptop speech kit is ready.",
    "slow": "The laptop speech kit would be slow just now; Google's speech is used meanwhile.",
    "old": "The laptop speech kit needs updating; Google's speech is used meanwhile.",
}


def laptop_engine(slot: EngineSlot) -> str:
    """The engine's name where it is shown: `laptop-whisper-small`, `laptop-kokoro`, ..."""
    return f"laptop-{slot.value}"


def kit_language(language: str) -> str | None:
    """The kit's language for the console's: any English is the kit's English (R18's en-IN)."""
    if language.lower() == "en" or language.lower().startswith("en-"):
        return ENGLISH
    return language if is_language(language) else None


def kit_phrases(words: tuple[str, ...]) -> tuple[str, ...]:
    """The words to recognise as the kit takes them: 1 to 40 characters each, one spelling per
    word (the first wins), at most `PHRASES_MAX` (the base list and the honorific come first)."""
    out: dict[str, str] = {}
    for w in words:
        text = " ".join(w.split())
        if 1 <= len(text) <= PHRASE_CHARS:
            out.setdefault(text.casefold(), text)
    return tuple(out.values())[:PHRASES_MAX]


def kit_words(reason: str) -> str:
    """The kit's fixed words for a reason (`protocol.KitUnavailable`'s), else `REFUSED`."""
    for known in UNAVAILABLE_REASONS:
        if known == reason:
            return str(KitUnavailable(known))
    return REFUSED


class LaptopUnavailable(VoiceError):
    """The kit can't serve this now: the voice service falls back silently (Google, then the
    browser). `reason`: a `protocol.UnavailableReason`, or the kit's refusal code."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(kit_words(reason))


# ---- what the console and Vitals are shown -------------------------------------------------------
class EngineView(BaseModel):
    slot: EngineSlot
    kind: Kind
    ready: bool
    loaded: bool
    device: str
    model: str
    licence: str
    languages: list[str]


class Languages(BaseModel):
    hear: list[str] = Field(default_factory=list)
    speak: list[str] = Field(default_factory=list)


class LaptopStatus(BaseModel):
    """GET /v1/voice/profile/laptop (`LaptopApi.status`): never the laptop's name or the key."""

    configured: bool
    state: KitState
    words: str
    kit_version: str | None = None
    device: str | None = None
    engines: list[EngineView] = Field(default_factory=list)
    languages: Languages = Field(default_factory=Languages)
    last_heard_by: str | None = None  # `laptop-whisper-small`, `google`, ...
    last_spoken_by: str | None = None
    inr_per_minute: float = 0.0


@dataclass(frozen=True)
class VoiceLine:
    """What Vitals' engine line shows (`jarvis.vitals.own`): the kit's state, which engine served
    the last listen and the last voice, and what the laptop costs."""

    state: KitState
    heard_by: str | None
    spoken_by: str | None
    inr_per_minute: float


# ---- the kit, health-cached ----------------------------------------------------------------------
class LaptopVoice:
    def __init__(
        self,
        kit: KitClient | None,
        *,
        health_s: float,
        wait_s: float = HEALTH_WAIT_S,
        clock: Callable[[], float] = time.monotonic,
        inr_per_minute: float = 0.0,
    ) -> None:
        self.kit = kit
        self.inr_per_minute = inr_per_minute
        self._health_s = health_s
        self._wait_s = wait_s
        self._clock = clock
        self._health: KitHealth | None = None
        self._down: str | None = None
        self._checked_at: float | None = None
        self._check: asyncio.Task[None] | None = None
        self._served: dict[Kind, str] = {}
        self.stt = LaptopSTT(self)
        self.tts = LaptopTTS(self)

    def __repr__(self) -> str:
        return f"LaptopVoice(state={self.state()})"

    # ---- health ------------------------------------------------------------------------------
    def _fresh(self) -> bool:
        at = self._checked_at
        return at is not None and self._clock() - at < self._health_s

    def _set(self, health: KitHealth | None, down: str | None) -> None:
        self._health, self._down, self._checked_at = health, down, self._clock()

    async def _run_check(self) -> None:
        assert self.kit is not None
        try:
            health = await self.kit.health()
        except KitUnavailable as exc:
            self._set(None, exc.reason)
        except KitError:
            self._set(None, "error")
        else:
            self._set(health, None)
        log.info("local speech: health", extra={"state": self.state()})

    def _start_check(self) -> asyncio.Task[None]:
        if self._check is None or self._check.done():
            self._check = asyncio.ensure_future(self._run_check())
        return self._check

    async def health(self) -> KitHealth | None:
        """The kit's health, or None (not set up, down, or not answering in time). Never raises."""
        if self.kit is None:
            return None
        if self._fresh():
            return self._health
        stale_down = self._checked_at is not None and self._health is None
        task = self._start_check()
        if stale_down:
            return None  # probably still away: Google answers now, the check runs behind
        try:
            await asyncio.wait_for(asyncio.shield(task), self._wait_s)
        except TimeoutError:
            return None
        return self._health

    def mark_down(self, reason: str) -> None:
        """A call to the kit failed: not asked again until the period ends."""
        self._set(None, reason)

    async def ready(self, kind: Kind, slot: EngineSlot | None = None) -> bool:
        """Whether the kit can serve `kind` in English now (with `slot`, that engine)."""
        h = await self.health()
        if h is None or not h.compatible or h.slow:
            return False
        if slot is None:
            return h.engine_for(kind, ENGLISH) is not None
        if SLOT_KIND[slot] is not kind:
            return False
        return any(e.slot is slot and e.ready and ENGLISH in e.languages for e in h.engines)

    def state(self) -> KitState:
        if self.kit is None:
            return "off"
        if self._checked_at is None:
            return "unknown"
        h = self._health
        if h is None:
            return "down"
        if not h.compatible:
            return "old"
        return "slow" if h.slow else "ready"

    # ---- what served -------------------------------------------------------------------------
    def note_served(self, kind: Kind, engine: str) -> None:
        self._served[kind] = engine

    def last_served(self, kind: Kind) -> str | None:
        return self._served.get(kind)

    # ---- LaptopApi and Vitals ----------------------------------------------------------------
    def _words(self, state: KitState) -> str:
        if state != "down":
            return STATE_WORDS[state]
        return f"{kit_words(self._down or 'error')} Google's speech is used meanwhile."

    async def status(self, uid: str) -> LaptopStatus:
        h = await self.health()
        state = self.state()
        base = LaptopStatus(
            configured=self.kit is not None,
            state=state,
            words=self._words(state),
            last_heard_by=self.last_served(Kind.STT),
            last_spoken_by=self.last_served(Kind.TTS),
            inr_per_minute=self.inr_per_minute,
        )
        if h is None:
            return base
        engines = [
            EngineView(
                slot=e.slot,
                kind=e.kind,
                ready=e.ready,
                loaded=e.loaded,
                device=e.device.value,
                model=e.model,
                licence=e.licence,
                languages=list(e.languages),
            )
            for e in h.engines
        ]
        langs = Languages(hear=list(h.languages(Kind.STT)), speak=list(h.languages(Kind.TTS)))
        return base.model_copy(
            update={
                "kit_version": h.kit_version,
                "device": h.device.value,
                "engines": engines,
                "languages": langs,
            }
        )

    async def vitals_line(self, uid: str) -> VoiceLine | None:
        """Vitals' engine line; None when the kit is not set up (the item is left out)."""
        if self.kit is None:
            return None
        await self.health()
        return VoiceLine(
            state=self.state(),
            heard_by=self.last_served(Kind.STT),
            spoken_by=self.last_served(Kind.TTS),
            inr_per_minute=self.inr_per_minute,
        )

    async def aclose(self) -> None:
        task = self._check
        if task is not None and not task.done():
            task.cancel()
        close = getattr(self.kit, "aclose", None)
        if close is not None:
            await close()


def _kit_of(laptop: LaptopVoice) -> KitClient:
    if laptop.kit is None:
        raise LaptopUnavailable("not_configured")
    return laptop.kit


def _failed(laptop: LaptopVoice, exc: KitError) -> VoiceError:
    if isinstance(exc, KitUnavailable):
        laptop.mark_down(exc.reason)
        return LaptopUnavailable(exc.reason)
    code = exc.code if isinstance(exc, KitRefused) else "error"
    if code == "bad_audio":
        return BadAudio(MSG_FORMAT)
    return LaptopUnavailable(code)


class LaptopSTT:
    """`STTProvider` on the kit (`slot`: the owner's chosen laptop engine, else the kit's)."""

    def __init__(self, laptop: LaptopVoice) -> None:
        self._laptop = laptop

    async def recognize(
        self,
        pcm: bytes,
        *,
        sample_rate: int,
        language: str,
        phrases: tuple[str, ...],
        slot: EngineSlot | None = None,
    ) -> Transcript:
        kit = _kit_of(self._laptop)
        lang = kit_language(language)
        if lang is None or sample_rate != SAMPLE_RATE:
            raise LaptopUnavailable("bad_request")
        try:
            req = SttRequest.of_pcm(pcm, lang=lang, slot=slot, phrases=kit_phrases(phrases))
        except ValidationError:
            raise LaptopUnavailable("bad_request") from None
        try:
            out = await kit.stt(req)
        except KitError as exc:
            raise _failed(self._laptop, exc) from None
        self._laptop.note_served(Kind.STT, laptop_engine(out.slot))
        return Transcript(
            text=out.text,
            confidence=out.confidence,
            billed_seconds=0.0,  # the laptop bills nothing
            language=out.lang,
            alternatives=out.alternatives,
        )


class LaptopTTS:
    """`TTSProvider` on the kit: MP3 in the kit's British voice (the owner's Google voice id is
    Google's; the kit speaks with its own default, `protocol.DEFAULT_ENGLISH_VOICE`)."""

    def __init__(self, laptop: LaptopVoice) -> None:
        self._laptop = laptop

    async def synthesize(self, text: str, *, voice: str, language: str, rate: float) -> bytes:
        kit = _kit_of(self._laptop)
        lang = kit_language(language)
        if lang is None:
            raise LaptopUnavailable("bad_request")
        try:
            req = TtsRequest(
                lang=lang,
                text=text,
                rate=min(RATE_MAX, max(RATE_MIN, rate)),
                format=AudioFormat.MP3,
            )
        except ValidationError:
            raise LaptopUnavailable("bad_request") from None
        try:
            out = await kit.tts(req)
        except KitError as exc:
            raise _failed(self._laptop, exc) from None
        if out.format is not AudioFormat.MP3:
            self._laptop.mark_down("protocol")
            raise LaptopUnavailable("protocol")
        self._laptop.note_served(Kind.TTS, laptop_engine(out.slot))
        return out.audio_bytes()

    async def voices(self, language: str) -> frozenset[str]:
        h = await self._laptop.health()
        lang = kit_language(language)
        if h is None or lang is None:
            return frozenset()
        return frozenset(
            e.model for e in h.engines if e.kind is Kind.TTS and e.ready and lang in e.languages
        )


def laptop_voice(s: Settings) -> LaptopVoice:
    """The kit for console voice from the settings: no kit (state "off") unless both its https
    address and its key are set and it is enabled. Nothing here makes a network call."""
    price = speech_prices(s, 1.0)[SpeechOption.LAPTOP].inr_per_minute()  # ₹0: rupees, no dollar
    kit: KitClient | None = None
    if s.local_speech_configured and s.local_speech_url and s.local_speech_key:
        kit = cloud_kit(s.local_speech_url, s.local_speech_key, timeout_s=s.local_speech_timeout_s)
    return LaptopVoice(kit, health_s=s.local_speech_health_s, inr_per_minute=price)


__all__ = [
    "GOOGLE",
    "HEALTH_WAIT_S",
    "EngineView",
    "KitState",
    "LaptopSTT",
    "LaptopStatus",
    "LaptopTTS",
    "LaptopUnavailable",
    "LaptopVoice",
    "VoiceLine",
    "kit_language",
    "kit_phrases",
    "kit_words",
    "laptop_engine",
    "laptop_voice",
]
