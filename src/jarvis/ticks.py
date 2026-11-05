# src/jarvis/ticks.py
"""Tick jobs: housekeeping and daily work that rides the scheduler tick (R2 D5, D9).

A feature adds a `TickJob` (vault reminders, the DigiLocker inbox) to `app.state.tick_jobs`; the
tick (`api/brief.py`) calls `run_jobs` after its fixed sweeps. `run_jobs` never raises: a job that
fails, times out (`asyncio.timeout(budget_s)`, capped at `MAX_BUDGET_S`) or answers oddly is
logged (class name only) and reported "failed", the same words the sweeps use. Jobs run one after
another so the tick's CPU use stays bounded; a failure stops no one. A job's counts go to the log.
"""

from __future__ import annotations

import asyncio
import math
from collections.abc import Sequence
from typing import Literal, Protocol, runtime_checkable

from jarvis.logging import get_logger

log = get_logger(__name__)

MAX_BUDGET_S = 60.0
JobResult = Literal["ok", "failed"]


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


async def _run_one(job: TickJob, name: str, owners: Sequence[str]) -> JobResult:
    budget = _budget(job)
    if budget is None:
        log.error("tick job has no usable time budget", extra={"job": name})
        return "failed"
    try:
        async with asyncio.timeout(budget):
            counts = await job.run(owners)
    except TimeoutError:
        log.error("tick job timed out", extra={"job": name, "budget_s": budget})
        return "failed"
    except Exception as exc:  # noqa: BLE001 - a job never fails the tick
        log.error("tick job failed", extra={"job": name, "error": type(exc).__name__})
        return "failed"
    if not isinstance(counts, dict) or not all(
        isinstance(k, str) and isinstance(v, int) and not isinstance(v, bool)
        for k, v in counts.items()
    ):
        log.error("tick job answered in the wrong shape", extra={"job": name})
        return "failed"
    log.info("tick job done", extra={"job": name, "counts": counts})
    return "ok"


async def run_jobs(jobs: Sequence[TickJob] | None, owners: Sequence[str]) -> dict[str, JobResult]:
    """name -> "ok" | "failed" for each job, in order. Never raises."""
    out: dict[str, JobResult] = {}
    for job in tuple(jobs or ()):
        name = getattr(job, "name", None)
        if not isinstance(name, str) or not name or not hasattr(job, "run"):
            log.error("tick job without a name or run: skipped")
            continue
        result = await _run_one(job, name, owners)
        out[name] = "failed" if "failed" in (result, out.get(name)) else "ok"
    return out


__all__ = ["MAX_BUDGET_S", "JobResult", "TickJob", "run_jobs"]
