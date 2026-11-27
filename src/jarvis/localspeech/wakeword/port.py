# src/jarvis/localspeech/wakeword/port.py
"""What V1's kit server calls for the wake word (R5.2 row 83): `WakewordKit`, its request and
reply models, and the two small ports it needs from V1 (`Sealer`, `Voices`). Kit-safe and light:
the standard library, Pydantic and `jarvis.localspeech.protocol` only.

V1's server, per route (`protocol.WAKE_TRAIN`, `WAKE_STATUS`, `WAKE_MODEL`, `DELETE`):

    wake = build_wakeword(root, sealer=clip_cipher, voices=tts_voices)      # once, at start
    POST /wakeword/train   job = wake.prepare(req, clips_of(req.session_id))  # KitRefused -> 4xx
                           run wake.train(job, progress) in a job of kind wake.job_kind(...)
                           (blocking and CPU-bound: a worker thread; WakewordFailed -> FAILED)
    POST /wakeword/status  wake.status() with `jobs` set to the wake-word jobs
    POST /wakeword/model   wake.model(req)                                  # KitRefused -> 404
    POST /session/delete   Deleted.wakeword_files = wake.delete() when `wakeword` is true

Clips come from V1's encrypted clip store, decrypted in memory only; nothing here logs audio,
text or what was heard.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Final, Protocol

from pydantic import BaseModel, ConfigDict, Field, field_validator

from jarvis.localspeech.protocol import (
    CLIP_MAX_S,
    MIN_AUDIO_S,
    PROMPT_ID,
    SAMPLE_BYTES,
    SESSION_ID,
    VOICE_ID,
    ArtifactInfo,
    EngineLicence,
    JobKind,
    PromptKind,
    WakeArtifact,
    WakeModel,
    WakeModelIn,
    WakeStatus,
    WakeTrainIn,
    pcm_seconds,
)

MIN_WAKE_CLIPS: Final = 10  # his "Hey Jarvis" clips to learn from (the session records 30)
HELD_MIN: Final = 3  # held-out "Hey Jarvis" clips, else every HELD_EVERY-th one is held out
HELD_EVERY: Final = 5
CLIPS_MAX: Final = 400  # one session's clips (~120 prompts, redone at most a few times)

Progress = Callable[[float, str], None]  # fraction done (0..1), plain words: never audio or text


class WakewordFailed(RuntimeError):
    """A training run failed; `words` are for the owner (the job's words)."""

    def __init__(self, words: str) -> None:
        self.words = words[:200]
        super().__init__(self.words)


class WakeClip(BaseModel):
    """One of the session's clips, as V1's clip store hands it over (decrypted, in memory)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    prompt_id: str = Field(pattern=PROMPT_ID)
    kind: PromptKind
    pcm: bytes = Field(repr=False)  # 16 kHz mono PCM16, MIN_AUDIO_S..CLIP_MAX_S
    held_out: bool = False  # scored, never trained on

    @field_validator("pcm")
    @classmethod
    def _pcm(cls, v: bytes) -> bytes:
        if len(v) % SAMPLE_BYTES or not MIN_AUDIO_S <= pcm_seconds(len(v)) <= CLIP_MAX_S:
            raise ValueError(f"a clip is 16-bit audio of {MIN_AUDIO_S} to {CLIP_MAX_S} seconds")
        return v


class WakeJob(BaseModel):
    """A checked training request: what `WakewordKit.train` runs (from `prepare`)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    artifact: WakeArtifact
    session_id: str = Field(pattern=SESSION_ID)
    clips: tuple[WakeClip, ...] = Field(min_length=1, max_length=CLIPS_MAX, repr=False)

    def wake(self, *, held_out: bool) -> tuple[WakeClip, ...]:
        return tuple(c for c in self.clips if c.kind is PromptKind.WAKE and c.held_out is held_out)

    def speech(self, *, held_out: bool) -> tuple[WakeClip, ...]:
        """His other prompts (commands, words, places, numbers): the verifier's negatives."""
        return tuple(
            c for c in self.clips if c.kind is not PromptKind.WAKE and c.held_out is held_out
        )


@dataclass(frozen=True)
class Split:
    train: tuple[WakeClip, ...]
    held: tuple[WakeClip, ...]


def split_wake(job: WakeJob) -> Split:
    """His "Hey Jarvis" clips: V3's held-out ones (never trained on), or every 5th when it marked
    too few. WakewordFailed when too few are left to learn from."""
    train, held = job.wake(held_out=False), job.wake(held_out=True)
    if len(held) < HELD_MIN:
        ordered = sorted(train, key=lambda c: c.prompt_id)
        extra = tuple(c for i, c in enumerate(ordered) if i % HELD_EVERY == HELD_EVERY - 1)
        held += extra
        train = tuple(c for c in ordered if c not in extra)
    if len(train) < MIN_WAKE_CLIPS:
        raise WakewordFailed(
            f"Training needs at least {MIN_WAKE_CLIPS} Hey Jarvis recordings to learn from, and "
            f"a few kept apart to check it; that session has {len(train) + len(held)}."
        )
    return Split(train=train, held=held)


class VoiceInfo(BaseModel):
    """A synthetic voice V1's kit can speak with, and its licence (permissive only)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    voice: str = Field(pattern=VOICE_ID)  # e.g. "kokoro-bm_george", "piper-en_GB-alan"
    licence: EngineLicence


class Voices(Protocol):
    """V1's speaking engines (Kokoro, licensed Piper voices) for other speakers' "Hey Jarvis"
    (the verifier's negatives and its eval) and stage 2's synthetic speech."""

    def voices(self) -> Sequence[VoiceInfo]: ...

    def say(self, voice: str, text: str) -> bytes: ...  # 16 kHz mono PCM16


class Sealer(Protocol):
    """V1's at-rest cipher (the clip store's key): the trained files are sealed like the clips."""

    def seal(self, data: bytes) -> bytes: ...

    def unseal(self, data: bytes) -> bytes: ...  # raises on a file it did not seal


class WakewordKit(Protocol):
    """The wake word's side of the kit server (one instance, from `build_wakeword`)."""

    def job_kind(self, artifact: WakeArtifact) -> JobKind: ...

    def prepare(self, req: WakeTrainIn, clips: Sequence[WakeClip]) -> WakeJob: ...

    def train(self, job: WakeJob, progress: Progress) -> ArtifactInfo: ...

    def status(self) -> WakeStatus: ...  # the stored files; V1 adds `jobs`

    def model(self, req: WakeModelIn) -> WakeModel: ...

    def delete(self) -> int: ...  # wake-word files removed


__all__ = [
    "CLIPS_MAX",
    "HELD_EVERY",
    "HELD_MIN",
    "MIN_WAKE_CLIPS",
    "Progress",
    "Sealer",
    "Split",
    "VoiceInfo",
    "Voices",
    "WakeClip",
    "WakeJob",
    "WakewordFailed",
    "WakewordKit",
    "split_wake",
]
