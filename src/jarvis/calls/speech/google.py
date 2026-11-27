# src/jarvis/calls/speech/google.py
"""Google hearing and voice for calls (R18 B; Layer 6), reusing `jarvis.voice` — not a copy of it.

What is reused: `jarvis.voice.google_cloud`'s request (`_call`: the ADC bearer token from the
voice's `TokenSource`, its deadline, its status mapping to the voice errors, `maybe_billed`), its
URLs and Duration parser, and `jarvis.voice.catalogue.PriceList` (the voice's own allowance keys,
so calls and JARVIS's English voice share ONE free allowance, metered by `SpeechMeter`).

What a call needs on top, and only here:

    hearing  Speech-to-Text v1 `speech:recognize` on one utterance (the desk sends audio only while
             the other person speaks): LINEAR16 16 kHz; `latest_short` for one language; with
             several, the first is `languageCode` and up to 3 others `alternativeLanguageCodes`
             (Google's language detection; Google's default model, as its docs require), and the
             detected language comes back in the result. A refused alternatives request is tried
             once more with the first language alone (detection then falls to the caller).
    voice    Text-to-Speech v1 in Chirp 3: HD (`{lang}-Chirp3-HD-Algieba`, a stock voice),
             LINEAR16 at 16 kHz: Google returns a WAV, read into PCM16 16 kHz mono.

Retries (backoff, within the policy's deadline) only where Google surely did not bill: a 429 or a
clean 5xx / connection failure. A request that may have reached Google and failed (a timeout, an
unreadable answer, a cancel) is metered on its estimate, as the voice does. Audio, text and
transcripts are never logged.
"""

from __future__ import annotations

import asyncio
import base64
import binascii
import math
import random
from collections.abc import Callable, Sequence
from typing import Any

import httpx

from jarvis.calls.models import Heard
from jarvis.calls.speech.audio import AudioFormatError, pcm_from_wav, pcm_seconds
from jarvis.calls.speech.catalogue import GOOGLE, GOOGLE_VOICE_STEM, google_voice, hears, speaks
from jarvis.calls.speech.errors import (
    NotOffered,
    OptionUnavailable,
    Reason,
    SpeechBusy,
    SpeechRejected,
)
from jarvis.calls.speech.meter import SpeechMeter
from jarvis.calls.speech.rest import IN_CALL, RetryPolicy, Sleep, backoff
from jarvis.logging import get_logger
from jarvis.voice.catalogue import Price, PriceList
from jarvis.voice.google_cloud import STT_MODEL, STT_URL, TTS_URL, _call, _seconds
from jarvis.voice.ports import TokenSource, VoiceBusy, VoiceRejected, VoiceUnavailable

log = get_logger(__name__)

MAX_ALTERNATIVE_LANGUAGES = 3  # Google: "up to 3 additional BCP-47 language tags"
MAX_SAY_CHARS = 1_000  # one spoken reply; the brain speaks in short sentences
MAX_TEXT = 4_000  # Heard.text
NO_CONFIDENCE = 0.5  # Google gave words but no confidence: "unknown", neither sure nor unsure
_REASONS: dict[str, Reason] = {
    "api_disabled": "off",
    "not_configured": "not_configured",
    "upstream_error": "upstream_error",
    "timeout": "timeout",
}


class _Google:
    """The request both adapters make: `_call` with retries and the speech errors."""

    def __init__(
        self,
        http: httpx.AsyncClient,
        tokens: TokenSource,
        meter: SpeechMeter,
        prices: PriceList,
        *,
        policy: RetryPolicy = IN_CALL,
        sleep: Sleep = asyncio.sleep,
        rng: Callable[[], float] = random.random,
    ) -> None:
        self._http = http
        self._tokens = tokens
        self.meter = meter
        self.prices = prices
        self.policy = policy
        self._sleep = sleep
        self._rng = rng

    async def _once(self, url: str, api: str, body: dict[str, Any]) -> dict[str, Any]:
        try:
            return await _call(
                self._http, self._tokens, "POST", url, api, deadline_s=self.policy.deadline_s,
                json=body,
            )  # fmt: skip
        except VoiceUnavailable as exc:
            raise OptionUnavailable(
                GOOGLE, _REASONS.get(exc.reason, "upstream_error"), maybe_billed=exc.maybe_billed
            ) from None
        except VoiceBusy:
            raise SpeechBusy(GOOGLE) from None
        except VoiceRejected:
            raise SpeechRejected(GOOGLE) from None

    async def _retrying(self, url: str, api: str, body: dict[str, Any]) -> dict[str, Any]:
        attempts = max(1, self.policy.attempts)
        for attempt in range(attempts):
            try:
                return await self._once(url, api, body)
            except SpeechBusy:
                if attempt == attempts - 1:
                    raise
            except OptionUnavailable as exc:
                sticky = exc.reason in ("off", "not_configured", "auth")
                if exc.maybe_billed or sticky or attempt == attempts - 1:
                    raise
            await self._sleep(backoff(self.policy, attempt, None, self._rng))
        raise AssertionError("unreachable")

    async def post(self, url: str, api: str, body: dict[str, Any]) -> dict[str, Any]:
        try:
            async with asyncio.timeout(self.policy.deadline_s):
                return await self._retrying(url, api, body)
        except TimeoutError:
            raise OptionUnavailable(GOOGLE, "timeout", maybe_billed=True) from None

    async def metered(
        self, part: str, price: Price, estimate: float, url: str, api: str, body: dict[str, Any]
    ) -> dict[str, Any]:
        """Gate, call, and meter a failure that Google may have billed (on the estimate)."""
        await self.meter.gate(GOOGLE, price, estimate)
        try:
            return await self.post(url, api, body)
        except OptionUnavailable as exc:
            if exc.maybe_billed:
                self.meter.report(part, await self.meter.charge(price, estimate))
            raise
        except asyncio.CancelledError:  # the call moved on mid-request: Google may have it
            self.meter.report(part, await self.meter.charge(price, estimate))
            raise


