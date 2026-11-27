# src/jarvis/calls/speech/sarvam.py
"""Sarvam over REST (R18 B; Layer 6): PAID, off unless the owner turned it on (D3). httpx only.

    hearing  POST https://api.sarvam.ai/speech-to-text, multipart: `file` (a 16 kHz PCM16 WAV),
             `model` saaras:v4, `mode` transcribe, `language_code` (the language, or `unknown` to
             let Sarvam detect among several: `language_code` + `language_probability` come back)
    voice    POST https://api.sarvam.ai/text-to-speech, JSON: `text`, `language_code`, `speaker`
             (Bulbul v3's stock voice "shubh"), `model` bulbul:v3, `speech_sample_rate` 16000;
             `audios[0]` is a base64 WAV, read into PCM16 16 kHz mono

Before anything else, every request asks `enabled()` (the owner's YES, `CallSettings.sarvam_on`,
and the deployment's `sarvam_enabled` with its key): no → `PaidOptionOff`, nothing sent, nothing
spent. Then the owner's monthly limit is checked (`SpeechMeter.gate_inr`) and every rupee metered
exactly: ₹30 an hour of hearing (whole seconds) and ₹30 per 10,000 characters of voice by default
(`jarvis.calls.prices`). A failure Sarvam may have billed (a timeout after sending) is metered
too. The key travels only in `api-subscription-key`; audio and text are never logged.
"""

from __future__ import annotations

import asyncio
import base64
import binascii
import math
from collections.abc import Awaitable, Callable, Sequence
from typing import Any

import httpx
from pydantic import SecretStr

from jarvis.calls.models import Heard
from jarvis.calls.speech.audio import AudioFormatError, pcm_from_wav, pcm_seconds, wav_from_pcm
from jarvis.calls.speech.catalogue import LANGUAGES, SARVAM, SARVAM_SPEAKER, hears, speaks
from jarvis.calls.speech.errors import NotOffered, OptionUnavailable, PaidOptionOff, SpeechRejected
from jarvis.calls.speech.meter import SpeechMeter
from jarvis.calls.speech.rest import IN_CALL, RetryPolicy, Sleep, json_body, send

STT_URL = "https://api.sarvam.ai/speech-to-text"
TTS_URL = "https://api.sarvam.ai/text-to-speech"
STT_MODEL = "saaras:v4"
TTS_MODEL = "bulbul:v3"
STT_KEY, TTS_KEY = "sarvam_stt_seconds", "sarvam_tts_chars"
MAX_AUDIO_S = 30.0  # the synchronous REST endpoint takes short clips; a call's turn is one
MAX_SAY_CHARS = 1_000  # Sarvam allows 2,500; a spoken reply is short
MAX_TEXT = 4_000
NO_CONFIDENCE = 0.5  # Sarvam gives no confidence for one named language: "unknown"
Enabled = Callable[[], Awaitable[bool]]


class _Sarvam:
    def __init__(
        self,
        http: httpx.AsyncClient,
        key: SecretStr,
        meter: SpeechMeter,
        *,
        enabled: Enabled,
        policy: RetryPolicy = IN_CALL,
        sleep: Sleep = asyncio.sleep,
    ) -> None:
        self._http = http
        self._key = key
        self.meter = meter
        self._enabled = enabled
        self.policy = policy
        self._sleep = sleep

    async def _require_on(self) -> None:
        if not await self._enabled():
            raise PaidOptionOff(SARVAM)

    async def _paid(
        self, part: str, key: str, units: float, inr_per_unit: float, **kw: Any
    ) -> httpx.Response:
        """Gate on the limit, send, and meter the units (also when Sarvam may have billed)."""
        await self.meter.gate_inr(SARVAM, key, units)
        try:
            r = await send(
                self._http, "POST", policy=self.policy, sleep=self._sleep, option=SARVAM,
                headers={"api-subscription-key": self._key.get_secret_value()}, **kw,
            )  # fmt: skip
        except OptionUnavailable as exc:
            if exc.maybe_billed:
                self.meter.report(part, await self.meter.charge_inr(key, units, inr_per_unit))
            raise
        self.meter.report(part, await self.meter.charge_inr(key, units, inr_per_unit))
        return r


