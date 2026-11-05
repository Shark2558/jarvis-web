# src/jarvis/belongings/privacy.py
"""Things in the privacy dashboard (R2 D14): the `belongings` category. Registered by I1 with
`PrivacyRegistry.register(BelongingsPrivacy(service))`. Counts live things only; the export is
the owner's own list with each history; a delete wipes the index and every history (it can't be
brought back: the dashboard asks for the passkey)."""

from __future__ import annotations

import hashlib
from typing import Any

from jarvis.belongings.service import BelongingsService
from jarvis.privacy.ports import CategoryView

CATEGORY_ID = "belongings"
SECTION = "Notes and things"


class BelongingsPrivacy:
    id = CATEGORY_ID
    section = SECTION
    label = "Where things are kept"

    def __init__(self, service: BelongingsService | None) -> None:
        self._svc = service

    async def describe(self, uid: str) -> CategoryView:
        base: dict[str, Any] = {
            "id": self.id,
            "section": self.section,
            "label": self.label,
            "what": (
                "Where you keep your passport, keys, gold and papers, and where each was before."
            ),
            "unit": "things",
            "retention": "Until you delete it",
            "where": "Firestore, encrypted by JARVIS",
        }
        if self._svc is None:
            return CategoryView(
                **base, count=0, note="Not available on this server (no encryption key)."
            )
        state = await self._svc.state(uid)
        live = state.live()
        fingerprint = hashlib.sha256(
            f"{state.rev}:{len(state.things)}:{len(live)}".encode()
        ).hexdigest()[:16]
        return CategoryView(
            **base,
            count=len(live),
            encrypted_by_jarvis=True,
            export=True,
            delete="passkey" if state.things else "none",
            recoverable=False,
            note="Deleted things stay in Recently deleted for 30 days unless removed there.",
            rev=fingerprint,
        )

    async def export(self, uid: str) -> dict[str, Any] | None:
        if self._svc is None:
            return None
        return await self._svc.export(uid)

    async def delete(self, uid: str) -> int:
        if self._svc is None:
            return 0
        return await self._svc.wipe(uid)


__all__ = ["CATEGORY_ID", "SECTION", "BelongingsPrivacy"]
