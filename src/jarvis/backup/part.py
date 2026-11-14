# src/jarvis/backup/part.py
"""R14 Part A (backups and the restore drill): the part's one join with the app
(`jarvis.hardening.ports`). I0's stub: no tools, no jobs, status "not built yet". Part A fills
it: tools `vitals_backups` (R1) and `vitals_drill_start` (R2, a card, `bulk_ok=False`), daily
jobs `backup_canary` and `backup_drill`, Vitals items `backups`, `backup_drill`, `db_size`, the
"Backups" privacy row, and the service `backup_status` (`backup.ports.BackupStatus`).
"""

from __future__ import annotations

from jarvis.hardening.ports import HardeningContext, HardeningPart


def build(ctx: HardeningContext) -> HardeningPart:
    return HardeningPart("backup")


__all__ = ["build"]
