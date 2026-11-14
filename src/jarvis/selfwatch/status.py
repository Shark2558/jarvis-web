# src/jarvis/selfwatch/status.py
"""What the self-health watch shows (docs/plans/r14-hardening.md D5, data model): names, counts
and times only.

- `Status.view()`: the body of `GET /v1/selfwatch` (owner-only, `no-store`): the two clocks'
  last runs and open outages, the jobs in a streak (name, runs in a row, since, told), today's
  error count, the live revision and version as stored, this process's version.
- `ToldPrivacy`: the privacy row `selfwatch_told` (data model: listed, no export, no delete):
  how many self-health alerts were already sent to him (kind and time, 30 days), and the daily
  AI-spend totals the spend check compares. No message text is kept, so there is nothing more
  to export, and deleting the claims would only let an alert be sent twice.
"""

from __future__ import annotations

import hashlib
from datetime import datetime
from typing import TYPE_CHECKING, Any

from jarvis.logging import get_logger
from jarvis.privacy.ports import CategoryView
from jarvis.selfwatch.deploys import DeployWatch

if TYPE_CHECKING:
    from jarvis.selfwatch.jobs import Watch

log = get_logger(__name__)

READY = "on"
SEC_SAFETY = "Settings and safety"  # the dashboard's own section name (privacy/sources.py)
TOLD_WHAT = (
    "Which self-health alerts JARVIS already sent you (the kind and the time), so none is sent "
    "twice, and each day's AI spend so far this month, which the spend check compares."
)
TOLD_NOTE = "Kinds, times and rupee totals only: no message text is kept."


def _iso(at: datetime | None) -> str | None:
    return None if at is None else at.isoformat()


class Status:
    def __init__(self, watch: Watch) -> None:
        self._w = watch

    async def _errors_today(self, now: datetime) -> int | None:
        try:
            return await self._w.errors.today(self._w.docs, now)
        except Exception as exc:  # noqa: BLE001 - shown as unknown
            log.warning("selfwatch errors unreadable", extra={"error": type(exc).__name__})
            return None

    async def _deploy(self) -> dict[str, Any]:
        try:
            return await DeployWatch.current(self._w.docs, prefix=self._w.prefix)
        except Exception as exc:  # noqa: BLE001
            log.warning("selfwatch deploy unreadable", extra={"error": type(exc).__name__})
            return {}

    async def view(self) -> dict[str, Any]:
        w = self._w
        now = w.now()
        clocks = await w.clocks.read(w.docs)
        jobs = [
            {"name": n, "runs": s.runs, "since": _iso(s.since), "told": s.told_at is not None}
            for n, s in w.ledger.failing(1)
        ]
        return {
            "clocks": {
                "tick": _iso(clocks.tick),
                "watchdog": _iso(clocks.watchdog),
                "tick_outage": clocks.tick_outage is not None,
                "watchdog_outage": clocks.watchdog_outage is not None,
            },
            "jobs": jobs,
            "errors_today": await self._errors_today(now),
            "deploy": await self._deploy(),
            "version": w.version,
        }


class ToldPrivacy:
    id = "selfwatch_told"
    section = SEC_SAFETY
    label = "Self-health alerts sent"

    def __init__(self, watch: Watch) -> None:
        self._w = watch

    async def describe(self, uid: str) -> CategoryView:
        count = await self._w.told.count(uid)
        return CategoryView(
            id=self.id,
            section=self.section,
            label=self.label,
            what=TOLD_WHAT,
            count=count,
            unit="alerts",
            retention="30 days",
            where="Firestore",
            delete="none",
            note=TOLD_NOTE,
            rev=hashlib.sha256(f"{self.id}:{count}".encode()).hexdigest()[:16],
        )

    async def export(self, uid: str) -> dict[str, Any] | None:
        return None

    async def delete(self, uid: str) -> int:
        return 0


__all__ = ["READY", "Status", "ToldPrivacy"]
