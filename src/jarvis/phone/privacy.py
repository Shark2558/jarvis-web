# src/jarvis/phone/privacy.py
"""The `phones` row of the privacy dashboard (R7 D25; a `PrivacySource` registered through Part C's
`MobilePart.privacy`, so no privacy file is edited).

What is kept: each linked phone's public things (the key's public half, the app's package and
signing fingerprint, the model word, when it was linked and last seen, its app version and what
it said it may do), and the app lock's switch. Export: the phones without keys or fingerprints.
Delete is simple: it unlinks every phone (the door closes at once); linking again is five minutes.
"""

from __future__ import annotations

import hashlib
from typing import Any

from jarvis.phone.service import PhoneService, iso
from jarvis.privacy.ports import CategoryView

CATEGORY_ID = "phones"
SECTION = "Phone app"


class PhonePrivacy:
    id = CATEGORY_ID
    section = SECTION
    label = "Linked phones"

    def __init__(self, svc: PhoneService) -> None:
        self._svc = svc

    async def describe(self, uid: str) -> CategoryView:
        owner = await self._svc.store.owner(uid)
        ids = ",".join(sorted(p.id for p in owner.phones))
        return CategoryView(
            id=self.id,
            section=self.section,
            label=self.label,
            what=(
                "Each linked phone's public key, the app's signing fingerprint, the phone's model "
                "word, when it was linked and last seen, and what the app may do."
            ),
            count=len(owner.phones),
            unit="phone",
            retention="Until you unlink it",
            where="Firestore (public things only; the phone's key never leaves the phone)",
            export=bool(owner.phones),
            delete="simple" if owner.phones else "none",
            recoverable=True,
            note="Unlinking closes the phone's door at once. Link again from Integrations.",
            rev=hashlib.sha256(ids.encode()).hexdigest()[:16],
        )

    async def export(self, uid: str) -> dict[str, Any] | None:
        owner = await self._svc.store.owner(uid)
        return {
            "phones": [
                {
                    "id": p.id,
                    "model": p.model,
                    "linked_at": iso(p.linked_at),
                    "last_seen": iso(p.last_seen),
                    "app_version": p.app_version,
                    "can": dict(p.can),
                }
                for p in owner.phones
            ],
            "app_lock": {"on": owner.lock.on, "passkeys_from_the_app": len(owner.lock.keys)},
        }

    async def delete(self, uid: str) -> int:
        return await self._svc.unlink_all(uid)


__all__ = ["CATEGORY_ID", "PhonePrivacy"]
