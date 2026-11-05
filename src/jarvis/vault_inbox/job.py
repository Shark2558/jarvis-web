# src/jarvis/vault_inbox/job.py
"""The DigiLocker import as a tick job (R2 D9). `InboxJob` rides the scheduler tick
(`app.state.tick_jobs`, `jarvis.ticks`): for each owner with a picked folder it runs
`InboxService.check`, which imports at most 3 files per run. An owner with no folder costs one
storage read and no Drive call. One owner's trouble never stops the next; counts only, no names.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence

from jarvis.logging import get_logger
from jarvis.vault_inbox.service import InboxService

log = get_logger(__name__)

JOB_NAME = "digilocker_inbox"  # not one of the tick's own sweep names


class InboxJob:
    name = JOB_NAME
    budget_s = 55.0

    def __init__(
        self,
        service: InboxService,
        *,
        allowed: Callable[[str], Awaitable[bool]] | None = None,
    ) -> None:
        """`allowed(uid)`: False while the owner's Drive row is Never (no import then)."""
        self._svc = service
        self._allowed = allowed

    async def run(self, owners: Sequence[str]) -> dict[str, int]:
        counts = {"owners": 0, "imported": 0, "skipped": 0, "failed": 0}
        for uid in owners:
            try:
                if self._allowed is not None and not await self._allowed(uid):
                    continue
                result = await self._svc.check(uid)
            except Exception as exc:  # noqa: BLE001 - one owner never blocks another
                log.warning("inbox job failed for an owner", extra={"error": type(exc).__name__})
                counts["failed"] += 1
                continue
            counts["owners"] += 1
            counts["imported"] += result.imported
            counts["skipped"] += result.skipped
        return counts


__all__ = ["JOB_NAME", "InboxJob"]
