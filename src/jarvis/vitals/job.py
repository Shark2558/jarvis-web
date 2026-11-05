# src/jarvis/vitals/job.py
"""The hourly Vitals poll as a tick job (R4 D14). No new Cloud Scheduler job: it rides the existing
tick (`jarvis.ticks`). The tick may call more often than hourly; alerts fire only on a line-cross
(`VitalsService.check_and_alert`), so frequency costs nothing but a few reads. One owner's trouble
never stops the next; counts only."""

from __future__ import annotations

from collections.abc import Sequence

from jarvis.config import Settings
from jarvis.logging import get_logger
from jarvis.notify.ports import Notifier
from jarvis.vitals.service import VitalsService

log = get_logger(__name__)

JOB_NAME = "vitals_poll"
BUDGET_S = 45.0


class VitalsJob:
    name = JOB_NAME
    budget_s = BUDGET_S

    def __init__(
        self, service: VitalsService, notifier: Notifier, *, settings: Settings | None = None
    ) -> None:
        self._svc = service
        self._notifier = notifier
        self._enabled = True if settings is None else settings.vitals_enabled

    async def run(self, owners: Sequence[str]) -> dict[str, int]:
        counts = {"owners": 0, "alerts": 0, "failed": 0}
        if not self._enabled:
            return counts
        for uid in owners:
            try:
                counts["alerts"] += await self._svc.check_and_alert(uid, self._notifier)
            except Exception as exc:  # noqa: BLE001 - one owner never blocks another
                log.warning("vitals poll failed for an owner", extra={"error": type(exc).__name__})
                counts["failed"] += 1
                continue
            counts["owners"] += 1
        return counts


__all__ = ["BUDGET_S", "JOB_NAME", "VitalsJob"]
