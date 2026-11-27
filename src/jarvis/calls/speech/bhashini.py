# src/jarvis/calls/speech/bhashini.py
"""Bhashini (Government of India) over REST (R18 B; Layer 6): optional, off unless configured.

Bhashini's ULCA pipeline is two calls:

    config   POST https://meity-auth.ulcacontrib.org/ulca/apis/v0/model/getModelsPipeline with
             the owner's `userID` and `ulcaApiKey` headers, the task (asr / tts), the language and
             MeitY's pipeline id → a `callbackUrl`, an `inferenceApiKey` {name, value} and the
             task's `serviceId`. Cached an hour per task and language.
    compute  POST callbackUrl with the header {name: value}:
             asr  `audioFormat` wav, `samplingRate` 16000, `inputData.audio[0].audioContent` (a
                  base64 16 kHz PCM16 WAV) → `pipelineResponse[0].output[0].source`
             tts  `gender` male, `samplingRate` 16000, `inputData.input[0].source` (the text) →
                  `pipelineResponse[0].audio[0].audioContent` (a base64 WAV, read to PCM16 16 kHz)

The config call's answer is untrusted data: the callback must be https on Bhashini's own domains
(`bhashini.gov.in`, `ulcacontrib.org`), else nothing is sent there (`bad_answer`). Languages use
Bhashini's ISO 639 codes (`catalogue.Language.short`). Plan 5.1: its data terms are read before
any use, and it is tried only when a language fails the other options; speed for live calls is
unknown (the language check measures it).

Price: Bhashini publishes none for this use. Hearing is priced only if the owner set
`voice_price_bhashini_inr_per_minute` (₹ metered, limit-checked); otherwise each part reports its
cost as None — unknown, never ₹0 (`jarvis.calls.prices`). The keys are never logged.
"""

from __future__ import annotations

import asyncio
import base64
import binascii
import math
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

import httpx
from pydantic import SecretStr

from jarvis.calls.models import Heard
from jarvis.calls.speech.audio import AudioFormatError, pcm_from_wav, pcm_seconds, wav_from_pcm
from jarvis.calls.speech.catalogue import BHASHINI, hears, language, speaks
from jarvis.calls.speech.errors import NotOffered, OptionUnavailable, SpeechRejected
from jarvis.calls.speech.meter import SpeechMeter
from jarvis.calls.speech.rest import IN_CALL, RetryPolicy, Sleep, json_body, send

CONFIG_URL = "https://meity-auth.ulcacontrib.org/ulca/apis/v0/model/getModelsPipeline"
PIPELINE_ID = "64392f96daac500b55c543cd"  # MeitY's public pipeline (Bhashini's API docs)
CONFIG_TTL_S = 3_600.0
ALLOWED_HOSTS = ("bhashini.gov.in", "ulcacontrib.org")
STT_KEY = "bhashini_stt_seconds"
MAX_AUDIO_S = 60.0
MAX_SAY_CHARS = 1_000
MAX_TEXT = 4_000
NO_CONFIDENCE = 0.5  # Bhashini returns no confidence: "unknown"


@dataclass(frozen=True)
class Endpoint:
    url: str
    header: tuple[str, str]
    service_id: str


def _host_ok(url: str) -> bool:
    parts = urlsplit(url)
    host = (parts.hostname or "").lower()
    domain_ok = any(host == d or host.endswith("." + d) for d in ALLOWED_HOSTS)
    return parts.scheme == "https" and domain_ok and parts.username is None


def _endpoint(body: dict[str, Any], task: str) -> Endpoint:
    try:
        api = body["pipelineInferenceAPIEndPoint"]
        key = api["inferenceApiKey"]
        url, name, value = str(api["callbackUrl"]), str(key["name"]), str(key["value"])
        configs = next(c for c in body["pipelineResponseConfig"] if c.get("taskType") == task)
        service = str(configs["config"][0]["serviceId"])
    except (KeyError, IndexError, TypeError, StopIteration, AttributeError):
        raise OptionUnavailable(BHASHINI, "bad_answer") from None
    if not _host_ok(url) or not name or not service:
        raise OptionUnavailable(BHASHINI, "bad_answer")
    return Endpoint(url, (name, value), service)


