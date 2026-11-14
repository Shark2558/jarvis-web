# src/jarvis/selfwatch/ports.py
"""Part B's ports (docs/plans/r14-hardening.md D5, A6), owned by I0.

- The tick observer: `jarvis.ticks` hands every job's outcome (`JobOutcome`: the clock, the job,
  `ok` | `failed` | `timed_out` | `skipped`, seconds) to the one observer the app holds
  (`app.state.tick_observer`, Part B's `services["tick_observer"]`). A skip for time never counts
  toward a streak; a selfwatch job never watches itself (the tick's `selfwatch_daily` watches the
  clock's `selfwatch_clock`, and the clock watches the tick's).
- `SENDING`: set while a selfwatch alert is being sent, so the errors handler can leave out the
  records `QUIET_LOGGERS` raise meanwhile (no alert about its own alert).
- `B_KINDS`: the kinds Part B raises; the backup kinds are Part A's alone.
"""

from __future__ import annotations

import contextvars
from typing import Final

from jarvis.ticks import JobOutcome, Outcome, TickObserver

SENDING: contextvars.ContextVar[bool] = contextvars.ContextVar("selfwatch_sending", default=False)
QUIET_LOGGERS: Final = ("jarvis.notify", "jarvis.telegram")
B_KINDS: Final = (
    "job_failing",
    "clock_stopped",
    "brief_missed",
    "errors_piling",
    "spend_spike",
    "deploy_changed",
    "selfwatch_ok",
)
CLOCKS: Final = ("tick", "watchdog")  # the two clocks a job's outcome comes from

__all__ = ["B_KINDS", "CLOCKS", "QUIET_LOGGERS", "SENDING", "JobOutcome", "Outcome", "TickObserver"]
