# tests/test_r11_i1_ticks.py -- R11 I1, INTEGRATION-B 3.5: a job can read what is left of its time
# (`ticks.time_left()`): its own budget or what is left of the tick's, whichever is less, nested
# composites included; None outside a tick job, so a part stops starting work it can't finish.
from __future__ import annotations

from collections.abc import Sequence

from jarvis.ticks import run_jobs, time_left


class Probe:
    def __init__(self, name: str, budget_s: float) -> None:
        self.name, self.budget_s = name, budget_s
        self.seen: list[float | None] = []

    async def run(self, owners: Sequence[str]) -> dict[str, int]:
        self.seen.append(time_left())
        return {"done": 1}


class Nest:
    """A composite: its own jobs through run_jobs inside its budget (like helpers_clock)."""

    name, budget_s = "outer", 20.0

    def __init__(self, inner: Probe) -> None:
        self.inner = inner

    async def run(self, owners: Sequence[str]) -> dict[str, int]:
        await run_jobs([self.inner], owners, total_budget_s=5.0)
        return {"done": 1}


async def test_a_job_reads_its_own_budget_or_what_is_left_of_the_tick() -> None:
    assert time_left() is None
    own, capped = Probe("own", 8.0), Probe("capped", 50.0)
    await run_jobs([own, capped], ["u"], total_budget_s=30.0)
    left_own, left_capped = own.seen[0], capped.seen[0]
    assert left_own is not None and 7.0 < left_own <= 8.0
    assert left_capped is not None and 25.0 < left_capped <= 30.0
    assert time_left() is None


async def test_a_nested_job_sees_the_composites_share_and_the_outer_value_comes_back() -> None:
    inner = Probe("inner", 12.0)
    await run_jobs([Nest(inner)], ["u"], total_budget_s=60.0)
    got = inner.seen[0]
    assert got is not None and 4.0 < got <= 5.0
    assert time_left() is None


async def test_part_bs_outside_slots_never_run_past_the_jobs_real_time() -> None:
    from jarvis.helpers.house.fetch import MARGIN_S, SLOTS, OutsideClock

    seen: list[tuple[float, float]] = []

    class Feeds:
        name, budget_s = "disaster_poll", 2.0

        async def run(self, owners: Sequence[str]) -> dict[str, int]:
            slots = OutsideClock()
            seen.append(
                (slots.deadline("sachet") - slots.now(), slots.deadline("weather") - slots.now())
            )
            return {"done": 1}

    await run_jobs([Feeds()], ["u"], total_budget_s=60.0)
    sachet, weather = seen[0]
    assert sachet <= 2.0 - MARGIN_S + 0.01 and weather <= 2.0 - MARGIN_S + 0.01
    free = OutsideClock()  # outside a tick job: the slots alone
    assert abs(free.deadline("sachet") - free.now() - SLOTS["sachet"]) < 0.01
