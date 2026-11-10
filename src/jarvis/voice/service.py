# src/jarvis/voice/service.py
"""Voice, tied together (slice 9; Layers 2, 4 and 8): settings, availability, the spending gate,
the engines and the meter.

    speak       text (1–1,200) → speakable() (≤ 600) → [gate (only if priced) → TTS → meter]
    transcribe  WAV → strict parse → [gate (only if priced) → STT → meter (Google's billed time)]
    view        settings, cloud status, voices (validated against Google's list), wit levels,
                the deployment's allowance use this Pacific month and the owner's voice rupees
    wit_for     the Brain's persona variant (never raises; any failure → "film")

[…] runs under a per-owner lock per kind (speak, transcribe), so concurrent calls at the
allowance edge or the limit are gated one after another (one instance runs in production).
STT is gated on ceil(duration) and billed on Google's `totalBilledTime` when it is returned.
A call that fails after the request may have reached Google (sent, then a timeout or a broken
connection; or cancelled while in flight) is metered on its estimate (characters sent / ceil of
the audio seconds); a clean error answer (4xx / 5xx) is not.

Settings reads (speak, transcribe's hints, the view, the persona) are bounded to 1 s; a failure
gives the defaults and is remembered 30 s (no read meanwhile) until a PUT clears it.

Availability (D10): Google answering 403 or no credentials marks that API unavailable for 10
minutes (no calls meanwhile); timeouts and 5xx are reported but not remembered. Privacy (D13): no
audio is stored; text and transcripts are never logged (lengths only).
"""

from __future__ import annotations

import asyncio
import math
import time
import weakref
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Literal, TypeVar

import httpx
from pydantic import BaseModel, ConfigDict, Field

from jarvis.billing import Billing
from jarvis.billing.meter import UnitCharge
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
    Price,
    PriceList,
    Voice,
    find_voice,
)
from jarvis.voice.commands import BASE_PHRASES
from jarvis.voice.ports import (
    NothingToSay,
    Reason,
    STTProvider,
    TokenSource,
    Transcript,
    TTSProvider,
    VoiceError,
    VoiceRejected,
    VoiceUnavailable,
)
from jarvis.voice.settings import (
    CACHE_S,
    PHRASE_CHARS,
    PHRASE_ITEMS,
    VoiceSettings,
    VoiceSettingsPatch,
    VoiceSettingsStore,
    rate_ok,
)
from jarvis.voice.speakable import speakable
from jarvis.voice.wav import Audio, parse_wav

log = get_logger(__name__)

MAX_TEXT_IN = 1_200
DOWN_TTL_S = 600.0
# Inside the Brain's own bound (1.5 s), so a hung read is remembered as a failure.
SETTINGS_READ_S = 1.0
VOICE_LIST_WAIT_S = 2.0  # GET /v1/voice waits this long for Google's list, then lists all
STICKY: frozenset[str] = frozenset({"api_disabled", "not_configured"})
Api = Literal["tts", "stt"]
State = Literal["ready", "off", "unavailable"]
T = TypeVar("T")


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
    """The free allowance JARVIS may use (90 % of Google's by default; 0 if the billing account
    is shared), counted once for the whole deployment on Pacific-time months like Google's."""

    tts: TtsAllowance
    stt: SttAllowance
    month: str  # "2026-11", the Pacific-time month the counters are for
    resets_at: str  # ISO 8601: the next 1st, 00:00 America/Los_Angeles
    scope: Literal["deployment"] = "deployment"


class VoiceMonth(BaseModel):
    month: str
    voice_inr: float


class PhraseLimits(BaseModel):
    items: int = PHRASE_ITEMS
    chars: int = PHRASE_CHARS


