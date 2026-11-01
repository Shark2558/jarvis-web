# src/jarvis/voice/service.py
"""Voice, tied together (slice 9; Layers 2, 4 and 8): settings, availability, the spending gate,
the engines and the meter.

    speak       text (1–1,200) → speakable() (≤ 600) → gate (only if priced) → TTS → meter
    transcribe  WAV → strict parse → gate (only if priced) → STT → meter (Google's billed time)
    view        settings, cloud status, voices (validated against Google's list), wit levels,
                this month's allowance use and voice rupees
    wit_for     the Brain's persona variant (never raises; any failure → "film")

Availability (D10): Google answering 403 or no credentials marks that API unavailable for 10
minutes (no calls meanwhile); timeouts and 5xx are reported but not remembered. Privacy (D13): no
audio is stored; text and transcripts are never logged (lengths only).
"""

from __future__ import annotations

import math
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

import httpx
from pydantic import BaseModel, ConfigDict, Field

from jarvis.billing import Billing
from jarvis.config import Settings
from jarvis.core.prompts import DEFAULT_WIT, WIT_LEVELS
from jarvis.logging import get_logger
from jarvis.storage.docs import Docs
from jarvis.voice.catalogue import (
    METER_LABEL,
    SAMPLE_LINE,
    TYPES,
    VOICE_LANGUAGE,
    VOICES,
    PriceList,
    Voice,
    find_voice,
)
from jarvis.voice.ports import (
    NothingToSay,
    Reason,
    STTProvider,
    TokenSource,
    TTSProvider,
    VoiceError,
    VoiceRejected,
    VoiceUnavailable,
)
from jarvis.voice.settings import (
    CACHE_S,
    VoiceSettings,
    VoiceSettingsPatch,
    VoiceSettingsStore,
    rate_ok,
)
from jarvis.voice.speakable import speakable
from jarvis.voice.wav import parse_wav

log = get_logger(__name__)

MAX_TEXT_IN = 1_200
DOWN_TTL_S = 600.0
STICKY: frozenset[str] = frozenset({"api_disabled", "not_configured"})
Api = Literal["tts", "stt"]
State = Literal["ready", "off", "unavailable"]


# ---- views -----------------------------------------------------------------------------------


class CloudStatus(BaseModel):
    tts: State
    stt: State
    reason: Reason | None


class VoiceOption(BaseModel):
    id: str
    label: str
    style: str
    type: str
    available: bool


class WitOption(BaseModel):
    id: str
    label: str
    description: str


class TypeUse(BaseModel):
    used: int
    free: int


class TtsAllowance(BaseModel):
    type: str  # the owner's current voice type; used/free below are for it
    used_chars: int
    free_chars: int
    by_type: dict[str, TypeUse]


class SttAllowance(BaseModel):
    used_seconds: float
    free_seconds: int


class Allowance(BaseModel):
    tts: TtsAllowance
    stt: SttAllowance


class VoiceMonth(BaseModel):
    month: str
    voice_inr: float


class VoiceView(BaseModel):
    cloud: CloudStatus
    settings: VoiceSettings
    voices: list[VoiceOption]
    wit_levels: list[WitOption]
    allowance: Allowance
    month: VoiceMonth
    language: str


class SpeakRequest(BaseModel):
    """POST /v1/voice/speak. `{preview: true, voice}` reads the server's fixed sample line."""

    model_config = ConfigDict(extra="ignore")

    text: str | None = None
    voice: str | None = Field(default=None, max_length=64)
    rate: float | None = None
    preview: bool = False


class TranscriptView(BaseModel):
    text: str
    confidence: float | None
    seconds: float
    cost_inr: float
    language: str
    no_speech: bool


@dataclass(frozen=True)
class Speech:
    audio: bytes
    chars: int
    cost_inr: float
    voice: str


@dataclass(frozen=True)
class VoiceEngines:
    """The cloud side, injectable (tests, evals, a future vendor)."""

    tts: TTSProvider
    stt: STTProvider
    tokens: TokenSource | None = None
    http: httpx.AsyncClient | None = None  # closed with the service


# ---- the service -----------------------------------------------------------------------------