class BhashiniPipeline:
    """The ULCA config call, cached; shared by Bhashini's hearing and voice."""

    def __init__(
        self,
        http: httpx.AsyncClient,
        user_id: str,
        api_key: SecretStr,
        *,
        policy: RetryPolicy = IN_CALL,
        sleep: Sleep = asyncio.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.http = http
        self._user = user_id
        self._key = api_key
        self.policy = policy
        self.sleep = sleep
        self._clock = clock
        self._cache: dict[tuple[str, str], tuple[float, Endpoint]] = {}

    async def endpoint(self, task: str, short: str) -> Endpoint:
        hit = self._cache.get((task, short))
        if hit is not None and self._clock() - hit[0] < CONFIG_TTL_S:
            return hit[1]
        r = await send(
            self.http, "POST", CONFIG_URL, option=BHASHINI, api=f"config-{task}",
            policy=self.policy, sleep=self.sleep,
            headers={"userID": self._user, "ulcaApiKey": self._key.get_secret_value()},
            json={
                "pipelineTasks": [
                    {"taskType": task, "config": {"language": {"sourceLanguage": short}}}
                ],
                "pipelineRequestConfig": {"pipelineId": PIPELINE_ID},
            },
        )  # fmt: skip
        found = _endpoint(json_body(r, BHASHINI), task)
        self._cache[(task, short)] = (self._clock(), found)
        return found

    async def compute(self, task: str, short: str, config: dict[str, Any], data: Any) -> Any:
        ep = await self.endpoint(task, short)
        body = {
            "pipelineTasks": [
                {
                    "taskType": task,
                    "config": {
                        "language": {"sourceLanguage": short},
                        "serviceId": ep.service_id,
                        **config,
                    },
                }
            ],
            "inputData": data,
        }
        r = await send(
            self.http, "POST", ep.url, option=BHASHINI, api=task, policy=self.policy,
            sleep=self.sleep, headers={ep.header[0]: ep.header[1]}, json=body,
        )  # fmt: skip
        try:
            return json_body(r, BHASHINI)["pipelineResponse"][0]
        except (KeyError, IndexError, TypeError):
            raise OptionUnavailable(BHASHINI, "bad_answer", maybe_billed=True) from None


class BhashiniHearing:
    name = BHASHINI

    def __init__(
        self, pipeline: BhashiniPipeline, meter: SpeechMeter, *, inr_per_minute: float | None
    ) -> None:
        self.pipeline = pipeline
        self.meter = meter
        self.inr_per_minute = inr_per_minute

    async def transcribe(self, pcm16k: bytes, languages: Sequence[str]) -> Heard:
        lang = next((x for x in languages if hears(BHASHINI, x)), None)
        if lang is None:
            raise NotOffered(BHASHINI, ", ".join(languages) or "no language")
        seconds = pcm_seconds(pcm16k)
        if seconds > MAX_AUDIO_S:
            raise SpeechRejected(BHASHINI)
        units = float(max(1, math.ceil(seconds)))
        if self.inr_per_minute is not None:
            await self.meter.gate_inr(BHASHINI, STT_KEY, units)
        audio = base64.b64encode(wav_from_pcm(pcm16k)).decode("ascii")
        out = await self.pipeline.compute(
            "asr",
            language(lang).short,
            {"audioFormat": "wav", "samplingRate": 16_000},
            {"audio": [{"audioContent": audio}]},
        )
        await self._meter(units)
        try:
            text = str(out["output"][0]["source"]).strip()
        except (KeyError, IndexError, TypeError):
            raise OptionUnavailable(BHASHINI, "bad_answer", maybe_billed=True) from None
        conf = NO_CONFIDENCE if text else 0.0
        return Heard(lang=lang, text=text[:MAX_TEXT], confidence=conf, seconds=seconds)

    async def _meter(self, units: float) -> None:
        if self.inr_per_minute is None:
            self.meter.report("hearing", None)  # unknown, never ₹0
            return
        inr = await self.meter.charge_inr(STT_KEY, units, self.inr_per_minute / 60)
        self.meter.report("hearing", inr)


class BhashiniVoice:
    name = BHASHINI

    def __init__(self, pipeline: BhashiniPipeline, meter: SpeechMeter) -> None:
        self.pipeline = pipeline
        self.meter = meter

    async def speak(self, text: str, lang: str) -> bytes:
        if not speaks(BHASHINI, lang):
            raise NotOffered(BHASHINI, lang)
        say = " ".join(text.split())
        if not say or len(say) > MAX_SAY_CHARS:
            raise SpeechRejected(BHASHINI)
        out = await self.pipeline.compute(
            "tts",
            language(lang).short,
            {"gender": "male", "samplingRate": 16_000},
            {"input": [{"source": say}]},
        )
        self.meter.report("voice", None)  # Bhashini's voice has no known price
        try:
            raw = base64.b64decode(str(out["audio"][0]["audioContent"]), validate=True)
            return pcm_from_wav(raw)
        except (KeyError, IndexError, TypeError, binascii.Error, ValueError, AudioFormatError):
            raise OptionUnavailable(BHASHINI, "bad_answer", maybe_billed=True) from None


__all__ = [
    "ALLOWED_HOSTS",
    "CONFIG_TTL_S",
    "CONFIG_URL",
    "PIPELINE_ID",
    "BhashiniHearing",
    "BhashiniPipeline",
    "BhashiniVoice",
    "Endpoint",
]
