# src/jarvis/buildbook/writer/privacy.py
"""R6.3 D13: the Privacy row "Build book: writer" (id `book_writer`, Settings and safety): the AI
pages files (their count and MiB), trial pages, drafts, the pick and the consents. Export: ids,
counts, MiB and his choices (never page text). Delete takes his passkey (`passkey`): it stops any
run first, then removes the pages files (crypto-shred), trial pages, drafts and the writer's
document; the rupee ledger stays 13 months as numbers (like `tryon_spend`). Writing the pages
again is a new first write with its own YES (D12).
"""

from __future__ import annotations

import hashlib
from typing import Any

from jarvis.buildbook.model import MIB
from jarvis.buildbook.privacy import SEC_SAFETY
from jarvis.buildbook.writer.model import DRAFTS, TRIAL, WRITER
from jarvis.logging import get_logger
from jarvis.privacy.ports import CategoryView
from jarvis.storage.docs import Delete

log = get_logger(__name__)
ROW_ID = "book_writer"
LABEL = "Build book: writer"
WHAT = (
    "The build book's AI-written pages, trial pages and drafts, your writer choice and caps, and "
    "your typed YES records."
)
KEPT = "Until you delete them; trial pages and drafts 30 days. The rupee ledger stays 13 months."
WHERE = "Firestore, encrypted by JARVIS"


class WriterSource:
    id = ROW_ID
    section = SEC_SAFETY
    label = LABEL

    def __init__(
        self, ctx: Any = None, store: Any = None, vault: Any = None, service: Any = None
    ) -> None:
        self._ctx, self._store, self._vault, self._service = ctx, store, vault, service

    async def _counts(self, uid: str) -> tuple[int, int, int, int]:
        """(pages written in the pages files, their bytes, trial pages, drafts)."""
        if self._store is None:
            return 0, 0, 0, 0
        ix = await self._vault.index(uid)
        trials = len(await self._store.trials(uid))
        drafts = len(await self._store._mine(DRAFTS, uid, f"{uid}_"))
        return sum(f.written for f in ix.files), sum(f.size for f in ix.files), trials, drafts

    async def describe(self, uid: str) -> CategoryView:
        written, size, trials, drafts = await self._counts(uid)
        count = written + trials + drafts
        rev = hashlib.sha256(f"{written}:{size}:{trials}:{drafts}".encode()).hexdigest()[:16]
        return CategoryView(
            id=self.id, section=self.section, label=self.label, what=WHAT, count=count,
            unit="pages", retention=KEPT, where=WHERE,
            size_hint=f"{size / MIB:.1f} MiB" if size else None, encrypted_by_jarvis=True,
            export=True, delete="passkey", rev=rev,
        )  # fmt: skip

    async def export(self, uid: str) -> dict[str, Any] | None:
        if self._store is None:
            return None
        doc = await self._store.doc(uid)
        ix = await self._vault.index(uid)
        files = [
            {"release": f.release, "sealed_at": f.sealed_at, "written": f.written,
             "changed": f.changed, "skipped": f.skipped, "mib": round(f.size / MIB, 2)}
            for f in ix.files
        ]  # fmt: skip
        _, _, trials, drafts = await self._counts(uid)
        return {
            "pick": doc.pick.model_dump(mode="json"),
            "consents": {k: v.model_dump(mode="json") for k, v in doc.consents.items()},
            "pages_files": files,
            "trial_pages": trials,
            "drafts": drafts,
        }

    async def delete(self, uid: str) -> int:
        """Stops any run, then removes everything but the rupee ledger (13 months)."""
        if self._store is None:
            return 0
        if self._service is not None:
            await self._service.stop(uid)
        count = await self._vault.delete_all(uid)
        count += await self._store.drop(TRIAL, uid)
        count += await self._store.drop(DRAFTS, uid)
        await self._store.docs.write([Delete(self._store.path(WRITER, uid))])
        log.info("book writer data deleted", extra={"count": count})
        return count


__all__ = ["LABEL", "ROW_ID", "WriterSource"]
