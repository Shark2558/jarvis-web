# tests/test_r4_i2_tick_deadline.py -- R4 I2 F4: the tick has an aggregate deadline.
from __future__ import annotations

import asyncio
import time
from collections.abc import Sequence

from jarvis.health.tick import TICK_BUDGET_S as HEALTH_BUDGET_S
from jarvis.ticks import MAX_BUDGET_S, TICK_TOTAL_BUDGET_S, run_jobs
from jarvis.vitals.job import BUDGET_S as VITALS_BUDGET_S


class Slow:
    def __init__(self, name: str, sleep_s: float, budget_s: float = 60.0) -> None:
        self.name, self.budget_s, self._sleep = name, budget_s, sleep_s
        self.ran = False

    async def run(self, owners: Sequence[str]) -> dict[str, int]:
        self.ran = True
        await asyncio.sleep(self._sleep)
        return {"done": 1}


def test_the_total_is_under_the_schedulers_attempt_deadline() -> None:
    assert TICK_TOTAL_BUDGET_S == 150.0 < 180.0
    assert VITALS_BUDGET_S <= 30.0 and HEALTH_BUDGET_S <= 30.0
    assert MAX_BUDGET_S >= 30.0


async def test_a_slow_early_job_does_not_push_the_tick_past_the_total() -> None:
    first, second, third = Slow("a", 5.0), Slow("b", 5.0), Slow("c", 0.0)
    t0 = time.monotonic()

    out = await run_jobs([first, second, third], ["u"], total_budget_s=0.3)

    assert time.monotonic() - t0 < 1.5
    assert out["a"] == "failed"  # cut at the remaining budget
    assert out["b"] == "failed" and not second.ran  # not reached: skipped
    assert out["c"] == "failed" and not third.ran


async def test_jobs_inside_the_total_run_normally() -> None:
    a, b = Slow("a", 0.0), Slow("b", 0.0)

    out = await run_jobs([a, b], ["u"], total_budget_s=5.0)

    assert out == {"a": "ok", "b": "ok"}
