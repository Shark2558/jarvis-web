# src/jarvis/localspeech/protocol.py
"""The laptop speech kit's API (R5.2 row 383; docs/plans/r5-2-voice.md 3.1; I0 seams:
docs/plans/r5-2-integration/I0-SEAMS.md). Both sides use this module: the kit's server on the
laptop (V1) and its clients (V2: the cloud through the owner's Tailscale https name, the call desk
on 127.0.0.1). Kit-safe: the standard library, Pydantic and R18's pure models only.

Every path is relative to the kit's base, which ends in `/v1`: the cloud's base is exactly what
`jarvis.offline.config.check_url` gives (`https://<machine>.<tailnet>.ts.net[:port]/v1`, the
offline brain's SSRF-safe rule, with `PinnedTransport`), the desk's is `LOOPBACK_BASE`.

    GET  /health            KitHealth (engines, device, free memory)
    POST /stt               SttRequest -> SttResult
    POST /tts               TtsRequest -> TtsResult
    POST /session/clip      ClipIn -> ClipStored           (stored on the laptop, encrypted)
    POST /session/score     ScoreIn -> JobView             (the laptop engines hear the clips)
    POST /session/results   ResultsIn -> SessionHeard
    POST /session/delete    DeleteIn -> Deleted
    POST /wakeword/train    WakeTrainIn -> JobView
    POST /wakeword/status   {} -> WakeStatus
    POST /wakeword/model    WakeModelIn -> WakeModel
    GET  /jobs/{job_id}     JobView

JSON only; audio travels as base64 of 16 kHz mono signed 16-bit little-endian PCM (R18's format,
`jarvis.calls.protocol`), or MP3 for the console's voice. The key is `Authorization: Bearer <key>`,
checked by the gate (fail closed under `KEY_MIN_CHARS`). A refusal is `KitErrorBody` with an HTTP
status; its words never quote the request. Requests are strict (unknown fields refused); replies
ignore fields a newer kit adds, and `PROTOCOL` says whether the two sides match at all.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import re
import secrets
from enum import StrEnum
from typing import Annotated, Final, Literal, Protocol, Self, TypeVar

from pydantic import (
    AfterValidator,
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)

from jarvis.calls.models import ENGLISH, LANGUAGES, is_language
from jarvis.calls.protocol import SAMPLE_BYTES, SAMPLE_RATE

PROTOCOL: Final = 1
KIT_VERSION: Final = r"^[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,4}$"  # the kit's own track, never JARVIS's

# ---- where -------------------------------------------------------------------------------------
API_PREFIX: Final = "/v1"
HEALTH, STT, TTS, JOBS = "/health", "/stt", "/tts", "/jobs/{job_id}"
CLIP, SCORE = "/session/clip", "/session/score"
RESULTS, DELETE = "/session/results", "/session/delete"
WAKE_TRAIN, WAKE_STATUS, WAKE_MODEL = "/wakeword/train", "/wakeword/status", "/wakeword/model"
ROUTES: Final[tuple[tuple[str, str], ...]] = (
    ("GET", HEALTH),
    ("POST", STT),
    ("POST", TTS),
    ("POST", CLIP),
    ("POST", SCORE),
    ("POST", RESULTS),
    ("POST", DELETE),
    ("POST", WAKE_TRAIN),
    ("POST", WAKE_STATUS),
    ("POST", WAKE_MODEL),
    ("GET", JOBS),
)  # exactly what the gate passes (with the key); everything else 404
GATE_PORT: Final = 11436  # Caddy, on 127.0.0.1 only (the offline brain's gate is 11435)
SERVER_PORT: Final = 11437  # the kit's own server, on 127.0.0.1 only, never published
FUNNEL_PORT: Final = 8443  # Tailscale Funnel's https port for the kit (the brain keeps 443)
LOOPBACK_BASE: Final = f"http://127.0.0.1:{GATE_PORT}{API_PREFIX}"  # the call desk, same laptop
KEY_MIN_CHARS: Final = 32
BODY_MAX: Final = 3_000_000  # one request (60 s of PCM is 2.56 MB as base64)
REPLY_MAX: Final = 4_000_000  # one reply, read by the client (an owned wake-word model fits)

JOB_ID: Final = r"^job_[0-9a-f]{12}$"
JOB_ID_RE: Final = re.compile(JOB_ID)
SESSION_ID: Final = r"^vs_[0-9a-f]{12}$"
SESSION_ID_RE: Final = re.compile(SESSION_ID)
PROMPT_ID: Final = r"^[a-z][a-z0-9_]{0,31}$"
VOICE_ID: Final = r"^[a-z0-9_-]{1,40}$"
SHA256: Final = r"^[0-9a-f]{64}$"


def job_path(job_id: str) -> str:
    if not JOB_ID_RE.fullmatch(job_id):
        raise ValueError("not a job id")
    return JOBS.format(job_id=job_id)


def bearer(key: str) -> dict[str, str]:
    """The gate's header. A key under `KEY_MIN_CHARS` is never sent (the gate refuses it too)."""
    if len(key) < KEY_MIN_CHARS:
        raise ValueError("the kit's key is too short")
    return {"Authorization": f"Bearer {key}"}


