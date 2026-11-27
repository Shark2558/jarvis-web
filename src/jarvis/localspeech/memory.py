# src/jarvis/localspeech/memory.py
"""`MemoryKit`: the laptop speech kit in memory (R5.2 I0), deterministic, for V2, V3 and V4's
tests and the CI mock evals (plan 5: real models only on the laptop). It keeps the `KitClient`
contract: `KitUnavailable` when `down` is set, `KitRefused` for a language without an engine, an
unknown job or a missing artifact; clips are kept per session and deleted on request; every job
finishes at once.

What it hears is scripted: `heard` maps the SHA-256 of a clip's PCM to its text; anything else is
heard as `DEFAULT_TEXT`. What it says is silence as long as the text would take to read. `calls`
names each method called, never what was in it. Kit-safe (no cloud import).
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime

from jarvis.calls.models import ENGLISH
from jarvis.localspeech.protocol import (
    OWNER_LICENCE,
    PROTOCOL,
    SAMPLE_RATE,
    SLOT_KIND,
    ArtifactInfo,
    AudioFormat,
    ClipIn,
    ClipStored,
    Deleted,
    DeleteIn,
    Device,
    EngineHealth,
    EngineSlot,
    HeardRow,
    JobKind,
    JobState,
    JobView,
    Kind,
    KitHealth,
    KitRefused,
    KitUnavailable,
    PromptKind,
    ScoreIn,
    SessionHeard,
    SttRequest,
    SttResult,
    TtsRequest,
    TtsResult,
    UnavailableReason,
    WakeArtifact,
    WakeModel,
    WakeStatus,
    WakeTrainIn,
    encode_pcm,
    new_job_id,
    pcm_seconds,
)

INDIAN_TEST_LANGUAGES = ("hi-IN", "ml-IN")  # what the fake's Indian engines serve
SECONDS_PER_CHAR = 0.06  # how long the fake's silence lasts per character of text
_FAKE_MP3 = b"ID3\x04\x00\x00\x00\x00\x00\x00"  # an MP3 header and nothing to play
_KIND_OF: dict[WakeArtifact, JobKind] = {
    WakeArtifact.VERIFIER: JobKind.VERIFIER,
    WakeArtifact.OWNED: JobKind.OWNED,
}


def _engine(slot: EngineSlot, languages: tuple[str, ...], licence: str) -> EngineHealth:
    return EngineHealth(
        slot=slot,
        kind=SLOT_KIND[slot],
        languages=languages,
        model=f"{slot.value}-fake",
        licence=licence,
        ready=True,
        device=Device.CUDA,
    )


def default_health() -> KitHealth:
    """A healthy kit on a graphics card: English and two Indian languages, both ways."""
    return KitHealth(
        protocol=PROTOCOL,
        kit_version="1.0.0",
        device=Device.CUDA,
        gpu_free_mb=3_500,
        ram_free_mb=8_000,
        engines=(
            _engine(EngineSlot.WHISPER_SMALL, (ENGLISH,), "MIT"),
            _engine(EngineSlot.WHISPER_MEDIUM, (ENGLISH,), "MIT"),
            _engine(EngineSlot.KOKORO, (ENGLISH,), "Apache-2.0"),
            _engine(EngineSlot.PIPER, (ENGLISH,), "MIT"),
            _engine(EngineSlot.INDIC_CONFORMER, INDIAN_TEST_LANGUAGES, "MIT"),
            _engine(EngineSlot.INDIC_PARLER, INDIAN_TEST_LANGUAGES, "Apache-2.0"),
        ),
    )


class MemoryKit:
    DEFAULT_TEXT = "hello jarvis"

    def __init__(self, *, heard: dict[str, str] | None = None, health: KitHealth | None = None):
        self.heard = dict(heard or {})
        self.base_health = health or default_health()
        self.down: UnavailableReason | None = None
        self.slow = False
        self.calls: list[str] = []
        self._clips: dict[str, dict[str, ClipIn]] = {}
        self._jobs: dict[str, JobView] = {}
        self._artifacts: dict[WakeArtifact, tuple[bytes, ArtifactInfo]] = {}

    def __repr__(self) -> str:
        return f"MemoryKit(clips={sum(len(c) for c in self._clips.values())})"

    def clip_count(self, session_id: str) -> int:
        return len(self._clips.get(session_id, {}))

    def _enter(self, name: str) -> None:
        self.calls.append(name)
        if self.down is not None:
            raise KitUnavailable(self.down)

    def _slot(self, kind: Kind, lang: str, asked: EngineSlot | None) -> EngineSlot:
        health = self.base_health
        if asked is not None:
            ok = any(e.slot is asked and e.ready and lang in e.languages for e in health.engines)
            slot: EngineSlot | None = asked if ok else None
        else:
            slot = health.engine_for(kind, lang)
        if slot is None:
            raise KitRefused("unsupported_language", "That language has no engine on the laptop.")
        return slot

    def _text_of(self, pcm: bytes) -> str:
        return self.heard.get(hashlib.sha256(pcm).hexdigest(), self.DEFAULT_TEXT)

    def _job(self, kind: JobKind) -> JobView:
        now = datetime.now(UTC)
        job = JobView(
            job_id=new_job_id(),
            kind=kind,
            state=JobState.DONE,
            progress=1.0,
            started_at=now,
            finished_at=now,
        )
        self._jobs[job.job_id] = job
        return job

    # ---- KitClient ---------------------------------------------------------------------------
    async def health(self) -> KitHealth:
        self._enter("health")
        return self.base_health.model_copy(update={"slow": self.slow})

    async def stt(self, req: SttRequest) -> SttResult:
        self._enter("stt")
        slot = self._slot(Kind.STT, req.lang, req.slot)
        pcm = req.pcm()
        return SttResult(
            lang=req.lang,
            text=self._text_of(pcm),
            confidence=0.9,
            seconds=pcm_seconds(len(pcm)),
            slot=slot,
        )

    async def tts(self, req: TtsRequest) -> TtsResult:
        self._enter("tts")
        slot = self._slot(Kind.TTS, req.lang, req.slot)
        seconds = round(len(req.text) * SECONDS_PER_CHAR / req.rate, 3)
        if req.format is AudioFormat.MP3:
            audio, rate = encode_pcm(_FAKE_MP3), 24_000
        else:
            audio, rate = encode_pcm(b"\x00\x00" * int(seconds * SAMPLE_RATE)), SAMPLE_RATE
        return TtsResult(
            format=req.format,
            audio=audio,
            sample_rate=rate,
            seconds=seconds,
            slot=slot,
            voice=req.voice or f"{slot.value}-default",
        )

    async def put_clip(self, clip: ClipIn) -> ClipStored:
        self._enter("put_clip")
        session = self._clips.setdefault(clip.session_id, {})
        session[clip.prompt_id] = clip
        return ClipStored(
            session_id=clip.session_id,
            prompt_id=clip.prompt_id,
            seconds=pcm_seconds(len(clip.pcm())),
            clips=len(session),
        )

    async def score(self, req: ScoreIn) -> JobView:
        self._enter("score")
        if not self._clips.get(req.session_id):
            raise KitRefused("not_found", "That session has no recordings on the laptop.")
        return self._job(JobKind.SCORE)

    async def results(self, session_id: str) -> SessionHeard:
        self._enter("results")
        clips = self._clips.get(session_id, {})
        rows = tuple(
            HeardRow(prompt_id=pid, slot=EngineSlot.WHISPER_SMALL, text=self._text_of(c.pcm()))
            for pid, c in sorted(clips.items())
        )
        return SessionHeard(session_id=session_id, rows=rows)

    async def delete(self, req: DeleteIn) -> Deleted:
        self._enter("delete")
        ids = [req.session_id] if req.session_id is not None else list(self._clips)
        clips = sum(len(self._clips.pop(i, {})) for i in ids)
        files = len(self._artifacts) if req.wakeword else 0
        if req.wakeword:
            self._artifacts.clear()
        return Deleted(clips=clips, wakeword_files=files)

    async def job(self, job_id: str) -> JobView:
        self._enter("job")
        found = self._jobs.get(job_id)
        if found is None:
            raise KitRefused("not_found", "There is no such job on the laptop.")
        return found

    async def wakeword_train(self, req: WakeTrainIn) -> JobView:
        self._enter("wakeword_train")
        wake = [
            c for c in self._clips.get(req.session_id, {}).values() if c.kind is PromptKind.WAKE
        ]
        if not wake:
            raise KitRefused("not_found", "That session has no Hey Jarvis recordings.")
        data = json.dumps({"artifact": req.artifact.value, "clips": len(wake)}).encode()
        info = ArtifactInfo(
            artifact=req.artifact,
            sha256=hashlib.sha256(data).hexdigest(),
            size=len(data),
            trained_at=datetime.now(UTC),
            licence=OWNER_LICENCE,
        )
        self._artifacts[req.artifact] = (data, info)
        return self._job(_KIND_OF[req.artifact])

    async def wakeword_status(self) -> WakeStatus:
        self._enter("wakeword_status")
        verifier = self._artifacts.get(WakeArtifact.VERIFIER)
        owned = self._artifacts.get(WakeArtifact.OWNED)
        return WakeStatus(
            verifier=verifier[1] if verifier else None,
            owned=owned[1] if owned else None,
        )

    async def wakeword_model(self, artifact: WakeArtifact) -> WakeModel:
        self._enter("wakeword_model")
        found = self._artifacts.get(artifact)
        if found is None:
            raise KitRefused("not_found", "That wake-word file has not been trained yet.")
        data, info = found
        return WakeModel(
            artifact=artifact,
            data=encode_pcm(data),
            format="json" if artifact is WakeArtifact.VERIFIER else "onnx",
            sha256=info.sha256,
            licence=info.licence,
        )


__all__ = ["INDIAN_TEST_LANGUAGES", "MemoryKit", "default_health"]
