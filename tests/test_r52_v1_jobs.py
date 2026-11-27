# tests/test_r52_v1_jobs.py -- R5.2 V1: the kit's long jobs. One at a time (busy otherwise),
# polled until finished, plain words (an error's own text never shown), cancelled when asked,
# only the last few kept.
from __future__ import annotations

import time
from datetime import UTC, datetime

import pytest

from jarvis.localspeech import protocol as p
from jarvis.localspeech.jobs import BUSY_WORDS, FAILED_WORDS, KEEP_FINISHED, JobRunner, Progress


async def test_a_job_runs_and_reports_done_with_its_words() -> None:
    runner = JobRunner()

    def work(progress: Progress) -> str:
        progress.set(0.5, "half")
        return "Heard 3 recordings."

    view = runner.start(p.JobKind.SCORE, work, session_id="vs_000000000001", long=False)
    assert p.JOB_ID_RE.fullmatch(view.job_id) and not view.finished
    done = await runner.wait(view.job_id)
    assert (done.state, done.progress, done.words) == (p.JobState.DONE, 1.0, "Heard 3 recordings.")
    assert done.started_at and done.finished_at and done.finished_at >= done.started_at
    assert runner.running == 0 and not runner.long_running


async def test_a_second_job_waits_its_turn_as_busy() -> None:
    runner = JobRunner()

    def slow(progress: Progress) -> str:
        while not progress.cancelled:
            time.sleep(0.01)
        return ""

    first = runner.start(p.JobKind.OWNED, slow, session_id=None, long=True)
    assert runner.long_running
    with pytest.raises(p.KitRefused) as busy:
        runner.start(p.JobKind.SCORE, lambda _: "", session_id=None, long=False)
    assert (busy.value.code, busy.value.words) == ("busy", BUSY_WORDS)
    runner.cancel_for(None)
    assert (await runner.wait(first.job_id)).state is p.JobState.CANCELLED


async def test_a_failure_shows_plain_words_never_the_errors_text() -> None:
    runner = JobRunner()

    def broken(progress: Progress) -> str:
        raise OSError("C:\\Users\\someone\\clips\\vs_x - transcript: my PIN")

    def refused(progress: Progress) -> str:
        raise p.KitRefused("engine_not_ready", "Its program is not installed.")

    one = runner.start(p.JobKind.SCORE, broken, session_id=None, long=False)
    assert (await runner.wait(one.job_id)).words == FAILED_WORDS
    two = runner.start(p.JobKind.VERIFIER, refused, session_id=None, long=True)
    failed = await runner.wait(two.job_id)
    assert (failed.state, failed.words) == (p.JobState.FAILED, "Its program is not installed.")


async def test_cancel_only_touches_the_named_sessions_job() -> None:
    runner = JobRunner()
    released = {"go": False}

    def wait(progress: Progress) -> str:
        while not (progress.cancelled or released["go"]):
            time.sleep(0.01)
        return "done"

    job = runner.start(p.JobKind.SCORE, wait, session_id="vs_000000000001", long=False)
    runner.cancel_for("vs_000000000002")
    released["go"] = True
    assert (await runner.wait(job.job_id)).state is p.JobState.DONE


async def test_unknown_jobs_and_old_jobs() -> None:
    runner = JobRunner(now=lambda: datetime(2026, 11, 27, tzinfo=UTC))
    with pytest.raises(p.KitRefused) as missing:
        runner.view("job_000000000000")
    assert missing.value.code == "not_found"
    ids = []
    for _ in range(KEEP_FINISHED + 3):
        job = runner.start(p.JobKind.SCORE, lambda _: "ok", session_id=None, long=False)
        await runner.wait(job.job_id)
        ids.append(job.job_id)
    runner.start(p.JobKind.SCORE, lambda _: "ok", session_id=None, long=False)
    with pytest.raises(p.KitRefused):
        runner.view(ids[0])
    assert runner.view(ids[-1]).state is p.JobState.DONE
    assert len(runner.views([p.JobKind.SCORE])) == 8
    await runner.close()


def test_progress_stays_between_zero_and_one() -> None:
    progress = Progress()
    progress.set(7)
    assert progress.value == 1.0
    progress.set(-1, "x" * 500)
    assert progress.value == 0.0 and len(progress.words) == p.WORDS_MAX
