# src/jarvis/health/tick.py
"""The scheduled health check as a TickJob (R4 D14). Rides the existing tick: no new Cloud
Scheduler job. One owner's failure is counted under `failed` and stops no one."""

from __future__ import annotations

from collections.abc import Sequence

from jarvis.health.service import HealthService
from jarvis.logging import get_logger
from jarvis.ticks import FAILED_COUNT

log = get_logger(__name__)

TICK_BUDGET_S = 45.0


class HealthTickJob:
    name = "health_check"
    budget_s = TICK_BUDGET_S

    def __init__(self, svc: HealthService) -> None:
        self._svc = svc

    async def run(self, owners: Sequence[str]) -> dict[str, int]:
        counts = {"owners": 0, "faults": 0, FAILED_COUNT: 0}
        for uid in owners:
            counts["owners"] += 1
            try:
                report = await self._svc.check(uid)
            except Exception as exc:  # noqa: BLE001 - one owner never stops the others
                log.error("health check failed for an owner", extra={"error": type(exc).__name__})
                counts[FAILED_COUNT] += 1
                continue
            if report.overall != "ok":
                counts["faults"] += 1
        return counts


__all__ = ["TICK_BUDGET_S", "HealthTickJob"]
