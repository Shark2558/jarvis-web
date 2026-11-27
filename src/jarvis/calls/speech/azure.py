# src/jarvis/calls/speech/azure.py
"""Microsoft Azure Speech, free tier F0, over REST (R18 B; Layer 6). No SDK: httpx only.

    hearing  speech-to-text REST for short audio (≤ 60 s, one utterance):
             POST https://{region}.stt.speech.microsoft.com/speech/recognition/conversation/
                  cognitiveservices/v1?language={lang}&format=detailed&profanity=raw
             a 16 kHz PCM16 WAV body; NBest[0].Display and .Confidence come back. This REST API
             does no language detection: the first language Azure lists is heard (detection is
             `jarvis.calls.speech.detect`'s, by confidence and script).
    voice    POST https://{region}.tts.speech.microsoft.com/cognitiveservices/v1, SSML with a stock
             male neural voice of the language (`catalogue`), output `raw-16khz-16bit-mono-pcm`:
             JARVIS's format as it is.

F0 cannot bill: its price is ₹0 (`jarvis.calls.prices`). It stops at its monthly allowance (5
hours of hearing, 0.5 M characters of voice), so every request first HOLDS its units on the
deployment's allowance counter (`SpeechMeter.hold`: whole seconds; for voice the whole SSML
request, the safe side) and gives them back when Azure surely did not count it (a clean refusal,
a throttle, the quota answer). Past the allowance the option stops and says so plainly
(`AllowanceUsedUp`), before any request; Azure's own "out of call volume quota" 403 says the same,
never "bad key". The key travels only in `Ocp-Apim-Subscription-Key` and is never logged.
"""

from __future__ import annotations

import asyncio
import math
import random
from collections.abc import Awaitable, Callable, Sequence
from typing import TypeVar
from xml.sax.saxutils import escape, quoteattr

import httpx
from pydantic import SecretStr

from jarvis.calls.models import Heard
from jarvis.calls.speech.audio import pcm_seconds, wav_from_pcm
from jarvis.calls.speech.catalogue import AZURE, hears, language, speaks
from jarvis.calls.speech.errors import (
    AllowanceUsedUp,
    NotOffered,
    OptionUnavailable,
    SpeechBusy,
    SpeechRejected,
)
from jarvis.calls.speech.meter import FreeAllowance, SpeechMeter
from jarvis.calls.speech.rest import IN_CALL, RetryPolicy, Sleep, json_body, send

T = TypeVar("T")

MAX_AUDIO_S = 60.0  # the short-audio REST API's limit
MAX_SAY_CHARS = 1_000
MAX_TEXT = 4_000
STT_KEY, TTS_KEY = "azure_stt_seconds", "azure_tts_chars"
OUTPUT_FORMAT = "raw-16khz-16bit-mono-pcm"
_EMPTY = frozenset({"NoMatch", "InitialSilenceTimeout", "BabbleTimeout"})


def stt_url(region: str) -> str:
    return (
        f"https://{region}.stt.speech.microsoft.com/speech/recognition/conversation/"
        "cognitiveservices/v1"
    )


def tts_url(region: str) -> str:
    return f"https://{region}.tts.speech.microsoft.com/cognitiveservices/v1"


def allowances(stt_free_seconds: float, tts_free_chars: float) -> tuple[FreeAllowance, ...]:
    """F0's monthly allowances (`Settings.voice_azure_f0_*`) as the meter holds them."""
    return (
        FreeAllowance(STT_KEY, float(stt_free_seconds), "hearing"),
        FreeAllowance(TTS_KEY, float(tts_free_chars), "voice"),
    )


class _Azure:
    def __init__(
        self,
        http: httpx.AsyncClient,
        key: SecretStr,
        region: str,
        meter: SpeechMeter,
        *,
        allowance: FreeAllowance,
        policy: RetryPolicy = IN_CALL,
        sleep: Sleep = asyncio.sleep,
        rng: Callable[[], float] = random.random,
    ) -> None:
        self._http = http
        self._key = key
        self.region = region
        self.meter = meter
        self.allowance = allowance
        self.policy = policy
        self._sleep = sleep
        self._rng = rng

    async def _post(
        self,
        url: str,
        api: str,
        *,
        headers: dict[str, str],
        content: bytes,
        params: dict[str, str] | None = None,
    ) -> httpx.Response:
        r = await send(
            self._http,
            "POST",
            url,
            option=AZURE,
            api=api,
            policy=self.policy,
            sleep=self._sleep,
            rng=self._rng,
            headers={"Ocp-Apim-Subscription-Key": self._key.get_secret_value(), **headers},
            content=content,
            params=params,
            passthrough=frozenset({403}),
        )
        if r.status_code == 403:
            if "quota" in r.text.casefold():  # F0's own wall: its allowance, not the key
                raise AllowanceUsedUp(AZURE, self.allowance.what)
            raise OptionUnavailable(AZURE, "auth")
        return r

    async def _held(self, units: float, call: Callable[[], Awaitable[T]]) -> T:
        hold = await self.meter.hold(AZURE, self.allowance, units)
        try:
            return await call()
        except (SpeechBusy, SpeechRejected, AllowanceUsedUp):
            await self.meter.give_back(hold)
            raise
        except OptionUnavailable as exc:
            if not exc.maybe_billed:
                await self.meter.give_back(hold)
            raise


