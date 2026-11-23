# src/jarvis/buildbook/writer/privacy.py
"""R6.3 D13: the Privacy row "Build book: writer" (the pages files with their count and MiB, trial
pages, drafts, the pick, the consents; the Rs ledger stays 13 months as numbers). PART B builds it
(its delete takes his passkey and stops any run); I0's stub counts nothing and deletes nothing.
"""

from __future__ import annotations

from typing import Any

from jarvis.buildbook.privacy import SEC_SAFETY
from jarvis.privacy.ports import CategoryView

ROW_ID = "book_writer"
LABEL = "Build book: writer"


class WriterSource:
    id = ROW_ID
    section = SEC_SAFETY
    label = LABEL

    async def describe(self, uid: str) -> CategoryView:
        return CategoryView(
            id=self.id,
            section=self.section,
            label=self.label,
            what="The build book's AI-written pages, trial pages and drafts, your writer choice "
            "and caps, and your typed YES records.",
            count=0,
            unit="pages",
            retention="Until you delete them; trial pages and drafts 30 days.",
            where="Firestore",
        )

    async def export(self, uid: str) -> dict[str, Any] | None:
        return None

    async def delete(self, uid: str) -> int:
        return 0


__all__ = ["LABEL", "ROW_ID", "WriterSource"]
