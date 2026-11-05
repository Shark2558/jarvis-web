# src/jarvis/faces/privacy.py
"""Faces in the privacy dashboard (R3 D14): replaces the `faces` placeholder
(`privacy/sources.faces_source`). Registered by I1 with
`PrivacyRegistry.register(FacesPrivacy(svc))` in the placeholder's place (section "Faces", last).

Counts people whose names JARVIS still holds (a person being deleted is not counted: the name
mapping died at once). The export is the consent records, no pictures (there are none in the
cloud). A delete of the category (passkey, target `faces:<rev>`) starts every person deleting; the
laptop deletes the pictures on its next check-in. A single person is deleted from the Faces
panel (passkey, purpose `privacy_delete`, target `face:<id>`).
"""

from __future__ import annotations

import hashlib
from typing import Any

from jarvis.faces.service import FacesService
from jarvis.privacy.ports import CategoryView

CATEGORY_ID = "faces"
SECTION = "Faces"


class FacesPrivacy:
    id = CATEGORY_ID
    section = SECTION
    label = "People JARVIS recognises"

    def __init__(self, service: FacesService | None) -> None:
        self._svc = service

    async def describe(self, uid: str) -> CategoryView:
        base: dict[str, Any] = {
            "id": self.id,
            "section": self.section,
            "label": self.label,
            "what": "Names, relation and consent records of people you added. Face pictures "
            "are only on your laptop.",
            "unit": "people",
            "retention": "Until deleted (JARVIS asks once a year if it is still OK)",
            "where": "Firestore, encrypted by JARVIS; pictures only on your laptop",
        }
        if self._svc is None:
            return CategoryView(
                **base, count=0, note="Not available on this server (no encryption key)."
            )
        state = await self._svc.state(uid)
        live, going = state.live(), state.deleting()
        fingerprint = hashlib.sha256(f"{state.rev}:{len(live)}:{len(going)}".encode()).hexdigest()[
            :16
        ]
        note = "Deleting wipes the name here now; the pictures on your laptop go when it checks in."
        if going:
            note = f"{len(going)} being deleted on your laptop when it is back."
        return CategoryView(
            **base,
            count=len(live),
            encrypted_by_jarvis=True,
            export=True,
            delete="passkey" if live else "none",
            recoverable=False,
            note=note,
            rev=fingerprint,
        )

    async def export(self, uid: str) -> dict[str, Any] | None:
        return None if self._svc is None else await self._svc.export(uid)

    async def delete(self, uid: str) -> int:
        if self._svc is None:
            return 0
        return await self._svc.remove_all(uid)  # the dashboard writes the audit entry


__all__ = ["CATEGORY_ID", "SECTION", "FacesPrivacy"]
