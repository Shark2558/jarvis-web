# src/jarvis/wardrobe/catalog/purges.py
"""How many pieces Recently deleted has purged for him (docs/plans/r13-wardrobe.md D16, D17;
review A-1 L2), a count only:

    {prefix}wardrobe_restore/{uid}   {v, kid, blob, updated_at}
        blob = AES-GCM({"purged": n}), purpose `wardrobe`, AAD `wardrobe/restore/{uid}/v1`

A restore token's MAC covers this count. A check made while his wardrobe was empty says "add
every piece" for its whole hour; once a purge has happened since, that token no longer matches
("check the file again"), so a replayed restore never brings back a piece he purged unticked.
The count is written in the purge's own commit (`purge_ops`, read through its `tx`).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from jarvis.storage.docs import Op, Set
from jarvis.wardrobe.catalog.sealed import VERSION, aad_restore, check_owner
from jarvis.wardrobe.catalog.store import CatalogStore

Get = Callable[[str], Awaitable[Any]]


class PurgeCount:
    def __init__(self, store: CatalogStore) -> None:
        self.store = store

    def path(self, uid: str) -> str:
        return f"{self.store.prefix}wardrobe_restore/{check_owner(uid)}"

    async def read(self, uid: str, get: Get | None = None) -> int:
        doc = await (get or self.store.docs.get)(self.path(uid))
        if doc is None:
            return 0
        if doc.get("v") != VERSION:
            raise ValueError("envelope")
        raw = self.store.sealer.open("wardrobe", aad_restore(uid), doc.get("blob"))
        return int(raw["purged"])

    async def purge_ops(self, uid: str, get: Get) -> list[Op]:
        """The write that counts one more purge (read first, through the purge's `tx`)."""
        n = await self.read(uid, get) + 1
        blob = self.store.sealer.seal("wardrobe", aad_restore(uid), {"purged": n})
        body = {"v": VERSION, "kid": self.store.sealer.kid, "blob": blob}
        return [Set(self.path(uid), {**body, "updated_at": self.store.now().isoformat()})]


__all__ = ["PurgeCount"]
