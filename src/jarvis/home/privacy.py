# src/jarvis/home/privacy.py
"""The `home` category of the privacy dashboard (R3 D14). Registered by I1.

What is kept: the link (laptop address and keys, encrypted by JARVIS), the devices he exposed and
his labels (encrypted), the alarm state and camera labels (B's documents, not counted here).
Export: whether it is linked and which devices are shared, never an address or a key. Delete is
simple: unlinking (the bridge notices at its next heartbeat and stops sending). It is a link he can
make again, so no passkey.
"""

from __future__ import annotations

import hashlib
from typing import Any

from jarvis.home.store import HomeStore
from jarvis.privacy.ports import CategoryView

CATEGORY_ID = "home"
SECTION = "Home"


class HomePrivacy:
    id = CATEGORY_ID
    section = SECTION
    label = "Your home link"

    def __init__(self, store: HomeStore | None) -> None:
        self._store = store

    async def describe(self, uid: str) -> CategoryView:
        base: dict[str, Any] = {
            "id": self.id,
            "section": self.section,
            "label": self.label,
            "what": "The link to your home laptop, the devices you share and what you named them.",
            "unit": "link",
            "retention": "Until you unlink it",
            "where": "Firestore, encrypted by JARVIS",
        }
        if self._store is None:
            return CategoryView(
                **base, count=0, note="Not available on this server (no encryption key)."
            )
        status = await self._store.status(uid)
        devices = await self._store.load_devices(uid)
        linked = status is not None
        fingerprint = hashlib.sha256(
            f"{status.home_id if status else '-'}:{devices.rev}".encode()
        ).hexdigest()[:16]
        return CategoryView(
            **base,
            count=1 if linked else 0,
            encrypted_by_jarvis=True,
            export=True,
            delete="simple" if linked else "none",
            note="Video, pictures and your Home Assistant password never leave your laptop.",
            rev=fingerprint,
        )

    async def export(self, uid: str) -> dict[str, Any] | None:
        if self._store is None:
            return None
        status = await self._store.status(uid)
        devices = await self._store.load_devices(uid)
        return {
            "linked": status is not None,
            "linked_at": status.linked_at if status else None,
            "devices": [
                {"entity_id": e.entity_id, "label": e.label, "class": e.tier}
                for e in devices.entries
            ],
        }

    async def delete(self, uid: str) -> int:
        if self._store is None:
            return 0
        return 1 if await self._store.unlink(uid) else 0


__all__ = ["CATEGORY_ID", "SECTION", "HomePrivacy"]
