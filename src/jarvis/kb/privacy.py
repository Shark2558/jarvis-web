# src/jarvis/kb/privacy.py
"""Notes in the privacy dashboard (R2 D14): the `notes` category.

Counts come from the store's header (one read, no decryption); the revision is the header's, so a
delete quoting it is refused (409) when the data changed since the owner looked. Export is the
notes file the Notes panel offers; delete wipes every shard and the header (crypto and path both).
Registered by the integrator only when notes are on (a server without a token key has no notes and
no row to show).
"""

from __future__ import annotations

from typing import Any

from jarvis.kb.service import NotesService
from jarvis.privacy import CategoryView


class NotesPrivacy:
    id = "notes"
    section = "Notes and things"
    label = "Notes, memos and links"

    def __init__(self, svc: NotesService) -> None:
        self._svc = svc

    async def describe(self, uid: str) -> CategoryView:
        rev, counts = await self._svc.store.summary(uid)
        live = counts["note"] + counts["memo"] + counts["link"]
        gone = counts["deleted"]
        note = f"{gone} in Recently deleted go too." if gone else "Deleting cannot be undone."
        return CategoryView(
            id=self.id,
            section=self.section,
            label=self.label,
            what="Notes you typed, voice-memo transcripts, saved links and any page text you "
            "fetched for a link.",
            count=live,
            unit="items",
            retention="until you delete them; deleted ones stay 30 days in Recently deleted",
            where="Firestore (Mumbai), encrypted by JARVIS",
            encrypted_by_jarvis=True,
            export=True,
            delete="passkey",
            recoverable=False,
            note=note,
            rev=rev or "0",
        )

    async def export(self, uid: str) -> dict[str, Any] | None:
        data = await self._svc.export(uid)
        return data if data["notes"] else None

    async def delete(self, uid: str) -> int:
        return await self._svc.wipe(uid)


__all__ = ["NotesPrivacy"]
