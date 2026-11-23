# src/jarvis/buildbook/writer/job.py
"""R6.3 D5: `book_write`, the writer's resumable job on the existing clocks (the 5-minute clock,
last, Home on or off, and the morning tick after `book_sweep`). PART B builds it: the free work on
every run (the sweep, the free carry at a new release, `update_ready`, the storage check and its
notices) and brain calls ONLY inside an approved run, under the lease, when a call fits the time
left (H7). I0's stub does nothing and calls nothing.
"""

from __future__ import annotations

from collections.abc import Sequence

from jarvis.buildbook.writer.model import JOB_BUDGET_S, JOB_NAME
from jarvis.buildbook.writer.ports import WriterContext


class BookWriteJob:
    name = JOB_NAME
    budget_s = JOB_BUDGET_S

    def __init__(self, ctx: WriterContext) -> None:
        self._ctx = ctx

    async def run(self, owners: Sequence[str]) -> dict[str, int]:
        """I0's stub (part B replaces it): no run, so nothing to do."""
        return {}


__all__ = ["BookWriteJob"]
