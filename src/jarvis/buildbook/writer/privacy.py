# src/jarvis/buildbook/writer/privacy.py
"""R6.3.1 D9 (docs/plans/r6-3-1-book-at-build.md): the Privacy row "Book writer (old trial)" (id
`book_writer`, Settings and safety). The runtime writer is gone (D8), but what its trial of 24 Nov
2026 stored stays until the owner deletes it; nothing deletes it by itself:

    {prefix}book_writer/{uid}               his writer pick, caps, YES records and the run
    {prefix}book_write_lease/{uid}          the run's lease
    {prefix}book_write_spend/{uid}_{month}  the writer's rupee ledger (numbers only)
    {prefix}book_drafts/{uid}_{rid}_{page}  drafts (their text sealed)
    {prefix}book_trial/{uid}_{nn}           trial pages (their text sealed)
    {prefix}book_pages/{uid}                the AI pages' own sealed index, chunks under it

Documents only: no keyring, nothing is opened. The count is the records found (the chunks of the
pages index are part of its record). Export: the count per kind and his pick and YES records as
stored (ids, numbers and choices; never page text). Delete (his passkey, the Privacy panel's
rule) removes every one of them, the chunks first. The row leaves the Privacy list once nothing
is left (`only_while_kept`); a row that can't be checked still shows.
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from typing import Any

from jarvis.buildbook.privacy import SEC_SAFETY
from jarvis.buildbook.seal_chunks import BookChunks
from jarvis.buildbook.writer.model import DRAFTS, LEASE, PAGES_INDEX, SPEND, TRIAL, WRITER
from jarvis.logging import get_logger
from jarvis.privacy.ports import CategoryView
from jarvis.storage.docs import Delete, Docs, Query

log = get_logger(__name__)
ROW_ID = "book_writer"
LABEL = "Book writer (old trial)"
WHAT = (
    "What the Book's old writer trial kept: your writer choice, caps and typed YES records, its "
    "run and rupee records, trial pages, drafts and the AI pages it sealed. JARVIS no longer "
    "writes the Book itself; the Workshop writes it while it builds JARVIS."
)
KEPT = "Until you delete it. Nothing new is added."
WHERE = "Firestore (page text encrypted by JARVIS)"
OWNED = (WRITER, LEASE, SPEND, DRAFTS, TRIAL)  # documents with an `owner` field
DELETE_GROUP = 200
KINDS = (*OWNED, PAGES_INDEX)


class OldWriterSource:
    id = ROW_ID
    section = SEC_SAFETY
    label = LABEL
    only_while_kept = True  # privacy.ports: listed only while it holds something

    def __init__(self, docs: Docs, *, prefix: str) -> None:
        self._docs, self._prefix = docs, prefix
        self._chunks = BookChunks(docs, f"{prefix}{PAGES_INDEX}")

    def _index_path(self, uid: str) -> str:
        return f"{self._prefix}{PAGES_INDEX}/{uid}"

    async def _found(self, uid: str) -> dict[str, list[str]]:
        """Kind -> the paths of his records of that kind (the pages index: itself, or a stand-in
        while only its chunks are left)."""
        out: dict[str, list[str]] = {}
        for col in OWNED:
            rows = await self._docs.query(Query(f"{self._prefix}{col}", where=("owner", uid)))
            out[col] = sorted(f"{self._prefix}{col}/{doc_id}" for doc_id, _ in rows)
        index = await self._docs.get(self._index_path(uid))
        chunks = await self._docs.query(Query(self._chunks.collection(uid), limit=1))
        out[PAGES_INDEX] = [self._index_path(uid)] if index is not None or chunks else []
        return out

    async def describe(self, uid: str) -> CategoryView:
        found = await self._found(uid)
        paths = sorted(p for kind in KINDS for p in found[kind])
        rev = hashlib.sha256("\n".join(paths).encode()).hexdigest()[:16]
        return CategoryView(
            id=self.id, section=self.section, label=self.label, what=WHAT, count=len(paths),
            unit="records", retention=KEPT, where=WHERE, encrypted_by_jarvis=True,
            export=True, delete="passkey", rev=rev,
        )  # fmt: skip

    async def export(self, uid: str) -> dict[str, Any] | None:
        found = await self._found(uid)
        if not any(found.values()):
            return None
        doc = await self._docs.get(f"{self._prefix}{WRITER}/{uid}") or {}
        return {
            "records": {kind: len(found[kind]) for kind in KINDS},
            "pick": doc.get("pick"),
            "consents": doc.get("consents"),
        }

    async def _delete(self, paths: Sequence[str]) -> None:
        for start in range(0, len(paths), DELETE_GROUP):
            await self._docs.write([Delete(p) for p in paths[start : start + DELETE_GROUP]])

    async def delete(self, uid: str) -> int:
        """Every record of the old writer: the pages index's chunks first, then the rest."""
        found = await self._found(uid)
        await self._chunks.drop_listed(uid)
        paths = [p for kind in KINDS for p in found[kind]]
        await self._delete(paths)
        log.info("old book writer data deleted", extra={"count": len(paths)})
        return len(paths)


__all__ = ["LABEL", "ROW_ID", "OldWriterSource"]
