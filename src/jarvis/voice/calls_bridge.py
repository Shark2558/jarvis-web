# src/jarvis/voice/calls_bridge.py
"""R18's call speech on the laptop speech kit (R5.2 V2; plan 3.2, 7a, D7; I0 seams "R18 reuse").

`LaptopHearing` and `LaptopCallVoice` satisfy `jarvis.calls.ports.Hearing` and `Voice` with the
name "laptop" (`SpeechOption.LAPTOP`), over the same health-cached kit as the console's voice
(`jarvis.voice.laptop.LaptopVoice`). The I1 join passes `laptop_speech(laptop)` to R18's
`jarvis.calls.speech.build.build_speech(..., laptop=...)`; R18's selection and its language check
decide when "laptop" is used (first when it passed the check). Nothing of R18's is copied here.

- hearing: the first of the call's languages the kit has a ready engine for; too little audio is
  heard as nothing; more than `STT_MAX_S` is left to another option.
- voice: PCM16 16 kHz mono, at most `TTS_MAX_CHARS` a request (R18's adapters cap theirs too).
- every failure (the kit off, slow, refusing the key, refusing the request, a language it lacks)
  is R18's `SpeechUnavailable` in fixed words, so the caller tries the next option. A kit that
  failed is marked down for the rest of its health period. The laptop costs ₹0 (R18's
  `speech_prices` for `SpeechOption.LAPTOP`), so nothing is metered.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Final

from pydantic import ValidationError

from jarvis.calls.models import Heard, SpeechOption
from jarvis.calls.ports import Hearing, SpeechUnavailable, Voice
from jarvis.localspeech.protocol import (
    MIN_AUDIO_S,
    SAMPLE_BYTES,
    STT_MAX_S,
    TTS_MAX_CHARS,
    AudioFormat,
    Kind,
    KitError,
    KitHealth,
    KitUnavailable,
    SttRequest,
    TtsRequest,
    pcm_seconds,
)
from jarvis.voice.laptop import LaptopVoice, kit_words

LAPTOP: Final = SpeechOption.LAPTOP.value
AWAY: Final = "The laptop's speech is not available just now."
NO_LANGUAGE: Final = "The laptop's speech has no engine for that language."
TOO_MUCH: Final = "That is too long for the laptop's speech."


async def _usable(laptop: LaptopVoice) -> KitHealth:
    h = await laptop.health()
    if h is None or not h.compatible or h.slow:
        raise SpeechUnavailable(AWAY)
    return h


def _failed(laptop: LaptopVoice, exc: KitError) -> SpeechUnavailable:
    if isinstance(exc, KitUnavailable):
        laptop.mark_down(exc.reason)
        return SpeechUnavailable(kit_words(exc.reason))
    return SpeechUnavailable(kit_words("refused"))


class LaptopHearing:
    """`Hearing` on the kit."""

    name: str = LAPTOP

    def __init__(self, laptop: LaptopVoice) -> None:
        self._laptop = laptop

    async def transcribe(self, pcm16k: bytes, languages: Sequence[str]) -> Heard:
        kit = self._laptop.kit
        if kit is None:
            raise SpeechUnavailable(AWAY)
        hears = set((await _usable(self._laptop)).languages(Kind.STT))
        lang = next((x for x in dict.fromkeys(languages) if x in hears), None)
        if lang is None:
            raise SpeechUnavailable(NO_LANGUAGE)
        pcm = pcm16k[: len(pcm16k) // SAMPLE_BYTES * SAMPLE_BYTES]
        seconds = pcm_seconds(len(pcm))
        if seconds < MIN_AUDIO_S:
            return Heard(lang=lang, text="", confidence=0.0, seconds=seconds)
        if seconds > STT_MAX_S:
            raise SpeechUnavailable(TOO_MUCH)
        try:
            out = await kit.stt(SttRequest.of_pcm(pcm, lang=lang))
        except KitError as exc:
            raise _failed(self._laptop, exc) from None
        return Heard(lang=out.lang, text=out.text, confidence=out.confidence, seconds=seconds)


class LaptopCallVoice:
    """`Voice` on the kit: PCM16 16 kHz mono."""

    name: str = LAPTOP

    def __init__(self, laptop: LaptopVoice) -> None:
        self._laptop = laptop

    async def speak(self, text: str, lang: str) -> bytes:
        kit = self._laptop.kit
        if kit is None:
            raise SpeechUnavailable(AWAY)
        if lang not in (await _usable(self._laptop)).languages(Kind.TTS):
            raise SpeechUnavailable(NO_LANGUAGE)
        say = " ".join(text.split())
        if not say:
            return b""
        if len(say) > TTS_MAX_CHARS:
            raise SpeechUnavailable(TOO_MUCH)
        try:
            req = TtsRequest(lang=lang, text=say, format=AudioFormat.PCM16)
        except ValidationError:
            raise SpeechUnavailable(NO_LANGUAGE) from None
        try:
            out = await kit.tts(req)
        except KitError as exc:
            raise _failed(self._laptop, exc) from None
        if out.format is not AudioFormat.PCM16:
            raise SpeechUnavailable(AWAY)
        return out.audio_bytes()


def laptop_speech(laptop: LaptopVoice) -> tuple[Hearing | None, Voice | None]:
    """R18's `laptop=` pair; (None, None) when the kit is not set up, so R18 lists it missing."""
    if laptop.kit is None:
        return None, None
    return LaptopHearing(laptop), LaptopCallVoice(laptop)


__all__ = ["LAPTOP", "LaptopCallVoice", "LaptopHearing", "laptop_speech"]
