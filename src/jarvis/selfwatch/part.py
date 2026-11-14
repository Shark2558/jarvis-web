# src/jarvis/selfwatch/part.py
"""R14 Part B (self-health): the part's one join with the app (`jarvis.hardening.ports`). I0's
stub: status "not built yet". Part B fills it: the 5-minute job `selfwatch_clock` (`clock_jobs`,
run first on both 5-minute paths), the daily `selfwatch_daily`, the Vitals item `clocks`, and the
services `tick_observer` and `log_handler` (installed once by the wiring).
"""

from __future__ import annotations

from jarvis.hardening.ports import HardeningContext, HardeningPart


def build(ctx: HardeningContext) -> HardeningPart:
    return HardeningPart("selfwatch")


__all__ = ["build"]
