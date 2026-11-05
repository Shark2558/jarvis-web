# src/jarvis/vault_inbox/privacy.py
"""The DigiLocker import folder in the privacy dashboard (R2 D14, I1): the `vault_inbox` category.

What is kept: the Drive folder the owner picked, when it was last checked, how many files came in,
and per Drive file id whether it was imported or skipped (never a file name). Export is that
record; delete is `simple` (switching the import off: the owner can pick the folder again), and it
never touches Drive or the documents already in the vault.
"""

from __future__ import annotations

from typing import Any

from jarvis.privacy.sources import CallbackSource, Look, Spec
from jarvis.vault_inbox.service import InboxService

CATEGORY_ID = "vault_inbox"
SECTION = "Documents"


def inbox_source(svc: InboxService) -> CallbackSource:
    async def look(uid: str) -> Look:
        box = await svc.store.load(uid)
        if box is None:
            return Look(0, (), deletable=False, note="No folder is picked.")
        basis = (box.folder_id, box.imported_total, sorted(box.seen), box.last_check_at)
        return Look(1, basis)

    async def export(uid: str) -> dict[str, Any]:
        return await svc.export(uid) or {}

    async def delete(uid: str) -> int:
        if await svc.store.load(uid) is None:
            return 0
        await svc.clear(uid)
        return 1

    return CallbackSource(
        Spec(
            CATEGORY_ID,
            SECTION,
            "DigiLocker import folder",
            "The Drive folder you picked for DigiLocker import, and which of its files came in or "
            "were skipped (Drive ids only, never file names).",
            "folder",
            "Until you switch the import off.",
            "Firestore",
            delete="simple",
            note="Deleting switches the import off. Drive and your vault documents are untouched.",
        ),
        look,
        export,
        delete,
    )


__all__ = ["CATEGORY_ID", "inbox_source"]
