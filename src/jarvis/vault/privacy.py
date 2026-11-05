# src/jarvis/vault/privacy.py
"""The vault's row in the privacy dashboard (R2 D14): `PrivacySource` id `vault`.

Counts, export (metadata only: the files leave through Vault -> Export, which needs the unlock)
and delete (everything, crypto-shredded; a passkey class because nothing can bring it back).
`rev` fingerprints the index revision and counts, so a delete made after the data changed is
refused by the dashboard.
"""

from __future__ import annotations

import hashlib
from typing import Any

from jarvis.privacy.ports import CategoryView
from jarvis.vault.service import MB, VaultService


class VaultPrivacy:
    id = "vault"
    section = "Documents and notes"
    label = "Vault documents"

    def __init__(self, svc: VaultService) -> None:
        self._svc = svc

    async def describe(self, uid: str) -> CategoryView:
        rev, index = await self._svc.store.load(uid)
        live = index.live_items()
        per = [
            f"{index.holder_label(h)}: {sum(1 for i in live if i.holder_id == h)}"
            for h in dict.fromkeys(i.holder_id for i in live)
        ]
        mb = round(index.bytes_total() / MB, 1)
        fingerprint = hashlib.sha256(f"{rev}:{len(index.items)}:{len(index.holders)}".encode())
        return CategoryView(
            id=self.id,
            section=self.section,
            label=self.label,
            what="Document types, whose they are, the last 4 characters, dates, and the files.",
            count=len(index.items),
            unit="documents",
            size_hint=f"{mb} MB of {self._svc.limit_mb} MB",
            retention="Until you delete them. Deleted ones stay in Recently deleted for 30 days.",
            where="Firestore (Mumbai), encrypted by JARVIS",
            encrypted_by_jarvis=True,
            export=True,
            delete="passkey",
            recoverable=False,
            note="By person: " + ", ".join(per) if per else "Nothing is stored yet.",
            rev=fingerprint.hexdigest()[:16],
        )

    async def export(self, uid: str) -> dict[str, Any] | None:
        index = await self._svc.index(uid)
        documents = [
            {k: v for k, v in self._svc.item_view(index, i, self._svc.today()).items()
             if k not in ("files", "proposal", "id")}
            for i in index.live_items()
        ]  # fmt: skip
        return {
            "documents": documents,
            "note": "The files are not in this download. Use Vault -> Export for them.",
        }

    async def delete(self, uid: str) -> int:
        return await self._svc.wipe(uid)


__all__ = ["VaultPrivacy"]