class VoiceService:
    def __init__(
        self,
        *,
        store: VoiceSettingsStore,
        billing: Billing,
        prices: PriceList,
        engines: VoiceEngines | None,
        language: str,
        honorific: str,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.store = store
        self.billing = billing
        self.prices = prices
        self.engines = engines
        self.language = language
        self.honorific = honorific
        self._clock = clock
        self._down: dict[Api, tuple[float, Reason]] = {}
        self._wit_fail_until: dict[str, float] = {}
        self.phrases = tuple(dict.fromkeys(("JARVIS", "Jarvis", honorific)))

    # ---- availability ----------------------------------------------------------------------

    def state(self, api: Api) -> tuple[State, Reason | None]:
        if self.engines is None:
            return "off", None
        tokens = self.engines.tokens
        if tokens is not None and tokens.not_configured:
            return "unavailable", "not_configured"
        down = self._down.get(api)
        if down is not None and self._clock() < down[0]:
            return "unavailable", down[1]
        return "ready", None

    def _note(self, api: Api, exc: VoiceUnavailable) -> None:
        if exc.reason in STICKY:
            self._down[api] = (self._clock() + DOWN_TTL_S, exc.reason)
        log.warning("cloud voice unavailable", extra={"api": api, "reason": exc.reason})

    def _require(self, api: Api) -> VoiceEngines:
        state, reason = self.state(api)
        if self.engines is None or state == "off":
            raise VoiceUnavailable("not_configured")
        if state == "unavailable":
            raise VoiceUnavailable(reason or "upstream_error")
        return self.engines

    # ---- settings ----------------------------------------------------------------------------

    async def settings_of(self, uid: str) -> VoiceSettings:
        """The owner's settings; the defaults (logged) when storage can't be read."""
        try:
            return await self.store.get(uid)
        except Exception as exc:  # noqa: BLE001 — speaking with defaults beats not speaking
            log.warning("voice settings unreadable", extra={"reason": type(exc).__name__})
            return VoiceSettings()

    async def update_settings(self, uid: str, patch: VoiceSettingsPatch) -> VoiceSettings:
        return await self.store.update(uid, patch)

    async def wit_for(self, uid: str) -> str:
        """The persona's wit level. Never raises; a failed read is not retried for 30 s."""
        if self._clock() < self._wit_fail_until.get(uid, 0.0):
            return DEFAULT_WIT
        try:
            return (await self.store.get(uid)).wit
        except Exception as exc:  # noqa: BLE001 — a persona nicety never fails a reply
            self._wit_fail_until[uid] = self._clock() + CACHE_S
            log.warning("wit level unreadable", extra={"reason": type(exc).__name__})
            return DEFAULT_WIT

    # ---- the owner's view --------------------------------------------------------------------

    async def _known_voices(self) -> frozenset[str] | None:
        """Google's voice ids (cached 24 h by the adapter); None when they can't be read."""
        if self.engines is None or self.state("tts")[0] != "ready":
            return None
        try:
            return await self.engines.tts.voices(VOICE_LANGUAGE)
        except VoiceUnavailable as exc:
            self._note("tts", exc)
        except VoiceError as exc:
            log.warning("voice list unreadable", extra={"reason": type(exc).__name__})
        return None

    async def view(self, uid: str) -> VoiceView:
        settings = await self.settings_of(uid)
        known = await self._known_voices()
        tts, tts_why = self.state("tts")
        stt, stt_why = self.state("stt")
        m = await self.billing.month(uid)  # BudgetUnavailable → 503: never a made-up "₹0"
        current = find_voice(settings.voice) or VOICES[0]
        by_type: dict[str, TypeUse] = {
            t: TypeUse(
                used=round(m.units.get(self.prices.tts(t).key, 0.0)),
                free=round(self.prices.tts(t).free_units),
            )
            for t in TYPES
        }
        return VoiceView(
            cloud=CloudStatus(tts=tts, stt=stt, reason=tts_why or stt_why),
            settings=settings,
            voices=[
                VoiceOption(
                    id=v.id,
                    label=v.label,
                    style=v.style,
                    type=v.type,
                    available=tts == "ready" and (known is None or v.id in known),
                )
                for v in VOICES
            ],
            wit_levels=[
                WitOption(id=w.id, label=w.label, description=w.description) for w in WIT_LEVELS
            ],
            allowance=Allowance(
                tts=TtsAllowance(
                    type=current.type,
                    used_chars=by_type[current.type].used,
                    free_chars=by_type[current.type].free,
                    by_type=by_type,
                ),
                stt=SttAllowance(
                    used_seconds=round(m.units.get(self.prices.stt.key, 0.0), 1),
                    free_seconds=round(self.prices.stt.free_units),
                ),
            ),
            month=VoiceMonth(
                month=m.month, voice_inr=round(m.by_brain_inr.get(METER_LABEL, 0.0), 2)
            ),
            language=self.language,
        )

    # ---- speech --------------------------------------------------------------------------------

    def _speech_input(self, req: SpeakRequest, settings: VoiceSettings) -> tuple[Voice, float, str]:
        voice = find_voice(req.voice if req.voice is not None else settings.voice)
        if voice is None:
            raise VoiceRejected("Unknown voice: choose one from the list.")
        rate = req.rate if req.rate is not None else settings.rate
        if not rate_ok(rate):
            raise VoiceRejected("Speed must be between 0.8 and 1.25.")
        if req.preview:
            return voice, rate, SAMPLE_LINE.replace("{honorific}", self.honorific)
        if not req.text:
            raise VoiceRejected("Send the text to read aloud.")
        if len(req.text) > MAX_TEXT_IN:
            raise VoiceRejected(f"At most {MAX_TEXT_IN:,} characters per request.")
        return voice, rate, req.text

    async def speak(self, uid: str, req: SpeakRequest) -> Speech:
        voice, rate, text = self._speech_input(req, await self.settings_of(uid))
        spoken = speakable(text)
        if not spoken:
            raise NothingToSay()
        engines = self._require("tts")
        price = self.prices.tts(voice.type)
        chars = len(spoken)
        await self.billing.ensure_units_allowed(
            uid, key=price.key, units=chars, free_units=price.free_units
        )
        try:
            audio = await engines.tts.synthesize(
                spoken, voice=voice.id, language=voice.language, rate=rate
            )
        except VoiceUnavailable as exc:
            self._note("tts", exc)
            raise
        charge = await self.billing.record_units(
            uid,
            key=price.key,
            units=chars,
            free_units=price.free_units,
            usd_per_unit=price.usd_per_unit,
            label=METER_LABEL,
        )
        log.info(
            "voice: spoke",
            extra={"chars": chars, "voice": voice.id, "cost_inr": round(charge.inr, 4)},
        )
        return Speech(audio=audio, chars=chars, cost_inr=charge.inr, voice=voice.id)

    async def transcribe(self, uid: str, blob: bytes) -> TranscriptView:
        audio = parse_wav(blob)
        engines = self._require("stt")
        price = self.prices.stt
        estimate = float(math.ceil(audio.seconds))
        await self.billing.ensure_units_allowed(
            uid, key=price.key, units=estimate, free_units=price.free_units
        )
        try:
            t = await engines.stt.recognize(
                audio.pcm,
                sample_rate=audio.sample_rate,
                language=self.language,
                phrases=self.phrases,
            )
        except VoiceUnavailable as exc:
            self._note("stt", exc)
            raise
        billed = t.billed_seconds if t.billed_seconds is not None else estimate
        charge = await self.billing.record_units(
            uid,
            key=price.key,
            units=billed,
            free_units=price.free_units,
            usd_per_unit=price.usd_per_unit,
            label=METER_LABEL,
        )
        text = t.text.strip()
        log.info(
            "voice: transcribed",
            extra={
                "seconds": round(audio.seconds, 2),
                "billed_s": billed,
                "chars": len(text),
                "cost_inr": round(charge.inr, 4),
            },
        )
        return TranscriptView(
            text=text,
            confidence=t.confidence,
            seconds=round(audio.seconds, 2),
            cost_inr=round(charge.inr, 4),
            language=self.language,
            no_speech=not text,
        )

    async def aclose(self) -> None:
        if self.engines is not None and self.engines.http is not None:
            await self.engines.http.aclose()


def google_engines() -> VoiceEngines:
    """Google Cloud TTS + STT as the runtime service account (ADC). Imported lazily: nothing
    touches google-auth until cloud voice is switched on."""
    from jarvis.voice.adc import AdcTokens
    from jarvis.voice.google_cloud import TIMEOUT_S, GoogleSTT, GoogleTTS

    http = httpx.AsyncClient(timeout=TIMEOUT_S, follow_redirects=False)
    tokens = AdcTokens()
    return VoiceEngines(
        tts=GoogleTTS(http, tokens), stt=GoogleSTT(http, tokens), tokens=tokens, http=http
    )


def build_voice_service(
    s: Settings, docs: Docs, billing: Billing, *, engines: VoiceEngines | None = None
) -> VoiceService:
    """Settings and the wit level always; the cloud engines only when JARVIS_VOICE_CLOUD is on.
    Nothing here makes a network call: credentials are looked up on first use."""
    if engines is None and s.voice_cloud:
        engines = google_engines()
    return VoiceService(
        store=VoiceSettingsStore(docs, prefix=s.firestore_prefix),
        billing=billing,
        prices=PriceList.from_settings(s),
        engines=engines if s.voice_cloud else None,
        language=s.voice_language,
        honorific=s.user_honorific,
    )


__all__ = [
    "MAX_TEXT_IN",
    "Speech",
    "SpeakRequest",
    "TranscriptView",
    "VoiceEngines",
    "VoiceService",
    "VoiceView",
    "build_voice_service",
    "google_engines",
]
