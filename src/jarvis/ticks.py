# src/jarvis/ticks.py
"""Tick jobs: housekeeping and daily work that rides the scheduler tick (R2 D5, D9).

A feature adds a `TickJob` (vault reminders, the DigiLocker inbox) to `app.state.tick_jobs`; the
tick (`api/brief.py`) calls `run_jobs` after its fixed sweeps. `run_jobs` never raises: a job that
fails, times out (`asyncio.timeout(budget_s)`, capped at `MAX_BUDGET_S`) or answers oddly is
logged (class name only) and reported "failed", the same words the sweeps use. So is a job whose
counts carry `failed` > 0: jobs isolate owners (one owner's failure stops no one) and count the
owners they could not serve. Jobs run one after another so the tick's CPU use stays bounded; a
failure stops no one. A job's counts go to the log.
"""

from __future__ import annotations

import asyncio
import contextvars
import math
import time
from collections.abc import Sequence
from typing import Literal, Protocol, runtime_checkable

from jarvis.logging import get_logger

log = get_logger(__name__)

MAX_BUDGET_S = 60.0
# All jobs together stay under the Scheduler's 180 s attempt deadline (R4 I2 F4); jobs the tick
# does not reach are reported failed (skipped) and logged, never silently dropped.
TICK_TOTAL_BUDGET_S = 150.0
# A job keeps one owner's failure from stopping the others and counts it under this key; any
# such count makes the job "failed" in the tick answer (R2 review M1).
FAILED_COUNT = "failed"
JobResult = Literal["ok", "failed"]
# R11 I1 (INTEGRATION-B 3.5): the monotonic time the running job must finish by (its budget, or
# what is left of the tick's); None outside `_run_one`. Nested runs (a composite's own jobs) set
# and reset it in turn, so each job reads its own.
_DEADLINE: contextvars.ContextVar[float | None] = contextvars.ContextVar(
    "tick_deadline", default=None
)


def time_left() -> float | None:
    """Seconds the running tick job has left, or None when no tick job is running."""
    at = _DEADLINE.get()
    return None if at is None else at - time.monotonic()


@runtime_checkable
class TickJob(Protocol):
    name: str
    budget_s: float

    async def run(self, owners: Sequence[str]) -> dict[str, int]: ...


def _budget(job: TickJob) -> float | None:
    b = job.budget_s
    if isinstance(b, bool) or not isinstance(b, int | float) or not math.isfinite(b) or b <= 0:
        return None
    return min(float(b), MAX_BUDGET_S)


async def _run_one(
    job: TickJob, name: str, owners: Sequence[str], remaining_s: float = MAX_BUDGET_S
) -> JobResult:
    budget = _budget(job)
    if budget is None:
        log.error("tick job has no usable time budget", extra={"job": name})
        return "failed"
    budget = min(budget, remaining_s)
    token = _DEADLINE.set(time.monotonic() + budget)
    try:
        async with asyncio.timeout(budget):
            counts = await job.run(owners)
    except TimeoutError:
        log.error("tick job timed out", extra={"job": name, "budget_s": budget})
        return "failed"
    except Exception as exc:  # noqa: BLE001 - a job never fails the tick
        log.error("tick job failed", extra={"job": name, "error": type(exc).__name__})
        return "failed"
    finally:
        _DEADLINE.reset(token)
    if not isinstance(counts, dict) or not all(
        isinstance(k, str) and isinstance(v, int) and not isinstance(v, bool)
        for k, v in counts.items()
    ):
        log.error("tick job answered in the wrong shape", extra={"job": name})
        return "failed"
    if counts.get(FAILED_COUNT, 0) > 0:  # review M1: owners it could not serve, never "ok"
        log.error("tick job failed for some owners", extra={"job": name, "counts": counts})
        return "failed"
    log.info("tick job done", extra={"job": name, "counts": counts})
    return "ok"


async def run_jobs(
    jobs: Sequence[TickJob] | None,
    owners: Sequence[str],
    *,
    total_budget_s: float = TICK_TOTAL_BUDGET_S,
) -> dict[str, JobResult]:
    """name -> "ok" | "failed" for each job, in order. Never raises. Each job gets at most what is
    left of `total_budget_s`; a job the tick has no time left for is reported failed (skipped)."""
    out: dict[str, JobResult] = {}
    deadline = time.monotonic() + total_budget_s
    for job in tuple(jobs or ()):
        name = getattr(job, "name", None)
        if not isinstance(name, str) or not name or not hasattr(job, "run"):
            log.error("tick job without a name or run: skipped")
            continue
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            log.error("tick job skipped: the tick is out of time", extra={"job": name})
            result: JobResult = "failed"
        else:
            result = await _run_one(job, name, owners, remaining)
        out[name] = "failed" if "failed" in (result, out.get(name)) else "ok"
    return out


__all__ = [
    "FAILED_COUNT",
    "MAX_BUDGET_S",
    "TICK_TOTAL_BUDGET_S",
    "JobResult",
    "TickJob",
    "run_jobs",
    "time_left",
]
