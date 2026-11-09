# tests/test_r51_int_watchdog.py -- R5.1 integrated fix (int-sec M4): the systems check riding the
# 5-minute home watchdog can never turn its HTTP answer into a 503. An unsaved report counts as
# degraded, a slow check ends before its tick budget, and the watchdog reports the health job as
# "degraded" (not "failed") whatever it did.
from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

from health_fakes import UID, Clock, fixed
from r51c_fakes import HomeStoreFake, home_status

from jarvis.api.home import home_watchdog
from jarvis.health import service as service_mod
from jarvis.health import tick as tick_mod
from jarvis.health.probes import PROBE_TIMEOUT_S
from jarvis.health.service import HealthService
from jarvis.health.store import HealthStore
from jarvis.health.tick import HealthTickJob
from jarvis.home.watchdog import OfflineJob, Watchdog
from jarvis.storage.docs import MemoryDocs
from jarvis.ticks import FAILED_COUNT


class DownStore(HealthStore):
    async def save(self, uid: str, state: Any) -> None:
        raise OSError("firestore down")


def test_the_numbers_nest_probe_then_check_then_job_then_tick_budget() -> None:
    assert PROBE_TIMEOUT_S == 5.0
    assert PROBE_TIMEOUT_S < service_mod.CHECK_DEADLINE_S == 20.0
    assert service_mod.CHECK_DEADLINE_S < tick_mod.TICK_DEADLINE_S == 25.0
    assert tick_mod.TICK_DEADLINE_S + 5.0 <= tick_mod.TICK_BUDGET_S == 30.0


async def test_an_unsaved_report_is_degraded_not_failed() -> None:
    svc = HealthService([fixed("a", "A", "ok")], DownStore(MemoryDocs()), clock=Clock())
    out = await HealthTickJob(svc, every_s=0).run([UID])
    assert out[FAILED_COUNT] == 0
    assert out["unsaved"] == 1


async def test_a_check_still_running_at_the_job_deadline_is_late_not_failed() -> None:
    class Slow(HealthService):
        async def check(self, uid: str, *, force: bool = False):  # type: ignore[no-untyped-def]
            await asyncio.sleep(5)

    svc = Slow([fixed("a", "A", "ok")], HealthStore(MemoryDocs()), clock=Clock())
    out = await HealthTickJob(svc, deadline_s=0.05, every_s=0).run([UID])
    assert out[FAILED_COUNT] == 0 and out["late"] == 1


def _watchdog(job: Any) -> Watchdog:
    store = HomeStoreFake(home_status())
    offline = OfflineJob(  # type: ignore[arg-type]
        store, None, None, clock=Clock(), offline_after_s=360.0
    )
    store.sweep_claims, store.sweep_codes = _zero, _zero  # type: ignore[attr-defined]
    store.linked_uids = _owners  # type: ignore[attr-defined]
    return Watchdog(store, offline, extra=(job,))  # type: ignore[arg-type]


async def _zero() -> int:
    return 0


async def _owners() -> list[str]:
    return [UID]


async def test_a_slow_health_job_cannot_fail_the_watchdog_answer() -> None:
    class Slow(HealthService):
        async def check(self, uid: str, *, force: bool = False):  # type: ignore[no-untyped-def]
            await asyncio.sleep(5)

    job = HealthTickJob(Slow([fixed("a", "A", "ok")], HealthStore(MemoryDocs())), every_s=0)
    job.budget_s = 0.05  # the tick's own cancel wins (the worst case: our deadline is skipped)
    dog = _watchdog(job)
    out = await dog.run()
    jobs = out["jobs"]
    assert isinstance(jobs, dict)
    assert jobs["health_check"] == "degraded" and jobs["home_offline"] == "ok"

    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(home_watchdog=dog)))
    answer = await home_watchdog(request)  # type: ignore[arg-type]
    assert isinstance(answer, dict)  # a dict, not a 503 JSONResponse


async def test_a_crashing_health_job_cannot_fail_the_watchdog_answer() -> None:
    class Boom:
        name = "health_check"
        budget_s = 5.0

        async def run(self, owners: Any) -> dict[str, int]:
            raise RuntimeError("boom")

    out = await _watchdog(Boom()).run()
    assert out["jobs"]["health_check"] == "degraded"  # type: ignore[index]


async def test_a_failing_laptop_job_still_fails_the_watchdog_answer() -> None:
    class Boom:
        name = "home_offline"
        budget_s = 5.0
        last: dict[str, int] = {}

        async def run(self, owners: Any) -> dict[str, int]:
            raise RuntimeError("boom")

    store = HomeStoreFake(home_status())
    store.sweep_claims, store.sweep_codes = _zero, _zero  # type: ignore[attr-defined]
    store.linked_uids = _owners  # type: ignore[attr-defined]
    dog = Watchdog(store, Boom())  # type: ignore[arg-type]
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(home_watchdog=dog)))
    answer = await home_watchdog(request)  # type: ignore[arg-type]
    assert getattr(answer, "status_code", 200) == 503