def _parse(data: dict[str, Any]) -> tuple[str, float | None, str | None]:
    parts: list[str] = []
    confidence: float | None = None
    lang: str | None = None
    for res in data.get("results", []) or []:
        alts = res.get("alternatives") if isinstance(res, dict) else None
        if not alts or not isinstance(alts[0], dict):
            continue
        text = alts[0].get("transcript")
        if isinstance(text, str) and text.strip():
            parts.append(text.strip())
        c = alts[0].get("confidence")
        if confidence is None and isinstance(c, int | float) and not isinstance(c, bool):
            confidence = min(1.0, max(0.0, float(c)))
        if lang is None and isinstance(res.get("languageCode"), str):
            lang = str(res["languageCode"])[:16]
    return " ".join(parts), confidence, lang


class GoogleHearing(_Google):
    """`Hearing` on Speech-to-Text v1 (see the module docstring)."""

    name = GOOGLE

    def _config(self, langs: Sequence[str]) -> dict[str, Any]:
        config: dict[str, Any] = {
            "encoding": "LINEAR16",
            "sampleRateHertz": 16_000,
            "audioChannelCount": 1,
            "languageCode": langs[0],
            "enableAutomaticPunctuation": True,
        }
        if len(langs) > 1:
            config["alternativeLanguageCodes"] = list(langs[1:])
        else:
            config["model"] = STT_MODEL
        return config

    async def _recognise(
        self, pcm16k: bytes, langs: Sequence[str], estimate: float
    ) -> tuple[dict[str, Any], Sequence[str]]:
        audio = {"content": base64.b64encode(pcm16k).decode("ascii")}
        price = self.prices.stt
        try:
            body = {"config": self._config(langs), "audio": audio}
            return await self.metered("hearing", price, estimate, STT_URL, "calls-stt", body), langs
        except SpeechRejected:
            if len(langs) == 1:
                raise
        log.warning("google refused the alternative languages; the first language alone")
        first = langs[:1]
        body = {"config": self._config(first), "audio": audio}
        return await self.metered("hearing", price, estimate, STT_URL, "calls-stt", body), first

    async def transcribe(self, pcm16k: bytes, languages: Sequence[str]) -> Heard:
        langs = [x for x in dict.fromkeys(languages) if hears(GOOGLE, x)]
        if not langs:
            raise NotOffered(GOOGLE, ", ".join(languages) or "no language")
        langs = langs[: 1 + MAX_ALTERNATIVE_LANGUAGES]
        seconds = pcm_seconds(pcm16k)
        estimate = float(math.ceil(seconds))
        data, asked = await self._recognise(pcm16k, langs, estimate)
        billed = _seconds(data.get("totalBilledTime"))
        self.meter.report(
            "hearing", await self.meter.charge(self.prices.stt, billed if billed else estimate)
        )
        text, confidence, code = _parse(data)
        by_lower = {x.lower(): x for x in asked}
        lang = by_lower.get((code or "").lower(), asked[0])
        if confidence is None:
            confidence = NO_CONFIDENCE if text else 0.0
        return Heard(lang=lang, text=text[:MAX_TEXT], confidence=confidence, seconds=seconds)


class GoogleVoice(_Google):
    """`Voice` on Text-to-Speech v1, Chirp 3: HD, LINEAR16 16 kHz."""

    name = GOOGLE

    def __init__(
        self,
        http: httpx.AsyncClient,
        tokens: TokenSource,
        meter: SpeechMeter,
        prices: PriceList,
        *,
        stem: str = GOOGLE_VOICE_STEM,
        policy: RetryPolicy = IN_CALL,
        sleep: Sleep = asyncio.sleep,
        rng: Callable[[], float] = random.random,
    ) -> None:
        super().__init__(http, tokens, meter, prices, policy=policy, sleep=sleep, rng=rng)
        self.stem = stem

    async def speak(self, text: str, lang: str) -> bytes:
        if not speaks(GOOGLE, lang):
            raise NotOffered(GOOGLE, lang)
        say = " ".join(text.split())
        if not say or len(say) > MAX_SAY_CHARS:
            raise SpeechRejected(GOOGLE)
        price = self.prices.chirp3_hd
        body = {
            "input": {"text": say},
            "voice": {"languageCode": lang, "name": google_voice(lang, self.stem)},
            "audioConfig": {"audioEncoding": "LINEAR16", "sampleRateHertz": 16_000},
        }
        data = await self.metered("voice", price, float(len(say)), TTS_URL, "calls-tts", body)
        # Google answered: the characters are billed, readable audio or not
        self.meter.report("voice", await self.meter.charge(price, float(len(say))))
        return _audio(data)


def _audio(data: dict[str, Any]) -> bytes:
    content = data.get("audioContent")
    if not isinstance(content, str) or not content:
        raise OptionUnavailable(GOOGLE, "bad_answer", maybe_billed=True)
    try:
        raw = base64.b64decode(content, validate=True)
        return pcm_from_wav(raw) if raw[:4] == b"RIFF" else raw[: len(raw) // 2 * 2]
    except (binascii.Error, ValueError, AudioFormatError):
        raise OptionUnavailable(GOOGLE, "bad_answer", maybe_billed=True) from None


__all__ = [
    "MAX_ALTERNATIVE_LANGUAGES",
    "MAX_SAY_CHARS",
    "NO_CONFIDENCE",
    "GoogleHearing",
    "GoogleVoice",
]
