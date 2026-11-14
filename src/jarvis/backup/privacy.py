# src/jarvis/backup/privacy.py
"""The Privacy panel's "Backups" row (docs/plans/r14-hardening.md D3 "Privacy change", data
model): Part A's privacy source, server-sent through I0's `r14_privacy_sources` slot, so the
console is untouched. It says plainly that a deleted item leaves the live database at once and
Google's daily copies within 7 days. Nothing here can be exported or deleted from JARVIS: the
copies are Google's, in his own project (deleting them is a Google Cloud step, and a restore
drill or a real restore needs them). Counts only; no backup content is ever read here.
"""

from __future__ import annotations

import hashlib
from typing import Any

from jarvis.backup.status import RETENTION_DAYS, BackupStatusService
from jarvis.privacy.ports import CategoryView

SECTION = "Settings and safety"  # the dashboard's own section name (privacy/sources.py)
WHAT = (
    "Google's daily copies of all JARVIS's data, for a restore if something goes wrong. A thing "
    f"you delete leaves JARVIS at once and these copies within {RETENTION_DAYS} days."
)
KEPT = f"{RETENTION_DAYS} days, then Google deletes each copy"
WHERE = (
    "Google Cloud, your own project (Mumbai), encrypted by Google; your vault, notes and things "
    "stay sealed by JARVIS inside them"
)
NOT_SET_UP = "Not set up: no copies are kept."
SET_UP = "A monthly restore drill opens the newest copy in a throw-away database, then deletes it."


class BackupsPrivacy:
    id = "backups"
    section = SECTION
    label = "Backups (Google's copies)"

    def __init__(self, status: BackupStatusService) -> None:
        self._status = status

    async def describe(self, uid: str) -> CategoryView:
        doc = await self._status.doc()
        return CategoryView(
            id=self.id,
            section=self.section,
            label=self.label,
            what=WHAT,
            count=doc.copies,
            unit="copies",
            retention=KEPT,
            where=WHERE,
            note=SET_UP if doc.set_up else NOT_SET_UP,
            rev=hashlib.sha256(f"{doc.copies}:{doc.newest_name}".encode()).hexdigest()[:16],
        )

    async def export(self, uid: str) -> dict[str, Any] | None:
        return None

    async def delete(self, uid: str) -> int:
        return 0


__all__ = ["SECTION", "BackupsPrivacy"]
