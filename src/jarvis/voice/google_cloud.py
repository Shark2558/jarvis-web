# src/jarvis/voice/google_cloud.py
"""Google Cloud Text-to-Speech v1 and Speech-to-Text v1 adapters (slice 9 D2, D3; Layer 6).

REST over httpx — no Google speech SDK — with a bearer token from a `TokenSource` (ADC as
jarvis-run). One total deadline per call (DEADLINE_S, ~12 s) covers the credential lookup AND
the request; inside it httpx allows 3 s to connect and 10 s per phase. Nothing is retried (a
voice reply that arrives late is worse than the browser voice now). Vendor error text never
leaves this module and neither the text, the audio nor the transcript is ever logged (lengths
and statuses only).

    403 (SERVICE_DISABLED, PERMISSION_DENIED, …)  VoiceUnavailable("api_disabled")
    401                                            VoiceUnavailable("upstream_error"), token dropped
    429                                            VoiceBusy
    400 / 404 (invalid voice or text)              VoiceRejected
    5xx                                            VoiceUnavailable("upstream_error")
    2xx with an unreadable body                    VoiceUnavailable("upstream_error", billed?)
    timeout / deadline                             VoiceUnavailable("timeout")
    connection broken after sending                VoiceUnavailable("upstream_error", billed?)

"billed?" = `maybe_billed`: the request may have reached Google (sent, then no or a broken
answer), so the caller meters its estimate. Never set for a clean error answer, nor for a
request that did not leave (credentials, connect, pool).

The voice list is cached 24 h; a list that failed (timeout, 5xx, 429) is remembered 60 s, so a
panel that refreshes doesn't ask Google again each time.
"""

from __future__ import annotations

import asyncio
import base64
import binascii
import re
import time
from collections.abc import Callable
from typing import Any

import httpx

from jarvis.logging import get_logger
from jarvis.voice.ports import (
    TokenSource,
    Transcript,
    VoiceBusy,
    VoiceError,
    VoiceRejected,
    VoiceUnavailable,
)

log = get_logger(__name__)

TTS_URL = "https://texttospeech.googleapis.com/v1/text:synthesize"
VOICES_URL = "https://texttospeech.googleapis.com/v1/voices"
STT_URL = "https://speech.googleapis.com/v1/speech:recognize"
HTTP_TIMEOUT = httpx.Timeout(10.0, connect=3.0)  # per phase, inside the deadline
DEADLINE_S = 12.0  # credentials + request, in all
VOICES_TTL_S = 24 * 3600.0
VOICES_FAIL_TTL_S = 60.0
# Google: latest_short for utterances of a few seconds, latest_long otherwise; both take en-IN
# with automatic punctuation (Speech-to-Text v1 supported-languages table).
SHORT_CLIP_S = 15.0
STT_MODEL = "latest_short"
STT_MODEL_LONG = "latest_long"
_DURATION = re.compile(r"^(\d{1,6}(?:\.\d{1,9})?)s$")
# Failures where the request never left JARVIS: it can't have been billed.
_NOT_SENT = (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout, httpx.ProxyError)


def _reason(r: httpx.Response) -> str:
    """Google's machine-readable reason (e.g. SERVICE_DISABLED) for the log; never its text."""
    try:
        err = r.json().get("error", {})
        for d in err.get("details", []) or []:
            if isinstance(d, dict) and isinstance(d.get("reason"), str):
                return str(d["reason"])[:64]
        return str(err.get("status", ""))[:64]
    except (ValueError, AttributeError):
        return ""


def _raise_for(r: httpx.Response, api: str, tokens: TokenSource) -> None:
    status = r.status_code
    if status < 400:
        return
    log.warning("google speech api error", extra={"api": api, "status": status, "why": _reason(r)})
    if status == 401:
        tokens.invalidate()
        raise VoiceUnavailable("upstream_error")
    if status == 403:
        raise VoiceUnavailable("api_disabled")
    if status == 429:
        raise VoiceBusy()
    if status in (400, 404):
        raise VoiceRejected("Google rejected that voice or text.")
    raise VoiceUnavailable("upstream_error")


async def _call(
    http: httpx.AsyncClient,
    tokens: TokenSource,
    method: str,
    url: str,
    api: str,
    *,
    deadline_s: float = DEADLINE_S,
    json: Any = None,
    params: dict[str, str] | None = None,
) -> dict[str, Any]:
    sent = False  # from the moment the request is handed to httpx, Google may have it
    try:
        async with asyncio.timeout(deadline_s):
            headers = await tokens.headers()
            sent = True
            r = await http.request(
                method, url, json=json, params=params, headers=headers, timeout=HTTP_TIMEOUT
            )
    except TimeoutError:
        log.warning("google speech api: deadline passed", extra={"api": api, "sent": sent})
        raise VoiceUnavailable("timeout", maybe_billed=sent) from None
    except httpx.TimeoutException as exc:
        log.warning("google speech api timed out", extra={"api": api, "why": type(exc).__name__})
        raise VoiceUnavailable("timeout", maybe_billed=not isinstance(exc, _NOT_SENT)) from None
    except httpx.HTTPError as exc:
        log.warning("google speech api unreachable", extra={"api": api, "why": type(exc).__name__})
        billed = isinstance(exc, httpx.TransportError) and not isinstance(exc, _NOT_SENT)
        raise VoiceUnavailable("upstream_error", maybe_billed=billed) from None
    _raise_for(r, api, tokens)
    try:
        body = r.json()
    except ValueError:
        raise VoiceUnavailable("upstream_error", maybe_billed=True) from None
    if not isinstance(body, dict):
        raise VoiceUnavailable("upstream_error", maybe_billed=True)
    return body


