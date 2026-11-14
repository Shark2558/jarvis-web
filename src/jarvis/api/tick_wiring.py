# src/jarvis/api/tick_wiring.py
"""The tick's jobs and the one 5-minute clock (moved out of `api/app.py` at R14 I0, which had no
line to spare; docs/plans/r14-hardening.md D7, seam 7).

- `tick_jobs(app)`: R2's jobs, the alert policy's, R4's vitals and health check, R6's book jobs,
  R11's helpers clock and daily jobs, R7's own two, R14's daily jobs (the existing morning tick,
  no new Scheduler job).
- `add_clock_job(app, job)`: the 5-minute advisory jobs (the systems check, the helpers' clock,
  R7's clock) register here instead of on the home watchdog, so they also run with Home off.
- `clock_jobs(app)` / `install_clocks(app)`: `app.state.clock_jobs`, built once: R14's 5-minute
  jobs FIRST (`selfwatch_clock`), then the registered ones, each run for the brief's owners
  (`BriefService.owners`, read late) whatever owners the caller passes. With Home on, the watchdog
  runs the R14 jobs before its own laptop check and the rest after it; with Home off the
  5-minute route runs the same list (`api/home.py`).
- `finish_wiring(app)`: the last step of the lifespan: the tick jobs, the clocks, the brain's R14
  slots.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any

from fastapi import FastAPI

import jarvis.api.r7_wiring as r7
import jarvis.api.r14_wiring as r14
from jarvis.api.home_wiring import check_job_names, notify_tick_jobs
from jarvis.api.personal import personal_tick_jobs
from jarvis.api.r4_wiring import r4_tick_jobs
from jarvis.api.r6_wiring import r6_tick_jobs
from jarvis.api.r11_wiring import r11_tick_jobs
from jarvis.ticks import TickJob


def tick_jobs(app: FastAPI) -> tuple[Any, ...]:
    """Every morning-tick job, in this order; the names are unique and never a sweep's."""
    jobs = (
        *personal_tick_jobs(app),
        *notify_tick_jobs(app),
        *r4_tick_jobs(app),
        *r6_tick_jobs(app),
        *r11_tick_jobs(app),
        *r7.mobile_tick_jobs(app),
        *r14.r14_tick_jobs(app),
    )
    check_job_names(jobs)
    return jobs


class ForOwners:
    """A 5-minute job run for the brief's owners (A7): the caller's owner list (the watchdog's
    linked laptops, or none with Home off) is replaced by `owners()`, read at each run."""

    def __init__(self, job: TickJob, owners: Callable[[], Sequence[str]]) -> None:
        self.job, self._owners = job, owners
        self.name, self.budget_s = job.name, job.budget_s

    async def run(self, owners: Sequence[str]) -> dict[str, int]:
        return await self.job.run(tuple(self._owners()))


def add_clock_job(app: FastAPI, job: TickJob) -> None:
    """Register a 5-minute advisory job once (a second one with the same name is ignored)."""
    added: list[TickJob] = getattr(app.state, "clock_jobs_added", None) or []
    if all(j.name != job.name for j in added):
        added.append(job)
    app.state.clock_jobs_added = added


def _brief_owners(app: FastAPI) -> Callable[[], tuple[str, ...]]:
    def owners() -> tuple[str, ...]:
        brief = getattr(app.state, "brief", None)
        return tuple(getattr(brief, "owners", ()) or ())

    return owners


def clock_jobs(app: FastAPI) -> tuple[ForOwners, ...]:
    """R14's 5-minute jobs first, then the registered ones; built once."""
    built: tuple[ForOwners, ...] | None = getattr(app.state, "clock_jobs", None)
    if built is not None:
        return built
    owners = _brief_owners(app)
    added = tuple(getattr(app.state, "clock_jobs_added", None) or ())
    jobs = tuple(ForOwners(j, owners) for j in (*r14.r14_clock_jobs(app), *added))
    names = [j.name for j in jobs]
    if len(set(names)) != len(names):
        raise RuntimeError(f"the 5-minute clock jobs must have unique names: {names}")
    app.state.clock_jobs = jobs
    return jobs


def install_clocks(app: FastAPI) -> None:
    """`app.state.clock_jobs`, and the same jobs on the home watchdog when Home is on."""
    jobs = clock_jobs(app)
    first = len(r14.r14_clock_jobs(app))
    watchdog = getattr(app.state, "home_watchdog", None)
    if watchdog is None:
        return
    watchdog.observer = getattr(app.state, "tick_observer", None)
    for job in jobs[:first]:
        watchdog.prepend(job)
    for job in jobs[first:]:
        watchdog.extend(job)


def finish_wiring(app: FastAPI) -> None:
    """R2 + R3 H3: the tick jobs (run after the tick's sweeps); R14 D7: the one 5-minute clock;
    R14 seam 7: Part C's offer and ledger in the brain's two slots."""
    app.state.tick_jobs = tick_jobs(app)
    install_clocks(app)
    r14.bind_brain(app)


__all__ = [
    "ForOwners",
    "add_clock_job",
    "clock_jobs",
    "finish_wiring",
    "install_clocks",
    "tick_jobs",
]
