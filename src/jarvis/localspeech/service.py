# src/jarvis/localspeech/service.py
"""What the kit does for each request of its API (R5.2 V1; `protocol`'s routes). Kit-safe. The
HTTP side is `server.py`; this module is the same behaviour without HTTP, so the tests and the
self-test drive it directly.

- Listening and speaking run one at a time on the kit's engines (a lock, in a worker thread);
  while a long job (wake-word training) is on the graphics card they answer `busy`, and the
  health answer says `slow` whenever a job runs or requests queue, so routing falls back.
- An engine that breaks mid-request is put away and the request answers `engine_not_ready`
  (the cloud falls back; the engine reloads next time).
- Recordings go to `clips.ClipVault` (encrypted); scoring is a job; deleting stops the job.
- The wake word goes through `ports.WakewordTrainer` (V4), `NoWakeword` until it joins.
Nothing here logs audio, text, a voice or the key.
"""

from __future__ import annotations

import asyncio
import importlib
import importlib.util
import logging
import threading
import time
from collections.abc import Callable
from typing import Final, TypeVar

from jarvis.calls.models import ENGLISH
from jarvis.localspeech import device as devices
from jarvis.localspeech.audio import Mp3Encoder, resample_pcm16
from jarvis.localspeech.clips import ClipVault
from jarvis.localspeech.engines import Slots
from jarvis.localspeech.jobs import JobRunner, Progress
from jarvis.localspeech.kitconfig import KIT_VERSION_NOW, KitConfig
from jarvis.localspeech.manager import ModelManager, load_manifest
from jarvis.localspeech.ports import NoWakeword, WakeClip, WakewordTrainer
from jarvis.localspeech.protocol import (
    MP3_RATES,
    PROTOCOL,
    SAMPLE_BYTES,
    SAMPLE_RATE,
    TEXT_MAX,
    AudioFormat,
    ClipIn,
    ClipStored,
    Deleted,
    DeleteIn,
    EngineSlot,
    HeardRow,
    JobKind,
    JobView,
    Kind,
    KitHealth,
    KitRefused,
    PromptKind,
    ResultsIn,
    ScoreIn,
    SessionHeard,
    SttRequest,
    SttResult,
    TtsRequest,
    TtsResult,
    WakeArtifact,
    WakeModel,
    WakeModelIn,
    WakeStatus,
    WakeTrainIn,
    encode_pcm,
    pcm_seconds,
)

log = logging.getLogger(__name__)

T = TypeVar("T")
SLOW_QUEUE: Final = 2  # requests waiting for the engines before the kit says it is slow
MEMORY_CACHE_S: Final = 10.0
MP3_FALLBACK_RATE: Final = 24_000
ENGINE_BROKE: Final = "The engine stopped on the laptop; it is reloaded next time."
_WAKE_JOB: Final[dict[WakeArtifact, JobKind]] = {
    WakeArtifact.VERIFIER: JobKind.VERIFIER,
    WakeArtifact.OWNED: JobKind.OWNED,
}

Memory = Callable[[], tuple[int | None, int]]  # (graphics memory free, memory free) in MB


def _memory() -> tuple[int | None, int]:
    return devices.gpu_free_mb(), devices.ram_free_mb()