class GoogleTTS:
    """`TTSProvider` on Cloud Text-to-Speech v1 (global endpoint, MP3)."""

    def __init__(
        self,
        http: httpx.AsyncClient,
        tokens: TokenSource,
        *,
        clock: Callable[[], float] = time.monotonic,
        deadline_s: float = DEADLINE_S,
    ) -> None:
        self._http = http
        self._tokens = tokens
        self._clock = clock
        self._deadline = deadline_s
        self._voices: dict[str, tuple[float, frozenset[str]]] = {}
        self._voices_failed: dict[str, tuple[float, Callable[[], VoiceError]]] = {}

    async def synthesize(self, text: str, *, voice: str, language: str, rate: float) -> bytes:
        body = {
            "input": {"text": text},
            "voice": {"languageCode": language, "name": voice},
            "audioConfig": {"audioEncoding": "MP3", "speakingRate": rate},
        }
        data = await _call(
            self._http, self._tokens, "POST", TTS_URL, "tts", deadline_s=self._deadline, json=body
        )
        content = data.get("audioContent")
        if not isinstance(content, str) or not content:
            raise VoiceUnavailable("upstream_error", maybe_billed=True)
        try:
            return base64.b64decode(content, validate=True)
        except (binascii.Error, ValueError):
            raise VoiceUnavailable("upstream_error", maybe_billed=True) from None

    async def voices(self, language: str) -> frozenset[str]:
        now = self._clock()
        hit = self._voices.get(language)
        if hit is not None and now - hit[0] < VOICES_TTL_S:
            return hit[1]
        failed = self._voices_failed.get(language)
        if failed is not None and now - failed[0] < VOICES_FAIL_TTL_S:
            raise failed[1]()  # a fresh exception each time (no growing traceback)
        try:
            data = await _call(
                self._http,
                self._tokens,
                "GET",
                VOICES_URL,
                "tts-voices",
                deadline_s=self._deadline,
                params={"languageCode": language},
            )
        except VoiceBusy:
            self._voices_failed[language] = (self._clock(), VoiceBusy)
            raise
        except VoiceUnavailable as exc:
            if exc.reason in ("timeout", "upstream_error"):  # transient: remember a minute
                reason = exc.reason
                self._voices_failed[language] = (self._clock(), lambda: VoiceUnavailable(reason))
            raise
        self._voices_failed.pop(language, None)
        names = frozenset(
            str(v["name"])
            for v in data.get("voices", []) or []
            if isinstance(v, dict) and isinstance(v.get("name"), str)
        )
        self._voices[language] = (self._clock(), names)
        return names


def _seconds(v: object) -> float | None:
    """Google's Duration JSON ("3s", "2.500s") → seconds."""
    if isinstance(v, str) and (m := _DURATION.fullmatch(v)):
        return float(m.group(1))
    return None


class GoogleSTT:
    """`STTProvider` on Cloud Speech-to-Text v1 `speech:recognize` (sync, ≤ 60 s)."""

    def __init__(
        self, http: httpx.AsyncClient, tokens: TokenSource, *, deadline_s: float = DEADLINE_S
    ) -> None:
        self._http = http
        self._tokens = tokens
        self._deadline = deadline_s

    async def recognize(
        self, pcm: bytes, *, sample_rate: int, language: str, phrases: tuple[str, ...]
    ) -> Transcript:
        seconds = len(pcm) / (2 * sample_rate) if sample_rate > 0 else 0.0  # 16-bit mono
        config: dict[str, Any] = {
            "encoding": "LINEAR16",
            "sampleRateHertz": sample_rate,
            "audioChannelCount": 1,
            "languageCode": language,
            "model": STT_MODEL if seconds <= SHORT_CLIP_S else STT_MODEL_LONG,
            "enableAutomaticPunctuation": True,
            "maxAlternatives": 1,
        }
        if phrases:
            config["speechContexts"] = [{"phrases": list(phrases)}]
        body = {"config": config, "audio": {"content": base64.b64encode(pcm).decode("ascii")}}
        data = await _call(
            self._http, self._tokens, "POST", STT_URL, "stt", deadline_s=self._deadline, json=body
        )
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
                confidence = float(c)
            if lang is None and isinstance(res.get("languageCode"), str):
                lang = str(res["languageCode"])[:16]
        return Transcript(
            text=" ".join(parts),
            confidence=confidence,
            billed_seconds=_seconds(data.get("totalBilledTime")),
            language=lang,
        )


__all__ = [
    "DEADLINE_S",
    "HTTP_TIMEOUT",
    "SHORT_CLIP_S",
    "STT_MODEL",
    "STT_MODEL_LONG",
    "STT_URL",
    "TTS_URL",
    "VOICES_FAIL_TTL_S",
    "VOICES_TTL_S",
    "VOICES_URL",
    "GoogleSTT",
    "GoogleTTS",
]