def new_session_id() -> str:
    return f"vs_{secrets.token_hex(6)}"


def new_job_id() -> str:
    return f"job_{secrets.token_hex(6)}"


# ---- audio ---------------------------------------------------------------------------------------
BYTES_PER_SECOND: Final = SAMPLE_RATE * SAMPLE_BYTES
MIN_AUDIO_S: Final = 0.3  # as POST /v1/voice/transcribe
STT_MAX_S: Final = 60
CLIP_MAX_S: Final = 20  # one session prompt
TTS_MAX_CHARS: Final = 600  # what `jarvis.voice.speakable` gives at most
PHRASES_MAX: Final = 50  # the owner's words to recognise (`jarvis.voice.settings.PHRASE_ITEMS`)
PHRASE_CHARS: Final = 40
TEXT_MAX: Final = 4_000
WORDS_MAX: Final = 200  # plain words in an error, a job, a reason
MP3_RATES: Final = frozenset({16_000, 22_050, 24_000, 44_100, 48_000})


def pcm_seconds(n_bytes: int) -> float:
    return n_bytes / BYTES_PER_SECOND


def encode_pcm(pcm: bytes) -> str:
    return base64.b64encode(pcm).decode("ascii")


def _b64(text: str) -> bytes:
    try:
        return base64.b64decode(text, validate=True)
    except (binascii.Error, ValueError):
        raise ValueError("not base64") from None


def decode_pcm(text: str, *, max_s: float) -> bytes:
    """PCM16 16 kHz mono from base64; ValueError (never quoting it) when it isn't, or is shorter
    than `MIN_AUDIO_S` or longer than `max_s`."""
    if len(text) > (max_s * BYTES_PER_SECOND) * 4 // 3 + 4:
        raise ValueError("the audio is too long")
    raw = _b64(text)
    if len(raw) % SAMPLE_BYTES:
        raise ValueError("the audio is not 16-bit samples")
    if not MIN_AUDIO_S <= pcm_seconds(len(raw)) <= max_s:
        raise ValueError(f"the audio must last {MIN_AUDIO_S} to {max_s} seconds")
    return raw


# ---- engines -------------------------------------------------------------------------------------
class Kind(StrEnum):
    STT = "stt"
    TTS = "tts"


class Device(StrEnum):
    CUDA = "cuda"
    CPU = "cpu"


class AudioFormat(StrEnum):
    PCM16 = "pcm16"  # 16 kHz mono (calls, scoring)
    MP3 = "mp3"  # the console's voice (POST /v1/voice/speak answers audio/mpeg)


