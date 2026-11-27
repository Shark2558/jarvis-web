# src/jarvis/localspeech/ports.py
"""The one seam the kit's server calls for the wake word (R5.2 V1 for V4; row 83). Kit-safe.

V4 implements `WakewordTrainer` in `jarvis.localspeech.wakeword` and the join hands it to
`service.build_service(..., wakeword=...)` (one line in `__main__.serve`). The server owns the
HTTP side, the job (`jobs.JobRunner`: one at a time, polled, cancellable) and the recordings
(`clips.ClipVault`); the trainer gets the session's "Hey Jarvis" clips already opened, trains in
the job's worker thread, and keeps its own files (in `KitConfig.wakeword_dir`).

Until V4 joins, `NoWakeword` answers every wake-word request with `engine_not_ready`.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Final, Protocol

from jarvis.localspeech.protocol import ArtifactInfo, KitRefused, WakeArtifact, WakeModel


@dataclass(frozen=True)
class WakeClip:
    """One "Hey Jarvis" recording of the session, opened: PCM16 16 kHz mono."""

    prompt_id: str
    pcm: bytes
    held_out: bool  # scored, never trained on


class ProgressSink(Protocol):
    """What the trainer reports to (`jobs.Progress`)."""

    def set(self, fraction: float, words: str = "") -> None: ...

    @property
    def cancelled(self) -> bool: ...


class WakewordTrainer(Protocol):
    def unready(self, artifact: WakeArtifact) -> str | None:
        """None when `artifact` can be trained now; else plain words why not."""
        ...

    def train(
        self, artifact: WakeArtifact, clips: Sequence[WakeClip], progress: ProgressSink
    ) -> ArtifactInfo:
        """Blocking (runs in the job's thread); stop early when `progress.cancelled`. Raises
        `KitRefused` with plain words when it can't (the job then fails with those words)."""
        ...

    def artifacts(self) -> Mapping[WakeArtifact, ArtifactInfo]:
        """What has been trained and kept on this laptop."""
        ...

    def model(self, artifact: WakeArtifact) -> WakeModel:
        """The file for the console; `KitRefused("not_found")` when there is none."""
        ...

    def delete(self) -> int:
        """Remove every wake-word file trained here; how many there were."""
        ...


NOT_BUILT: Final = "Wake-word training is not part of this kit yet."


class NoWakeword:
    """The stub until V4's trainer joins: nothing trained, nothing trainable."""

    def unready(self, artifact: WakeArtifact) -> str | None:
        return NOT_BUILT

    def train(
        self, artifact: WakeArtifact, clips: Sequence[WakeClip], progress: ProgressSink
    ) -> ArtifactInfo:
        raise KitRefused("engine_not_ready", NOT_BUILT)

    def artifacts(self) -> Mapping[WakeArtifact, ArtifactInfo]:
        return {}

    def model(self, artifact: WakeArtifact) -> WakeModel:
        raise KitRefused("not_found", "That wake-word file has not been trained yet.")

    def delete(self) -> int:
        return 0


__all__ = ["NOT_BUILT", "NoWakeword", "ProgressSink", "WakeClip", "WakewordTrainer"]