class SarvamHearing(_Sarvam):
    name = SARVAM

    def __init__(
        self,
        http: httpx.AsyncClient,
        key: SecretStr,
        meter: SpeechMeter,
        *,
        enabled: Enabled,
        inr_per_hour: float,
        policy: RetryPolicy = IN_CALL,
        sleep: Sleep = asyncio.sleep,
    ) -> None:
        super().__init__(http, key, meter, enabled=enabled, policy=policy, sleep=sleep)
        self.inr_per_second = inr_per_hour / 3600

    async def transcribe(self, pcm16k: bytes, languages: Sequence[str]) -> Heard:
        langs = [x for x in dict.fromkeys(languages) if hears(SARVAM, x)]
        if not langs:
            raise NotOffered(SARVAM, ", ".join(languages) or "no language")
        await self._require_on()
        seconds = pcm_seconds(pcm16k)
        if seconds > MAX_AUDIO_S:
            raise SpeechRejected(SARVAM)
        asked = langs[0] if len(langs) == 1 else "unknown"
        r = await self._paid(
            "hearing",
            STT_KEY,
            float(max(1, math.ceil(seconds))),
            self.inr_per_second,
            url=STT_URL,
            api="stt",
            data={"model": STT_MODEL, "mode": "transcribe", "language_code": asked},
            files={"file": ("turn.wav", wav_from_pcm(pcm16k), "audio/wav")},
        )
        body = json_body(r, SARVAM)
        text = body.get("transcript")
        if not isinstance(text, str):
            raise OptionUnavailable(SARVAM, "bad_answer", maybe_billed=True)
        code = body.get("language_code")
        # the language Sarvam heard, if JARVIS knows it (the engine then says it can't speak it)
        lang = code if isinstance(code, str) and code in LANGUAGES else langs[0]
        prob = body.get("language_probability")
        if isinstance(prob, int | float) and not isinstance(prob, bool):
            confidence = min(1.0, max(0.0, float(prob)))
        else:
            confidence = NO_CONFIDENCE if text.strip() else 0.0
        return Heard(
            lang=lang, text=text.strip()[:MAX_TEXT], confidence=confidence, seconds=seconds
        )


class SarvamVoice(_Sarvam):
    name = SARVAM

    def __init__(
        self,
        http: httpx.AsyncClient,
        key: SecretStr,
        meter: SpeechMeter,
        *,
        enabled: Enabled,
        inr_per_10k_chars: float,
        speaker: str = SARVAM_SPEAKER,
        policy: RetryPolicy = IN_CALL,
        sleep: Sleep = asyncio.sleep,
    ) -> None:
        super().__init__(http, key, meter, enabled=enabled, policy=policy, sleep=sleep)
        self.inr_per_char = inr_per_10k_chars / 10_000
        self.speaker = speaker

    async def speak(self, text: str, lang: str) -> bytes:
        if not speaks(SARVAM, lang):
            raise NotOffered(SARVAM, lang)
        await self._require_on()
        say = " ".join(text.split())
        if not say or len(say) > MAX_SAY_CHARS:
            raise SpeechRejected(SARVAM)
        r = await self._paid(
            "voice",
            TTS_KEY,
            float(len(say)),
            self.inr_per_char,
            url=TTS_URL,
            api="tts",
            json={
                "text": say,
                "language_code": lang,
                "speaker": self.speaker,
                "model": TTS_MODEL,
                "speech_sample_rate": 16_000,
            },
        )
        audios = json_body(r, SARVAM).get("audios")
        if not isinstance(audios, list) or not audios or not isinstance(audios[0], str):
            raise OptionUnavailable(SARVAM, "bad_answer", maybe_billed=True)
        try:
            return pcm_from_wav(base64.b64decode(audios[0], validate=True))
        except (binascii.Error, ValueError, AudioFormatError):
            raise OptionUnavailable(SARVAM, "bad_answer", maybe_billed=True) from None


__all__ = [
    "MAX_AUDIO_S",
    "STT_KEY",
    "STT_MODEL",
    "STT_URL",
    "TTS_KEY",
    "TTS_MODEL",
    "TTS_URL",
    "Enabled",
    "SarvamHearing",
    "SarvamVoice",
]