class AzureHearing(_Azure):
    """`Hearing` on Azure's short-audio REST API (F0)."""

    name = AZURE

    async def _recognise(self, pcm16k: bytes, lang: str) -> tuple[str, float]:
        r = await self._post(
            stt_url(self.region),
            "stt",
            params={"language": lang, "format": "detailed", "profanity": "raw"},
            headers={
                "Content-Type": "audio/wav; codecs=audio/pcm; samplerate=16000",
                "Accept": "application/json",
            },
            content=wav_from_pcm(pcm16k),
        )
        body = json_body(r, AZURE)
        status = body.get("RecognitionStatus")
        if status in _EMPTY:
            return "", 0.0
        if status != "Success":
            raise OptionUnavailable(AZURE, "upstream_error", maybe_billed=True)
        best = body.get("NBest")
        top = best[0] if isinstance(best, list) and best and isinstance(best[0], dict) else {}
        text = top.get("Display", body.get("DisplayText", ""))
        conf = top.get("Confidence", 0.0)
        if not isinstance(text, str):
            raise OptionUnavailable(AZURE, "bad_answer", maybe_billed=True)
        ok = isinstance(conf, int | float) and not isinstance(conf, bool)
        return text.strip(), min(1.0, max(0.0, float(conf))) if ok else 0.0

    async def transcribe(self, pcm16k: bytes, languages: Sequence[str]) -> Heard:
        lang = next((x for x in languages if hears(AZURE, x)), None)
        if lang is None:
            raise NotOffered(AZURE, ", ".join(languages) or "no language")
        seconds = pcm_seconds(pcm16k)
        if seconds > MAX_AUDIO_S:
            raise SpeechRejected(AZURE)
        text, conf = await self._held(
            float(max(1, math.ceil(seconds))), lambda: self._recognise(pcm16k, lang)
        )
        self.meter.report("hearing", 0.0)  # F0 cannot bill
        return Heard(lang=lang, text=text[:MAX_TEXT], confidence=conf, seconds=seconds)


def ssml(text: str, lang: str, voice: str) -> str:
    return (
        f"<speak version='1.0' xml:lang={quoteattr(lang)}>"
        f"<voice name={quoteattr(voice)}>{escape(text)}</voice></speak>"
    )


class AzureVoice(_Azure):
    """`Voice` on Azure's neural text-to-speech REST API (F0), raw 16 kHz PCM16."""

    name = AZURE

    async def speak(self, text: str, lang: str) -> bytes:
        voice = language(lang).azure_voice if speaks(AZURE, lang) else None
        if voice is None:
            raise NotOffered(AZURE, lang)
        say = " ".join(text.split())
        if not say or len(say) > MAX_SAY_CHARS:
            raise SpeechRejected(AZURE)
        body = ssml(say, lang, voice).encode("utf-8")

        async def call() -> bytes:
            r = await self._post(
                tts_url(self.region),
                "tts",
                headers={
                    "Content-Type": "application/ssml+xml",
                    "X-Microsoft-OutputFormat": OUTPUT_FORMAT,
                    "User-Agent": "jarvis-calls",
                },
                content=body,
            )
            if not r.content:
                raise OptionUnavailable(AZURE, "bad_answer", maybe_billed=True)
            return r.content[: len(r.content) // 2 * 2]

        pcm = await self._held(float(len(body.decode("utf-8"))), call)
        self.meter.report("voice", 0.0)  # F0 cannot bill
        return pcm


__all__ = [
    "MAX_AUDIO_S",
    "OUTPUT_FORMAT",
    "STT_KEY",
    "TTS_KEY",
    "AzureHearing",
    "AzureVoice",
    "allowances",
    "ssml",
    "stt_url",
    "tts_url",
]