class VoiceView(BaseModel):
    cloud: CloudStatus
    settings: VoiceSettings
    phrase_limits: PhraseLimits = PhraseLimits()
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
        self._settings_fail_until: dict[str, float] = {}
        self._voice_list: asyncio.Future[frozenset[str] | None] | None = None
        # gate → engine → meter, one at a time per owner and kind; locks vanish when unused
        self._locks: weakref.WeakValueDictionary[tuple[str, Api], asyncio.Lock] = (
            weakref.WeakValueDictionary()
        )
        self.base_phrases = (*BASE_PHRASES, honorific)

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
        """The owner's settings, read within SETTINGS_READ_S. Never raises: a failed or slow
        read gives the defaults (logged) and is not retried for 30 s, unless a PUT succeeds."""
        if self._clock() < self._settings_fail_until.get(uid, 0.0):
            return VoiceSettings()
        try:
            return await asyncio.wait_for(self.store.get(uid), SETTINGS_READ_S)
        except Exception as exc:  # noqa: BLE001 — speaking with defaults beats not speaking
            self._settings_fail_until[uid] = self._clock() + CACHE_S
            log.warning(
                "voice settings unreadable; using the defaults",
                extra={"reason": type(exc).__name__},
            )
            return VoiceSettings()

    def hints_for(self, owner_phrases: tuple[str, ...]) -> tuple[str, ...]:
        """The speech hints for one request: the base list, the honorific, then the owner's words,
        one spelling each (case-insensitive; the first wins). No `boost` (D16)."""
        seen: dict[str, str] = {}
        for w in (*self.base_phrases, *owner_phrases):
            if w.strip():
                seen.setdefault(w.casefold(), w)
        return tuple(seen.values())

    async def update_settings(self, uid: str, patch: VoiceSettingsPatch) -> VoiceSettings:
        new = await self.store.update(uid, patch)
        self._settings_fail_until.pop(uid, None)  # the new values apply at once
        return new

    async def wit_for(self, uid: str) -> str:
        """The persona's wit level. Never raises (any failure → the default)."""
        wit = (await self.settings_of(uid)).wit
        return wit if wit else DEFAULT_WIT

    # ---- the owner's view --------------------------------------------------------------------

    async def _fetch_voices(self, engines: VoiceEngines) -> frozenset[str] | None:
        try:
            return await engines.tts.voices(VOICE_LANGUAGE)
        except VoiceUnavailable as exc:
            self._note("tts", exc)
        except VoiceError as exc:
            log.warning("voice list unreadable", extra={"reason": type(exc).__name__})
        return None

    async def _known_voices(self) -> frozenset[str] | None:
        """Google's voice ids (cached 24 h by the adapter); None when they can't be read or
        don't arrive within VOICE_LIST_WAIT_S. One fetch at a time: it keeps going in the
        background when the view stops waiting, so the next view finds the list."""
        engines = self.engines
        if engines is None or self.state("tts")[0] != "ready":
            return None
        task = self._voice_list
        if task is None or task.done():
            task = asyncio.ensure_future(self._fetch_voices(engines))
            self._voice_list = task
        try:
            return await asyncio.wait_for(asyncio.shield(task), VOICE_LIST_WAIT_S)
        except TimeoutError:
            log.info("voice list still loading; availability unknown for now")
            return None

    async def view(self, uid: str) -> VoiceView:
        settings = await self.settings_of(uid)
        known = await self._known_voices()
        tts, tts_why = self.state("tts")
        stt, stt_why = self.state("stt")
        # BudgetUnavailable → 503: never a made-up "₹0" or "0 used"
        m = await self.billing.month(uid)
        stt_key = self.prices.stt.key
        a = await self.billing.allowance([*(self.prices.tts(t).key for t in TYPES), stt_key])
        current = find_voice(settings.voice) or VOICES[0]
        by_type: dict[str, TypeUse] = {
            t: TypeUse(
                used=round(a.used(self.prices.tts(t).key)),
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
                    used_seconds=round(a.used(stt_key), 1),
                    free_seconds=round(self.prices.stt.free_units),
                ),
                month=a.month,
                resets_at=self.billing.allowance_resets_at().isoformat(),
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

    def _lock(self, uid: str, api: Api) -> asyncio.Lock:
        lock = self._locks.get((uid, api))
        if lock is None:
            lock = asyncio.Lock()
            self._locks[(uid, api)] = lock
        return lock

    async def _meter(self, uid: str, price: Price, units: float) -> UnitCharge:
        return await self.billing.record_units(
            uid,
            key=price.key,
            units=units,
            free_units=price.free_units,
            usd_per_unit=price.usd_per_unit,
            label=METER_LABEL,
        )

    async def _engine(
        self, api: Api, uid: str, price: Price, estimate: float, call: Callable[[], Awaitable[T]]
    ) -> T:
        """One engine call. If it fails after the request may have reached Google, its estimate
        is metered (Google may bill it); a clean error answer is not."""
        try:
            return await call()
        except VoiceUnavailable as exc:
            self._note(api, exc)
            if exc.maybe_billed:
                await self._meter(uid, price, estimate)
            raise
        except asyncio.CancelledError:  # the owner went away mid-call: Google may have it
            await self._meter(uid, price, estimate)  # shielded: completes despite the cancel
            raise

    async def speak(self, uid: str, req: SpeakRequest) -> Speech:
        voice, rate, text = self._speech_input(req, await self.settings_of(uid))
        spoken = speakable(text)
        if not spoken:
            raise NothingToSay()
        engines = self._require("tts")
        price = self.prices.tts(voice.type)
        chars = len(spoken)
        async with self._lock(uid, "tts"):
            await self.billing.ensure_units_allowed(
                uid, key=price.key, units=chars, free_units=price.free_units
            )
            audio = await self._engine(
                "tts",
                uid,
                price,
                chars,
                lambda: engines.tts.synthesize(
                    spoken, voice=voice.id, language=voice.language, rate=rate
                ),
            )
            charge = await self._meter(uid, price, chars)
        log.info(
            "voice: spoke",
            extra={"chars": chars, "voice": voice.id, "cost_inr": round(charge.inr, 4)},
        )
        return Speech(audio=audio, chars=chars, cost_inr=charge.inr, voice=voice.id)

    async def _recognise(
        self,
        engines: VoiceEngines,
        uid: str,
        price: Price,
        estimate: float,
        audio: Audio,
        hints: tuple[str, ...],
        has_owner_words: bool,
    ) -> Transcript:
        """One recognition. If Google refuses the request while it carries the owner's words, try
        once more with the base hints alone, so one bad word cannot stop every transcription."""

        def call(phrases: tuple[str, ...]) -> Callable[[], Awaitable[Transcript]]:
            return lambda: engines.stt.recognize(
                audio.pcm, sample_rate=audio.sample_rate, language=self.language, phrases=phrases
            )

        try:
            return await self._engine("stt", uid, price, estimate, call(hints))
        except VoiceRejected:
            if not has_owner_words:
                raise
        log.warning("voice: owner words were refused; retrying with the base hints only")
        return await self._engine("stt", uid, price, estimate, call(self.hints_for(())))

    async def transcribe(
        self, uid: str, blob: bytes, *, owner_phrases: bool = True
    ) -> TranscriptView:
        """`owner_phrases=False`: the base hints only (R6: a build book guest's question must not
        be biased toward the owner's own words)."""
        audio = parse_wav(blob)
        engines = self._require("stt")
        owner = (await self.settings_of(uid)).phrases if owner_phrases else ()  # never raises
        hints = self.hints_for(owner)
        price = self.prices.stt
        estimate = float(math.ceil(audio.seconds))  # gated on this …
        async with self._lock(uid, "stt"):
            await self.billing.ensure_units_allowed(
                uid, key=price.key, units=estimate, free_units=price.free_units
            )
            t = await self._recognise(engines, uid, price, estimate, audio, hints, bool(owner))
            # … billed on what Google says it billed (totalBilledTime), when it says
            billed = t.billed_seconds if t.billed_seconds is not None else estimate
            charge = await self._meter(uid, price, billed)
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
        """App shutdown: the voice-list fetch, the HTTP client and the credentials transport."""
        task = self._voice_list
        if task is not None and not task.done():
            task.cancel()
        if self.engines is None:
            return
        if self.engines.http is not None:
            await self.engines.http.aclose()
        if self.engines.tokens is not None:
            self.engines.tokens.close()


def google_engines() -> VoiceEngines:
    """Google Cloud TTS + STT as the runtime service account (ADC). Imported lazily: nothing
    touches google-auth until cloud voice is switched on."""
    from jarvis.voice.adc import AdcTokens
    from jarvis.voice.google_cloud import HTTP_TIMEOUT, GoogleSTT, GoogleTTS

    http = httpx.AsyncClient(timeout=HTTP_TIMEOUT, follow_redirects=False)
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
    "PhraseLimits",
    "SpeakRequest",
    "TranscriptView",
    "VoiceEngines",
    "VoiceService",
    "VoiceView",
    "build_voice_service",
    "google_engines",
]