class EngineSlot(StrEnum):
    """One model each (plan D2, D3), loaded on demand so a 4 GB graphics card is enough."""

    WHISPER_SMALL = "whisper-small"  # faster-whisper small int8 (MIT; Whisper weights MIT)
    WHISPER_MEDIUM = "whisper-medium"  # faster-whisper medium int8, if the session shows better
    KOKORO = "kokoro"  # Kokoro-82M (Apache-2.0), a British male voice
    PIPER = "piper"  # Piper (MIT; each voice's licence checked): the light fallback
    INDIC_CONFORMER = "indic-conformer"  # AI4Bharat IndicConformer 600M int8 ONNX (MIT)
    INDIC_PARLER = "indic-parler"  # AI4Bharat Indic Parler-TTS (Apache-2.0)


SLOT_KIND: Final[dict[EngineSlot, Kind]] = {
    EngineSlot.WHISPER_SMALL: Kind.STT,
    EngineSlot.WHISPER_MEDIUM: Kind.STT,
    EngineSlot.KOKORO: Kind.TTS,
    EngineSlot.PIPER: Kind.TTS,
    EngineSlot.INDIC_CONFORMER: Kind.STT,
    EngineSlot.INDIC_PARLER: Kind.TTS,
}
_DEFAULTS: Final[dict[tuple[Kind, bool], tuple[EngineSlot, ...]]] = {
    (Kind.STT, True): (EngineSlot.WHISPER_SMALL,),
    (Kind.TTS, True): (EngineSlot.KOKORO, EngineSlot.PIPER),
    (Kind.STT, False): (EngineSlot.INDIC_CONFORMER,),
    (Kind.TTS, False): (EngineSlot.INDIC_PARLER, EngineSlot.PIPER),
}
DEFAULT_ENGLISH_VOICE: Final = "bm_george"  # Kokoro's British male voice (V1 may pick another)
# Plan risk 2: a model file or voice is shipped only under one of these; anything unclear is left
# out. Today's `hey_jarvis_v0.1` (CC BY-NC-SA) is the console's, never the kit's.
PERMISSIVE_LICENCES: Final = frozenset(
    {"MIT", "Apache-2.0", "BSD-2-Clause", "BSD-3-Clause", "ISC", "CC0-1.0", "CC-BY-4.0"}
)
OWNER_LICENCE: Final = "LicenseRef-Owner"  # a model trained by and owned by the owner (row 83)


def default_slots(kind: Kind, lang: str) -> tuple[EngineSlot, ...]:
    """The engines tried for `kind` in `lang`, in order (English: D2; Indian languages: D3)."""
    return _DEFAULTS[(kind, lang == ENGLISH)]


def _language(code: str) -> str:
    if not is_language(code):
        raise ValueError("not one of the languages JARVIS knows (BCP-47, e.g. en-IN)")
    return code


def _shipped(licence: str) -> str:
    if licence not in PERMISSIVE_LICENCES | {OWNER_LICENCE}:
        raise ValueError("a file whose licence is not permissive is left out")
    return licence


def _permissive(licence: str) -> str:
    if licence not in PERMISSIVE_LICENCES:
        raise ValueError("an engine whose licence is not permissive is left out")
    return licence


Lang = Annotated[str, AfterValidator(_language)]
EngineLicence = Annotated[str, AfterValidator(_permissive)]
FileLicence = Annotated[str, AfterValidator(_shipped)]
Phrase = Annotated[str, Field(min_length=1, max_length=PHRASE_CHARS)]  # one word to recognise


def _slot_of(slot: EngineSlot | None, kind: Kind) -> EngineSlot | None:
    if slot is not None and SLOT_KIND[slot] is not kind:
        raise ValueError(f"that engine is not a {kind.value} engine")
    return slot


