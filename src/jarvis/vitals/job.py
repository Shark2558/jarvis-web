# src/jarvis/vitals/job.py
"""The hourly Vitals poll as a tick job (R4 D14). No new Cloud Scheduler job: it rides the existing
tick (`jarvis.ticks`). The tick may call every minute, so the job keeps a last-poll time per owner
and skips an owner polled less than `POLL_EVERY_S` ago (the meter, FX and ledger reads are not
free). Alerts still fire only on an upward line-cross (`VitalsService.check_and_alert`). One
owner's trouble never stops the next; counts only. The throttle lives in memory: a restart simply
polls once early."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import UTC, datetime, timedelta

from jarvis.config import Settings
from jarvis.logging import get_logger
from jarvis.notify.ports import Notifier
from jarvis.vitals.service import VitalsService

log = get_logger(__name__)

JOB_NAME = "vitals_poll"
BUDGET_S = 30.0
POLL_EVERY_S = 3600


def _utcnow() -> datetime:
    return datetime.now(UTC)


class VitalsJob:
    name = JOB_NAME
    budget_s = BUDGET_S

    def __init__(
        self,
        service: VitalsService,
        notifier: Notifier,
        *,
        settings: Settings | None = None,
        clock: Callable[[], datetime] = _utcnow,
    ) -> None:
        self._svc = service
        self._notifier = notifier
        self._enabled = True if settings is None else settings.vitals_enabled
        self._clock = clock
        self._last: dict[str, datetime] = {}

    def _due(self, uid: str, now: datetime) -> bool:
        last = self._last.get(uid)
        return last is None or now - last >= timedelta(seconds=POLL_EVERY_S)

    async def run(self, owners: Sequence[str]) -> dict[str, int]:
        counts = {"owners": 0, "alerts": 0, "failed": 0}
        if not self._enabled:
            return counts
        for uid in owners:
            now = self._clock()
            if not self._due(uid, now):
                continue
            self._last[uid] = now  # on the attempt, so a failing owner isn't retried every minute
            try:
                counts["alerts"] += await self._svc.check_and_alert(uid, self._notifier)
            except Exception as exc:  # noqa: BLE001 - one owner never blocks another
                log.warning("vitals poll failed for an owner", extra={"error": type(exc).__name__})
                counts["failed"] += 1
                continue
            counts["owners"] += 1
        return counts


__all__ = ["BUDGET_S", "JOB_NAME", "POLL_EVERY_S", "VitalsJob"]
