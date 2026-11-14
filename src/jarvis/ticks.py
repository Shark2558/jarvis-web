# src/jarvis/ticks.py
"""Tick jobs: housekeeping and daily work that rides the scheduler tick (R2 D5, D9).

A feature adds a `TickJob` (vault reminders, the DigiLocker inbox) to `app.state.tick_jobs`; the
tick (`api/brief.py`) calls `run_jobs` after its fixed sweeps. `run_jobs` never raises: a job that
fails, times out (`asyncio.timeout(budget_s)`, capped at `MAX_BUDGET_S`) or answers oddly is
logged (class name only) and reported "failed", the same words the sweeps use. So is a job whose
counts carry `failed` > 0: jobs isolate owners (one owner's failure stops no one) and count the
owners they could not serve. Jobs run one after another so the tick's CPU use stays bounded; a
failure stops no one. A job's counts go to the log.

R14 I0 (docs/plans/r14-hardening.md D5, A6): `run_jobs` also hands each job's outcome to an
optional observer (`TickObserver`, Part B's self-health watch): `ok`, `failed`, `timed_out` or
`skipped` (the tick had no time left for it: never a failure of the job itself), with the clock
it ran on and its seconds. An observer that raises is logged and never stops a job.
"""

from __future__ import annotations

import asyncio
import contextvars
import math
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
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
Outcome = Literal["ok", "failed", "timed_out", "skipped"]
# R11 I1 (INTEGRATION-B 3.5): the monotonic time the running job must finish by (its budget, or
# what is left of the tick's); None outside `_outcome_of`. Nested runs (a composite's own jobs) set
# and reset it in turn, so each job reads its own.
_DEADLINE: contextvars.ContextVar[float | None] = contextvars.ContextVar(
    "tick_deadline", default=None
)


def time_left() -> float | None:
    """Seconds the running tick job has left, or None when no tick job is running."""
    at = _DEADLINE.get()
    return None if at is None else at - time.monotonic()


@dataclass(frozen=True)
class JobOutcome:
    clock: str  # "tick" (the morning tick) or "watchdog" (the 5-minute route, Home on or off)
    name: str
    outcome: Outcome
    seconds: float


TickObserver = Callable[[JobOutcome], None]


def report(observer: TickObserver | None, outcome: JobOutcome) -> None:
    """Hand one outcome to the observer; never raises."""
    if observer is None:
        return
    try:
        observer(outcome)
    except Exception as exc:  # noqa: BLE001 - watching a job never stops it
        log.error("tick observer failed", extra={"job": outcome.name, "error": type(exc).__name__})


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


async def _outcome_of(
    job: TickJob, name: str, owners: Sequence[str], remaining_s: float = MAX_BUDGET_S
) -> Outcome:
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
        return "timed_out"
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
    observer: TickObserver | None = None,
    clock: str = "tick",
) -> dict[str, JobResult]:
    """name -> "ok" | "failed" for each job, in order. Never raises. Each job gets at most what is
    left of `total_budget_s`; a job the tick has no time left for is reported failed (skipped),
    and the observer hears "skipped"."""
    out: dict[str, JobResult] = {}
    deadline = time.monotonic() + total_budget_s
    for job in tuple(jobs or ()):
        name = getattr(job, "name", None)
        if not isinstance(name, str) or not name or not hasattr(job, "run"):
            log.error("tick job without a name or run: skipped")
            continue
        started = time.monotonic()
        remaining = deadline - started
        if remaining <= 0:
            log.error("tick job skipped: the tick is out of time", extra={"job": name})
            outcome: Outcome = "skipped"
        else:
            outcome = await _outcome_of(job, name, owners, remaining)
        report(observer, JobOutcome(clock, name, outcome, max(0.0, time.monotonic() - started)))
        result: JobResult = "ok" if outcome == "ok" else "failed"
        out[name] = "failed" if "failed" in (result, out.get(name)) else "ok"
    return out


__all__ = [
    "FAILED_COUNT",
    "JobOutcome",
    "Outcome",
    "TickObserver",
    "report",
    "MAX_BUDGET_S",
    "TICK_TOTAL_BUDGET_S",
    "JobResult",
    "TickJob",
    "run_jobs",
    "time_left",
]