class KitService:
    def __init__(
        self,
        *,
        slots: Slots,
        vault: ClipVault,
        runner: JobRunner | None = None,
        wakeword: WakewordTrainer | None = None,
        mp3: Mp3Encoder | None = None,
        memory: Memory = _memory,
        kit_version: str = KIT_VERSION_NOW,
    ) -> None:
        self.slots = slots
        self.vault = vault
        self.runner = runner or JobRunner()
        self.wakeword: WakewordTrainer = wakeword or NoWakeword()
        self._mp3 = mp3
        self._memory = memory
        self._kit_version = kit_version
        self._infer = threading.Lock()
        self._waiting = 0
        self._memory_at = -MEMORY_CACHE_S
        self._memory_seen: tuple[int | None, int] = (None, 0)

    def __repr__(self) -> str:
        return f"KitService(kit {self._kit_version})"

    # ---- engines, one at a time ---------------------------------------------------------------
    async def _locked(self, fn: Callable[[], T]) -> T:
        def run() -> T:
            with self._infer:
                return fn()

        self._waiting += 1
        try:
            return await asyncio.to_thread(run)
        finally:
            self._waiting -= 1

    def _not_busy(self) -> None:
        if self.runner.long_running:
            raise KitRefused("busy", "The laptop is training the wake word just now.")

    @property
    def slow(self) -> bool:
        return self.runner.running > 0 or self._waiting >= SLOW_QUEUE

    def _guarded(self, slot: EngineSlot, fn: Callable[[], T]) -> T:
        try:
            return fn()
        except KitRefused:
            raise
        except Exception as exc:  # noqa: BLE001 - a broken engine never takes the kit down
            log.warning("engine %s failed: %s", slot.value, type(exc).__name__)
            self.slots.unload(slot)
            raise KitRefused("engine_not_ready", ENGINE_BROKE) from None

    # ---- GET /health ------------------------------------------------------------------------
    async def health(self) -> KitHealth:
        now = time.monotonic()
        if now - self._memory_at >= MEMORY_CACHE_S:
            self._memory_seen = await asyncio.to_thread(self._memory)
            self._memory_at = now
        gpu_free, ram_free = self._memory_seen
        return KitHealth(
            protocol=PROTOCOL,
            kit_version=self._kit_version,
            device=self.slots.device,
            gpu_free_mb=gpu_free,
            ram_free_mb=max(0, ram_free),
            engines=self.slots.health(),
            jobs_running=self.runner.running,
            slow=self.slow,
        )

    # ---- POST /stt --------------------------------------------------------------------------
    async def stt(self, req: SttRequest) -> SttResult:
        self._not_busy()
        slot = self.slots.pick(Kind.STT, req.lang, req.slot)
        pcm = req.pcm()
        started = time.monotonic()

        def hear() -> SttResult:
            engine = self.slots.stt(slot)
            heard = self._guarded(slot, lambda: engine.transcribe(pcm, req.lang, req.phrases))
            return SttResult(
                lang=req.lang,
                text=heard.text.strip()[:TEXT_MAX],
                confidence=min(1.0, max(0.0, heard.confidence)),
                seconds=round(pcm_seconds(len(pcm)), 3),
                slot=slot,
                alternatives=tuple(a[:TEXT_MAX] for a in heard.alternatives[:2]),
                elapsed_ms=int((time.monotonic() - started) * 1000),
            )

        return await self._locked(hear)

    # ---- POST /tts --------------------------------------------------------------------------
    async def tts(self, req: TtsRequest) -> TtsResult:
        self._not_busy()
        slot = self.slots.pick(Kind.TTS, req.lang, req.slot)
        if req.format is AudioFormat.MP3 and self._mp3 is None:
            raise KitRefused("engine_not_ready", "This kit can't make MP3 audio.")
        spec = self.slots.spec(slot)
        started = time.monotonic()

        def say() -> TtsResult:
            engine = self.slots.tts(slot)
            voice = req.voice or (spec.default_voice if spec else "") or min(engine.voices)
            if voice not in engine.voices:
                raise KitRefused("bad_request", "That voice is not on the laptop.")
            spoken = self._guarded(
                slot, lambda: engine.synthesize(req.text, req.lang, voice, req.rate)
            )
            audio, rate, seconds = self._encode(req.format, spoken.pcm, spoken.sample_rate)
            elapsed = int((time.monotonic() - started) * 1000)
            return TtsResult(
                format=req.format,
                audio=audio,
                sample_rate=rate,
                seconds=round(seconds, 3),
                slot=slot,
                voice=voice,
                first_audio_ms=spoken.first_audio_ms or elapsed,
                elapsed_ms=elapsed,
            )

        return await self._locked(say)

    def _encode(self, fmt: AudioFormat, pcm: bytes, rate: int) -> tuple[str, int, float]:
        if fmt is AudioFormat.PCM16:
            out = resample_pcm16(pcm, rate, SAMPLE_RATE)
            return encode_pcm(out), SAMPLE_RATE, pcm_seconds(len(out))
        assert self._mp3 is not None  # tts() checked
        if rate not in MP3_RATES:
            pcm, rate = resample_pcm16(pcm, rate, MP3_FALLBACK_RATE), MP3_FALLBACK_RATE
        seconds = len(pcm) / (SAMPLE_BYTES * rate)
        return encode_pcm(self._mp3.encode(pcm, rate)), rate, seconds

    # ---- the session (row 81) -----------------------------------------------------------------
    async def put_clip(self, clip: ClipIn) -> ClipStored:
        return await asyncio.to_thread(self.vault.put, clip)

    async def score(self, req: ScoreIn) -> JobView:
        if await asyncio.to_thread(self.vault.count, req.session_id) == 0:
            raise KitRefused("not_found", "That session has no recordings on the laptop.")
        for slot in req.slots:
            self.slots.pick(Kind.STT, ENGLISH, slot)  # refuses an engine that isn't ready
        return self.runner.start(
            JobKind.SCORE, self._score_work(req), session_id=req.session_id, long=False
        )

    def _score_work(self, req: ScoreIn) -> Callable[[Progress], str]:
        def work(progress: Progress) -> str:
            clips = [c for c in self.vault.clips(req.session_id) if c.held_out]
            total = max(1, len(clips) * len(req.slots))
            rows: list[HeardRow] = []
            for slot in req.slots:
                for clip in clips:
                    if progress.cancelled:
                        return ""
                    rows.append(self._hear_row(slot, clip.prompt_id, clip.pcm, req.phrases))
                    progress.set(len(rows) / total, f"{len(rows)} of {total} heard")
            self.vault.put_heard(req.session_id, tuple(rows))
            if not clips:
                return "That session has no held-out recordings to score."
            return f"Heard {len(clips)} recordings with {len(req.slots)} laptop engines."

        return work

    def _hear_row(
        self, slot: EngineSlot, prompt_id: str, pcm: bytes, phrases: tuple[str, ...]
    ) -> HeardRow:
        with self._infer:
            started = time.monotonic()
            engine = self.slots.stt(slot)
            heard = self._guarded(slot, lambda: engine.transcribe(pcm, ENGLISH, phrases))
            return HeardRow(
                prompt_id=prompt_id,
                slot=slot,
                text=heard.text.strip()[:TEXT_MAX],
                elapsed_ms=int((time.monotonic() - started) * 1000),
            )

    async def results(self, req: ResultsIn) -> SessionHeard:
        return await asyncio.to_thread(self.vault.heard, req.session_id)

    async def delete(self, req: DeleteIn) -> Deleted:
        self.runner.cancel_for(None if req.wakeword else req.session_id)
        clips = await asyncio.to_thread(self.vault.delete, req.session_id)
        files = await asyncio.to_thread(self.wakeword.delete) if req.wakeword else 0
        return Deleted(clips=clips, wakeword_files=files)

    async def job(self, job_id: str) -> JobView:
        return self.runner.view(job_id)

    # ---- the wake word (row 83, V4's trainer) -------------------------------------------------
    async def wake_train(self, req: WakeTrainIn) -> JobView:
        reason = self.wakeword.unready(req.artifact)
        if reason is not None:
            raise KitRefused("engine_not_ready", reason)
        stored = await asyncio.to_thread(self.vault.clips, req.session_id, kind=PromptKind.WAKE)
        if not stored:
            raise KitRefused("not_found", "That session has no Hey Jarvis recordings.")
        clips = tuple(WakeClip(c.prompt_id, c.pcm, c.held_out) for c in stored)

        def work(progress: Progress) -> str:
            self.wakeword.train(req.artifact, clips, progress)
            return "The wake-word file is trained."

        return self.runner.start(
            _WAKE_JOB[req.artifact], work, session_id=req.session_id, long=True
        )

    async def wake_status(self) -> WakeStatus:
        found = await asyncio.to_thread(self.wakeword.artifacts)
        return WakeStatus(
            verifier=found.get(WakeArtifact.VERIFIER),
            owned=found.get(WakeArtifact.OWNED),
            jobs=self.runner.views(_WAKE_JOB.values()),
        )

    async def wake_model(self, req: WakeModelIn) -> WakeModel:
        return await asyncio.to_thread(self.wakeword.model, req.artifact)

    async def close(self) -> None:
        await self.runner.close()
        await asyncio.to_thread(self.slots.unload_all)


def default_mp3() -> Mp3Encoder | None:
    """The kit's MP3 encoder (PyAV) when PyAV is installed, else None (MP3 requests refused)."""
    if importlib.util.find_spec("av") is None:
        return None
    module = importlib.import_module("jarvis.localspeech.runtimes.mp3")
    encoder: Mp3Encoder = module.PyAvMp3()
    return encoder


def build_service(
    config: KitConfig,
    *,
    wakeword: WakewordTrainer | None = None,
    mp3: Mp3Encoder | None = None,
) -> KitService:
    """The kit as installed: its manifest, models, device, recordings and (V4) wake word."""
    manager = ModelManager(load_manifest(config.manifest), config.models_dir, config.installed_file)
    found = devices.detect(config.device)
    slots = Slots(installed=manager.model_dir, device=found)
    vault = ClipVault(config.clips_dir, config.clip_key_file)
    return KitService(
        slots=slots,
        vault=vault,
        wakeword=wakeword,
        mp3=mp3 if mp3 is not None else default_mp3(),
    )


__all__ = ["SLOW_QUEUE", "KitService", "build_service", "default_mp3"]
