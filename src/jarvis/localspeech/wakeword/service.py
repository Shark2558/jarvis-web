# src/jarvis/localspeech/wakeword/service.py
"""`WakewordService`: the kit's `WakewordKit` (R5.2 row 83), built by `build_wakeword`.

Light at import (stdlib, Pydantic): the trainers, NumPy and onnxruntime are imported only when a
training run starts, so V1's server can import this anywhere. One run at a time. Stage 1 always
replaces the last verifier (the newest session); stage 2 replaces a stored owned model only when
the new one beats today's, or the stored one did not (risk 3: a worse model is never swapped in).
"""

from __future__ import annotations

import threading
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Final

from jarvis.localspeech.protocol import (
    ArtifactInfo,
    JobKind,
    KitRefused,
    WakeArtifact,
    WakeModel,
    WakeModelIn,
    WakeStatus,
    WakeTrainIn,
    encode_pcm,
)
from jarvis.localspeech.wakeword.formats import EMBEDDING_MODEL
from jarvis.localspeech.wakeword.port import (
    MIN_WAKE_CLIPS,
    Progress,
    Sealer,
    Voices,
    WakeClip,
    WakeJob,
    WakewordFailed,
)
from jarvis.localspeech.wakeword.store import ArtifactStore
from jarvis.logging import get_logger

if TYPE_CHECKING:  # the kit's runtime modules, loaded by `train` only
    from jarvis.localspeech.wakeword.mlp import Recipe
    from jarvis.localspeech.wakeword.runtime import ConsoleModels
    from jarvis.localspeech.wakeword.streaming import Runner
    from jarvis.localspeech.wakeword.verifier_train import Trained

log = get_logger(__name__)
KINDS: Final = {WakeArtifact.VERIFIER: JobKind.VERIFIER, WakeArtifact.OWNED: JobKind.OWNED}
BUSY = "The laptop is already training a wake word; try again when it has finished."
FAILED = "The wake-word training stopped with a problem on the laptop."
EARLIER_STAYS = "Done: your earlier model stays (it did better)."


def _now() -> datetime:
    return datetime.now(UTC)


def _console_models() -> ConsoleModels:
    from jarvis.localspeech.wakeword.runtime import open_console_models

    return open_console_models()


def _onnx_check(data: bytes) -> Runner:
    from jarvis.localspeech.wakeword.runtime import onnx_runner

    return onnx_runner(data)


class WakewordService:
    def __init__(
        self,
        root: Path,
        *,
        sealer: Sealer,
        voices: Voices | None = None,
        models: Callable[[], ConsoleModels] = _console_models,
        check: Callable[[bytes], Runner] | None = _onnx_check,
        recipe: Recipe | None = None,
        clock: Callable[[], datetime] = _now,
    ) -> None:
        self.store = ArtifactStore(root, sealer)
        self._voices, self._models, self._check = voices, models, check
        self._recipe, self._clock = recipe, clock
        self._lock = threading.Lock()

    def job_kind(self, artifact: WakeArtifact) -> JobKind:
        return KINDS[artifact]

    def prepare(self, req: WakeTrainIn, clips: Sequence[WakeClip]) -> WakeJob:
        if self._lock.locked():
            raise KitRefused("busy", BUSY)
        job = WakeJob(artifact=req.artifact, session_id=req.session_id, clips=tuple(clips))
        found = len(job.wake(held_out=False)) + len(job.wake(held_out=True))
        if found < MIN_WAKE_CLIPS:
            raise KitRefused(
                "not_found",
                f"Training needs at least {MIN_WAKE_CLIPS} Hey Jarvis recordings; "
                f"that session has {found} on the laptop.",
            )
        return job

    def train(self, job: WakeJob, progress: Progress) -> ArtifactInfo:
        """Blocking and CPU-bound: run it in a worker thread. WakewordFailed in plain words."""
        if not self._lock.acquire(blocking=False):
            raise WakewordFailed(BUSY)
        try:
            trained = self._run(job, progress)
            kept = self._keep(trained)
            if not kept:
                progress(1.0, EARLIER_STAYS)
            log.info(
                "wake word trained",
                extra={
                    "artifact": job.artifact.value,
                    "beats": trained.info.beats_current,
                    "kept": kept,
                },
            )
            return trained.info
        except WakewordFailed:
            raise
        except Exception as exc:  # a run never crashes the kit: the job fails in plain words
            log.error("wake word training failed", extra={"error": type(exc).__name__})
            raise WakewordFailed(FAILED) from exc
        finally:
            self._lock.release()

    def _run(self, job: WakeJob, progress: Progress) -> Trained:
        from jarvis.localspeech.wakeword.streaming import Stream

        progress(0.0, "Loading the wake-word models.")
        console = self._models()
        stream = Stream(console.features)
        if job.artifact is WakeArtifact.VERIFIER:
            from jarvis.localspeech.wakeword.verifier_train import train_verifier

            return train_verifier(
                job,
                stream,
                console.shas[EMBEDDING_MODEL],
                self._voices,
                progress,
                now=self._clock(),
            )
        from jarvis.localspeech.wakeword.owned_train import train_owned

        return train_owned(
            job,
            stream,
            console.feature_shas,
            self._voices,
            progress,
            now=self._clock(),
            recipe=self._recipe,
            check=self._check,
        )

    def _keep(self, trained: Trained) -> bool:
        info = trained.info
        if info.artifact is WakeArtifact.OWNED and not info.beats_current:
            stored = self.store.info(WakeArtifact.OWNED)
            if stored is not None and stored.beats_current:
                return False
        self.store.put(trained.data, info, trained.manifest)
        return True

    def status(self) -> WakeStatus:
        return WakeStatus(
            verifier=self.store.info(WakeArtifact.VERIFIER),
            owned=self.store.info(WakeArtifact.OWNED),
        )

    def model(self, req: WakeModelIn) -> WakeModel:
        stored = self.store.get(req.artifact)
        if stored is None:
            raise KitRefused("not_found", "That wake-word file has not been trained yet.")
        return WakeModel(
            artifact=req.artifact,
            data=encode_pcm(stored.data),  # plain base64 (the protocol's helper)
            format="json" if req.artifact is WakeArtifact.VERIFIER else "onnx",
            sha256=stored.info.sha256,
            licence=stored.info.licence,
            manifest=stored.manifest,
        )

    def delete(self) -> int:
        removed = self.store.delete_all()
        log.info("wake word files deleted", extra={"files": removed})
        return removed


def build_wakeword(root: Path, *, sealer: Sealer, voices: Voices | None = None) -> WakewordService:
    """V1's one line: the kit's wake word, its files under `root`, sealed with `sealer`."""
    return WakewordService(root, sealer=sealer, voices=voices)


__all__ = ["WakewordService", "build_wakeword"]