# ---- models --------------------------------------------------------------------------------------
class _Request(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class _Reply(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")


class EngineHealth(_Reply):
    slot: EngineSlot
    kind: Kind
    languages: tuple[Lang, ...] = Field(max_length=len(LANGUAGES))
    model: str = Field(min_length=1, max_length=80)  # e.g. "small-int8", "bm_george"
    licence: EngineLicence
    ready: bool
    loaded: bool = False  # in memory now (else loaded on first use)
    device: Device
    reason: str = Field(default="", max_length=WORDS_MAX)  # plain words when not ready

    @model_validator(mode="after")
    def _one_kind(self) -> Self:
        if SLOT_KIND[self.slot] is not self.kind:
            raise ValueError("a slot has one kind")
        return self


class KitHealth(_Reply):
    protocol: int = Field(ge=1)
    kit_version: str = Field(pattern=KIT_VERSION)
    device: Device
    gpu_free_mb: int | None = Field(default=None, ge=0)
    ram_free_mb: int = Field(ge=0)
    engines: tuple[EngineHealth, ...] = Field(max_length=16)
    jobs_running: int = Field(default=0, ge=0)
    slow: bool = False  # the kit expects a reply to be slow now: routing falls back (risk 1)

    @property
    def compatible(self) -> bool:
        return self.protocol == PROTOCOL

    def engine_for(self, kind: Kind, lang: str) -> EngineSlot | None:
        """The first ready engine of `kind` for `lang`, in `default_slots` order."""
        ready = {e.slot for e in self.engines if e.ready and lang in e.languages}
        return next((s for s in default_slots(kind, lang) if s in ready), None)

    def languages(self, kind: Kind) -> tuple[str, ...]:
        """Every language some ready engine of `kind` serves (for R18's `hello`)."""
        found = {c for e in self.engines if e.ready and e.kind is kind for c in e.languages}
        return tuple(sorted(found))


class SttRequest(_Request):
    lang: Lang
    audio: str  # base64 PCM16 16 kHz mono, MIN_AUDIO_S..STT_MAX_S
    slot: EngineSlot | None = None  # None: the kit's first ready engine for `lang`
    phrases: tuple[Phrase, ...] = Field(default=(), max_length=PHRASES_MAX)  # words to recognise

    @field_validator("audio")
    @classmethod
    def _audio(cls, v: str) -> str:
        decode_pcm(v, max_s=STT_MAX_S)
        return v

    @field_validator("slot")
    @classmethod
    def _stt(cls, v: EngineSlot | None) -> EngineSlot | None:
        return _slot_of(v, Kind.STT)

    @classmethod
    def of_pcm(
        cls,
        pcm: bytes,
        *,
        lang: str,
        slot: EngineSlot | None = None,
        phrases: tuple[str, ...] = (),
    ) -> SttRequest:
        return cls(lang=lang, audio=encode_pcm(pcm), slot=slot, phrases=phrases)

    def pcm(self) -> bytes:
        return decode_pcm(self.audio, max_s=STT_MAX_S)


class SttResult(_Reply):
    """What was heard. `lang`, `text`, `confidence`, `seconds` are R18's `Heard` fields 1:1."""

    lang: Lang
    text: str = Field(max_length=TEXT_MAX)
    confidence: float = Field(ge=0, le=1)
    seconds: float = Field(ge=0)  # the audio's length
    slot: EngineSlot
    alternatives: tuple[str, ...] = Field(default=(), max_length=2)  # as voice's Transcript
    elapsed_ms: int = Field(default=0, ge=0)


class TtsRequest(_Request):
    lang: Lang
    text: str = Field(min_length=1, max_length=TTS_MAX_CHARS)  # already speakable
    slot: EngineSlot | None = None
    voice: str | None = Field(default=None, pattern=VOICE_ID)  # None: the slot's default voice
    rate: float = Field(default=1.0, ge=0.5, le=2.0)
    format: AudioFormat = AudioFormat.PCM16

    @field_validator("slot")
    @classmethod
    def _tts(cls, v: EngineSlot | None) -> EngineSlot | None:
        return _slot_of(v, Kind.TTS)


class TtsResult(_Reply):
    format: AudioFormat
    audio: str  # base64: PCM16 16 kHz mono, or MP3
    sample_rate: int
    seconds: float = Field(ge=0)
    slot: EngineSlot
    voice: str = Field(pattern=VOICE_ID)
    first_audio_ms: int = Field(default=0, ge=0)  # the plan's "first audio" eval (5)
    elapsed_ms: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def _rate(self) -> Self:
        if self.format is AudioFormat.PCM16 and self.sample_rate != SAMPLE_RATE:
            raise ValueError("PCM audio is 16 kHz")
        if self.format is AudioFormat.MP3 and self.sample_rate not in MP3_RATES:
            raise ValueError("not an MP3 sample rate")
        return self

    def audio_bytes(self) -> bytes:
        return _b64(self.audio)


# ---- the voice session (row 81) ------------------------------------------------------------------
class PromptKind(StrEnum):
    COMMAND = "command"  # commands JARVIS knows
    WORDS = "words"  # the owner's words list
    PLACES = "places"  # places and names
    NUMBERS = "numbers"  # numbers and times
    WAKE = "wake"  # "Hey Jarvis", said 30 ways (row 83's clips)


class ClipIn(_Request):
    session_id: str = Field(pattern=SESSION_ID)
    prompt_id: str = Field(pattern=PROMPT_ID)
    audio: str  # base64 PCM16 16 kHz mono, MIN_AUDIO_S..CLIP_MAX_S
    kind: PromptKind
    held_out: bool = False  # scored, never trained on

    @field_validator("audio")
    @classmethod
    def _audio(cls, v: str) -> str:
        decode_pcm(v, max_s=CLIP_MAX_S)
        return v

    def pcm(self) -> bytes:
        return decode_pcm(self.audio, max_s=CLIP_MAX_S)


class ClipStored(_Reply):
    session_id: str = Field(pattern=SESSION_ID)
    prompt_id: str = Field(pattern=PROMPT_ID)
    seconds: float = Field(ge=0)
    clips: int = Field(ge=0)  # clips this session now holds on the laptop


class ScoreIn(_Request):
    """The laptop engines hear every held-out clip of the session (the cloud scores them)."""

    session_id: str = Field(pattern=SESSION_ID)
    slots: tuple[EngineSlot, ...] = Field(min_length=1, max_length=4)
    phrases: tuple[Phrase, ...] = Field(default=(), max_length=PHRASES_MAX)

    @field_validator("slots")
    @classmethod
    def _stt_only(cls, v: tuple[EngineSlot, ...]) -> tuple[EngineSlot, ...]:
        for slot in v:
            _slot_of(slot, Kind.STT)
        return v


class ResultsIn(_Request):
    session_id: str = Field(pattern=SESSION_ID)


class HeardRow(_Reply):
    prompt_id: str = Field(pattern=PROMPT_ID)
    slot: EngineSlot
    text: str = Field(max_length=TEXT_MAX)
    elapsed_ms: int = Field(default=0, ge=0)


class SessionHeard(_Reply):
    session_id: str = Field(pattern=SESSION_ID)
    rows: tuple[HeardRow, ...] = Field(default=(), max_length=2_000)


class DeleteIn(_Request):
    session_id: str | None = Field(default=None, pattern=SESSION_ID)  # None: every recording
    wakeword: bool = False  # also the wake-word files trained from them


class Deleted(_Reply):
    clips: int = Field(ge=0)
    wakeword_files: int = Field(default=0, ge=0)


# ---- jobs ----------------------------------------------------------------------------------------
class JobKind(StrEnum):
    SCORE = "score"
    VERIFIER = "wakeword_verifier"  # row 83 stage 1
    OWNED = "wakeword_owned"  # row 83 stage 2 (2-3 hours, unattended)


class JobState(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"
    CANCELLED = "cancelled"


class JobView(_Reply):
    job_id: str = Field(pattern=JOB_ID)
    kind: JobKind
    state: JobState
    progress: float = Field(default=0.0, ge=0, le=1)
    words: str = Field(default="", max_length=WORDS_MAX)
    started_at: AwareDatetime | None = None
    finished_at: AwareDatetime | None = None

    @property
    def finished(self) -> bool:
        return self.state in (JobState.DONE, JobState.FAILED, JobState.CANCELLED)


# ---- the wake word (row 83) ----------------------------------------------------------------------
class WakeArtifact(StrEnum):
    VERIFIER = "verifier"  # stage 1: plain weights the console applies after today's detector
    OWNED = "owned"  # stage 2: an ONNX model in the console's format, its MANIFEST, his licence


class WakeTrainIn(_Request):
    artifact: WakeArtifact
    session_id: str = Field(pattern=SESSION_ID)


class ArtifactInfo(_Reply):
    artifact: WakeArtifact
    sha256: str = Field(pattern=SHA256)
    size: int = Field(ge=0)
    trained_at: AwareDatetime
    licence: FileLicence
    evals: dict[str, float] = Field(default_factory=dict, max_length=12)  # e.g. false wakes/hour
    beats_current: bool | None = None  # stage 2: swapped in only when True (risk 3)


class WakeStatus(_Reply):
    verifier: ArtifactInfo | None = None
    owned: ArtifactInfo | None = None
    jobs: tuple[JobView, ...] = Field(default=(), max_length=8)


class WakeModelIn(_Request):
    artifact: WakeArtifact


class WakeModel(_Reply):
    artifact: WakeArtifact
    data: str  # base64
    format: Literal["json", "onnx"]
    sha256: str = Field(pattern=SHA256)
    licence: FileLicence
    manifest: str = Field(default="", max_length=20_000)

    @model_validator(mode="after")
    def _hash(self) -> Self:
        if hashlib.sha256(self.data_bytes()).hexdigest() != self.sha256:
            raise ValueError("the file does not match its hash")
        return self

    def data_bytes(self) -> bytes:
        return _b64(self.data)


# ---- errors --------------------------------------------------------------------------------------
KitErrorCode = Literal[
    "unauthorized",
    "not_found",
    "bad_request",
    "bad_audio",
    "too_large",
    "unsupported_language",
    "engine_not_ready",
    "busy",
    "job_failed",
    "internal",
]
UnavailableReason = Literal[
    "not_configured", "offline", "timeout", "busy", "slow", "unauthorized", "protocol", "error"
]
UNAVAILABLE_REASONS: Final[tuple[UnavailableReason, ...]] = (
    "not_configured",
    "offline",
    "timeout",
    "busy",
    "slow",
    "unauthorized",
    "protocol",
    "error",
)
_UNAVAILABLE: Final[dict[str, str]] = {
    "not_configured": "The laptop speech kit is not set up on this server.",
    "offline": "The laptop speech kit is not answering (is the laptop on and Tailscale up?).",
    "timeout": "The laptop speech kit took too long to answer.",
    "busy": "The laptop speech kit is busy with a long job just now.",
    "slow": "The laptop speech kit would be slow just now.",
    "unauthorized": "The laptop speech kit refused JARVIS's key.",
    "protocol": "The laptop speech kit answered in a way JARVIS doesn't understand (update it).",
    "error": "The laptop speech kit had a problem.",
}


class KitErrorBody(_Reply):
    error: KitErrorCode
    detail: str = Field(default="", max_length=WORDS_MAX)


class KitError(RuntimeError):
    """Base for every kit failure; words are for the owner and never quote audio, text or a key."""


class KitUnavailable(KitError):
    """The kit can't serve now: the caller falls back (console: Google, then the browser, as
    today; calls: R18's next option)."""

    def __init__(self, reason: UnavailableReason) -> None:
        self.reason: UnavailableReason = reason
        super().__init__(_UNAVAILABLE[reason])


class KitRefused(KitError):
    """The kit refused this request (bad audio, a language it has no engine for, ...)."""

    def __init__(self, code: KitErrorCode, words: str) -> None:
        self.code: KitErrorCode = code
        self.words = words[:WORDS_MAX]
        super().__init__(self.words)


M = TypeVar("M", bound=BaseModel)
_BAD_REQUEST = "That request is not one the laptop speech kit understands."


def parse_request(model: type[M], raw: bytes | str) -> M:
    """The kit's server reading a body: KitRefused("bad_request") in fixed words, never quoting."""
    if len(raw) > BODY_MAX:
        raise KitRefused("too_large", f"Requests are limited to {BODY_MAX:,} bytes.")
    try:
        return model.model_validate_json(raw)
    except ValidationError:
        raise KitRefused("bad_request", _BAD_REQUEST) from None


def parse_reply(model: type[M], raw: bytes | str) -> M:
    """A client reading the kit's answer: KitUnavailable("protocol") when it isn't one."""
    if len(raw) > REPLY_MAX:
        raise KitUnavailable("protocol")
    try:
        return model.model_validate_json(raw)
    except ValidationError:
        raise KitUnavailable("protocol") from None


# ---- the port ------------------------------------------------------------------------------------
class KitClient(Protocol):
    """What the cloud (V2's client over the Tailscale https name) and the call desk (V2's hook on
    127.0.0.1) call; `jarvis.localspeech.memory.MemoryKit` in tests. Every method raises
    `KitUnavailable` (fall back) or `KitRefused` (this request)."""

    async def health(self) -> KitHealth: ...

    async def stt(self, req: SttRequest) -> SttResult: ...

    async def tts(self, req: TtsRequest) -> TtsResult: ...

    async def put_clip(self, clip: ClipIn) -> ClipStored: ...

    async def score(self, req: ScoreIn) -> JobView: ...

    async def results(self, session_id: str) -> SessionHeard: ...

    async def delete(self, req: DeleteIn) -> Deleted: ...

    async def job(self, job_id: str) -> JobView: ...

    async def wakeword_train(self, req: WakeTrainIn) -> JobView: ...

    async def wakeword_status(self) -> WakeStatus: ...

    async def wakeword_model(self, artifact: WakeArtifact) -> WakeModel: ...


__all__ = [
    "API_PREFIX",
    "BODY_MAX",
    "CLIP",
    "CLIP_MAX_S",
    "DEFAULT_ENGLISH_VOICE",
    "DELETE",
    "FUNNEL_PORT",
    "GATE_PORT",
    "HEALTH",
    "JOBS",
    "KEY_MIN_CHARS",
    "LOOPBACK_BASE",
    "MIN_AUDIO_S",
    "OWNER_LICENCE",
    "PERMISSIVE_LICENCES",
    "PHRASES_MAX",
    "PROTOCOL",
    "REPLY_MAX",
    "RESULTS",
    "ROUTES",
    "SAMPLE_BYTES",
    "SAMPLE_RATE",
    "SCORE",
    "SERVER_PORT",
    "SLOT_KIND",
    "STT",
    "STT_MAX_S",
    "TTS",
    "TTS_MAX_CHARS",
    "UNAVAILABLE_REASONS",
    "WAKE_MODEL",
    "WAKE_STATUS",
    "WAKE_TRAIN",
    "ArtifactInfo",
    "AudioFormat",
    "ClipIn",
    "ClipStored",
    "DeleteIn",
    "Deleted",
    "Device",
    "EngineHealth",
    "EngineSlot",
    "HeardRow",
    "JobKind",
    "JobState",
    "JobView",
    "KitClient",
    "KitError",
    "KitErrorBody",
    "KitErrorCode",
    "KitHealth",
    "KitRefused",
    "KitUnavailable",
    "Kind",
    "PromptKind",
    "ResultsIn",
    "ScoreIn",
    "SessionHeard",
    "SttRequest",
    "SttResult",
    "TtsRequest",
    "TtsResult",
    "UnavailableReason",
    "WakeArtifact",
    "WakeModel",
    "WakeModelIn",
    "WakeStatus",
    "WakeTrainIn",
    "bearer",
    "decode_pcm",
    "default_slots",
    "encode_pcm",
    "job_path",
    "new_job_id",
    "new_session_id",
    "parse_reply",
    "parse_request",
    "pcm_seconds",
]
