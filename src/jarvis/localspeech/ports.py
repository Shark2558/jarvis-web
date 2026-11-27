# src/jarvis/localspeech/ports.py
"""The one seam the kit's server calls for the wake word (R5.2 V1 for V4; row 83). Kit-safe.

The interface is V4's `jarvis.localspeech.wakeword.port.WakewordKit` (the build brief: V1's server
calls the wake word "through a small interface V4 defines there"); the I1 join adapted V1's
server to it (`docs/plans/r5-2-integration/I1-NOTES.md`). The server owns the HTTP side, the job
(`jobs.JobRunner`: one at a time, polled, cancellable) and the recordings (`clips.ClipVault`): it
hands `prepare` every clip of the session, opened (his "Hey Jarvis" clips and, as the verifier's
negatives, his other prompts), so a request that can't be trained is refused before a job is
queued; `train` then runs in the job's worker thread and keeps its own files (sealed, in
`KitConfig.wakeword_dir`). `__main__.serve` builds it with `wakejoin.kit_wakeword(config)`.

Without it (`NoWakeword`) every wake-word request answers `engine_not_ready`.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Final

from jarvis.localspeech.protocol import (
    ArtifactInfo,
    JobKind,
    KitRefused,
    WakeArtifact,
    WakeModel,
    WakeModelIn,
    WakeStatus,
    WakeTrainIn,
)
from jarvis.localspeech.wakeword.port import (
    Progress,
    WakeClip,
    WakeJob,
    WakewordFailed,
    WakewordKit,
)

NOT_BUILT: Final = "Wake-word training is not part of this kit yet."
KINDS: Final[dict[WakeArtifact, JobKind]] = {
    WakeArtifact.VERIFIER: JobKind.VERIFIER,
    WakeArtifact.OWNED: JobKind.OWNED,
}


class NoWakeword:
    """A kit without wake-word training: nothing trained, nothing trainable."""

    def job_kind(self, artifact: WakeArtifact) -> JobKind:
        return KINDS[artifact]

    def prepare(self, req: WakeTrainIn, clips: Sequence[WakeClip]) -> WakeJob:
        raise KitRefused("engine_not_ready", NOT_BUILT)

    def train(self, job: WakeJob, progress: Progress) -> ArtifactInfo:
        raise WakewordFailed(NOT_BUILT)

    def status(self) -> WakeStatus:
        return WakeStatus()

    def model(self, req: WakeModelIn) -> WakeModel:
        raise KitRefused("not_found", "That wake-word file has not been trained yet.")

    def delete(self) -> int:
        return 0


__all__ = [
    "KINDS",
    "NOT_BUILT",
    "NoWakeword",
    "Progress",
    "WakeClip",
    "WakeJob",
    "WakewordFailed",
    "WakewordKit",
]
