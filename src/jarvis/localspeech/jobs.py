# src/jarvis/localspeech/jobs.py
"""The kit's long jobs (R5.2 V1): the session's scoring runs (row 81) and the wake-word training
(row 83, V4's trainer). Kit-safe: the standard library only.

One job runs at a time (the graphics card is shared), in a worker thread, and is polled with
`GET /v1/jobs/{job_id}`; a second one is refused as `busy`. A job's words are plain and never
carry an error's own text (it could quote a path or a transcript). The last few finished jobs are
kept in memory for polling; nothing about a job is written to disk.
"""

from __future__ import annotations

import asyncio
import logging
import threading
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Final

from jarvis.localspeech.protocol import (
    WORDS_MAX,
    JobKind,
    JobState,
    JobView,
    KitRefused,
    new_job_id,
)

log = logging.getLogger(__name__)

KEEP_FINISHED: Final = 16
FAILED_WORDS: Final = "The job failed on the laptop (run the kit's self-test)."
CANCELLED_WORDS: Final = "The job was stopped (its recordings were deleted, or the kit stopped)."
BUSY_WORDS: Final = "The laptop is busy with another job; try again when it has finished."


class Progress:
    """Handed to a job's work: report progress, and stop early when `cancelled`."""

    def __init__(self) -> None:
        self._value = 0.0
        self._words = ""
        self._stop = threading.Event()

    def set(self, fraction: float, words: str = "") -> None:
        self._value = min(1.0, max(0.0, float(fraction)))
        if words:
            self._words = words[:WORDS_MAX]

    @property
    def value(self) -> float:
        return self._value

    @property
    def words(self) -> str:
        return self._words

    @property
    def cancelled(self) -> bool:
        return self._stop.is_set()

    def cancel(self) -> None:
        self._stop.set()


Work = Callable[[Progress], str]  # runs in a worker thread; returns plain words for "done"


@dataclass
class _Job:
    job_id: str
    kind: JobKind
    session_id: str | None
    long: bool
    progress: Progress = field(default_factory=Progress)
    state: JobState = JobState.QUEUED
    words: str = ""
    started_at: datetime | None = None
    finished_at: datetime | None = None
    task: asyncio.Task[None] | None = None

    def view(self) -> JobView:
        progress = 1.0 if self.state is JobState.DONE else self.progress.value
        words = self.words or self.progress.words
        return JobView(
            job_id=self.job_id,
            kind=self.kind,
            state=self.state,
            progress=progress,
            words=words[:WORDS_MAX],
            started_at=self.started_at,
            finished_at=self.finished_at,
        )


class JobRunner:
    def __init__(self, *, now: Callable[[], datetime] = lambda: datetime.now(UTC)) -> None:
        self._jobs: dict[str, _Job] = {}
        self._now = now

    def active(self) -> _Job | None:
        return next(
            (j for j in self._jobs.values() if j.state in (JobState.QUEUED, JobState.RUNNING)),
            None,
        )

    @property
    def running(self) -> int:
        return 1 if self.active() is not None else 0

    @property
    def long_running(self) -> bool:
        """A long job (training) is on the card: live speech waits for it (`busy`)."""
        job = self.active()
        return job is not None and job.long

    def start(self, kind: JobKind, work: Work, *, session_id: str | None, long: bool) -> JobView:
        if self.active() is not None:
            raise KitRefused("busy", BUSY_WORDS)
        job = _Job(new_job_id(), kind, session_id, long)
        self._jobs[job.job_id] = job
        self._trim()
        job.task = asyncio.get_running_loop().create_task(self._run(job, work))
        return job.view()

    async def _run(self, job: _Job, work: Work) -> None:
        job.state, job.started_at = JobState.RUNNING, self._now()
        try:
            words = await asyncio.to_thread(work, job.progress)
        except KitRefused as refused:
            job.state, job.words = JobState.FAILED, refused.words
        except Exception as exc:  # noqa: BLE001 - a job's failure is reported, never raised
            log.warning("job %s failed: %s", job.kind.value, type(exc).__name__)
            job.state, job.words = JobState.FAILED, FAILED_WORDS
        else:
            if job.progress.cancelled:
                job.state, job.words = JobState.CANCELLED, CANCELLED_WORDS
            else:
                job.state, job.words = JobState.DONE, words[:WORDS_MAX]
        if job.progress.cancelled and job.state is JobState.FAILED:
            job.state, job.words = JobState.CANCELLED, CANCELLED_WORDS
        job.finished_at = self._now()

    def _trim(self) -> None:
        finished = [
            j for j in self._jobs.values() if j.state not in (JobState.QUEUED, JobState.RUNNING)
        ]
        for old in finished[: max(0, len(finished) - KEEP_FINISHED)]:
            self._jobs.pop(old.job_id, None)

    def view(self, job_id: str) -> JobView:
        job = self._jobs.get(job_id)
        if job is None:
            raise KitRefused("not_found", "There is no such job on the laptop.")
        return job.view()

    def views(self, kinds: Iterable[JobKind], most: int = 8) -> tuple[JobView, ...]:
        wanted = set(kinds)
        found = [j.view() for j in self._jobs.values() if j.kind in wanted]
        return tuple(found[-most:])

    def cancel_for(self, session_id: str | None) -> None:
        """Stop the running job of `session_id` (any session when None)."""
        job = self.active()
        if job is not None and (session_id is None or job.session_id == session_id):
            job.progress.cancel()

    async def wait(self, job_id: str) -> JobView:
        """Until the job finishes (the tests and the self-test)."""
        job = self._jobs.get(job_id)
        if job is None:
            raise KitRefused("not_found", "There is no such job on the laptop.")
        if job.task is not None:
            await asyncio.shield(job.task)
        return job.view()

    async def close(self) -> None:
        for job in self._jobs.values():
            job.progress.cancel()
        tasks = [j.task for j in self._jobs.values() if j.task is not None and not j.task.done()]
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)


__all__ = ["BUSY_WORDS", "FAILED_WORDS", "JobRunner", "Progress", "Work"]
