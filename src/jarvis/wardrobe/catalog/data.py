# src/jarvis/wardrobe/catalog/data.py
"""The catalog's two data sources for D's Privacy rows (docs/plans/r13-wardrobe.md D20;
`ports.WardrobeData`): `pieces` (row "pieces": "Wardrobe pieces and places") and `photos` (row
"photos": "Wardrobe photos and fingerprints"; INTEGRATION-D 6.4).

`CatalogData` (name "pieces"):
- `count`: every piece record he keeps (archived and merged-away ones too: they hold his labels
  until they are purged). It raises when the index can't be opened; Privacy then asks `kept`.
- `kept`: how many documents are on disk for him, found with no key (existence and the plain
  `owner` field), so Privacy never says "Nothing kept yet" for sealed data it can't open.
- `export`: a plain JSON of his own records (pieces, pairs, sets, places, labels and each piece's
  history), WITHOUT photos or fingerprints (D17); Privacy scrubs it again on the way out.
- `delete`: everything the catalog keeps for him (the index, every log page, every photo and
  fingerprint, the purge count), by path and with no key: the photos', fingerprints' and logs'
  documents first, the index LAST, so a delete cut halfway leaves the index and a second delete
  finishes. A readable index also names its pages (pages written before `owner` existed).
"""

from __future__ import annotations

from typing import Any

from jarvis.wardrobe.catalog.photos import PhotoVault
from jarvis.wardrobe.catalog.store import CatalogStore
from jarvis.wardrobe.kept import PHOTOS_OWNED, PIECES_OWNED, PIECES_SINGLES, erase, kept_paths
from jarvis.wardrobe.ports import PrivacyRow


class CatalogData:
    name = "pieces"
    row: PrivacyRow = "pieces"

    def __init__(self, store: CatalogStore, vault: PhotoVault) -> None:
        self.store, self.vault = store, vault

    async def count(self, uid: str) -> int:
        return len((await self.store.view(uid)).pieces)

    async def export(self, uid: str) -> dict[str, Any]:
        view = await self.store.view(uid)
        drop = {"photos", "fp_model", "events"}
        pieces = [
            {k: v for k, v in p.model_dump(mode="json").items() if k not in drop}
            for p in view.pieces.values()
        ]
        history = {
            pid: [e.model_dump(mode="json") for e in await self.store.events(uid, pid, view=view)]
            for pid in view.pieces
        }
        return {
            "pieces": pieces,
            "pairs": [x.model_dump(mode="json") for x in view.pairs.values()],
            "sets": [x.model_dump(mode="json") for x in view.sets.values()],
            "places": [x.model_dump(mode="json") for x in view.places.values()],
            "labels": [x.model_dump(mode="json") for x in view.labels.values()],
            "history": history,
        }

    async def kept(self, uid: str) -> int:
        return len(await self._paths(uid))

    async def _paths(self, uid: str) -> list[str]:
        return await kept_paths(
            self.store.docs, self.store.prefix, uid, singles=PIECES_SINGLES, owned=PIECES_OWNED
        )

    async def delete(self, uid: str) -> int:
        paths = await self._paths(uid)
        index = self.store.index_path(uid)
        try:  # pages written before the plain owner field: named by a readable index
            view = await self.store.view(uid)
        except Exception:  # noqa: BLE001 - no key, or a changed key: the plain fields are enough
            view = None
        named: list[str] = []
        if view is not None:
            for p in view.pieces.values():
                named += [op.path for op in self.store.logs.drops(uid, p)]
        rest = [p for p in dict.fromkeys(named) if p not in paths]
        body = [p for p in paths if p != index]
        gone = await erase(self.store.docs, [*rest, *body, *([index] if index in paths else [])])
        return len(view.pieces) if view is not None else gone  # pieces, or documents when unread


class PhotoData:
    """The photos row: photos and fingerprints only, and the catalog stays usable (e2e 7). The
    export says how many, never a byte (D17: photos are never in an export)."""

    name = "photos"
    row: PrivacyRow = "photos"

    def __init__(self, vault: PhotoVault) -> None:
        self.vault = vault

    async def count(self, uid: str) -> int:
        return await self.vault.count(uid)

    async def export(self, uid: str) -> dict[str, Any]:
        return {"photos": await self.vault.count(uid)}

    async def kept(self, uid: str) -> int:
        return len(await self._paths(uid))

    async def _paths(self, uid: str) -> list[str]:
        store = self.vault.store
        return await kept_paths(store.docs, store.prefix, uid, owned=PHOTOS_OWNED)

    async def delete(self, uid: str) -> int:
        store = self.vault.store
        if await store.docs.get(store.index_path(uid)) is None:  # no index: don't make a new one
            return await erase(store.docs, await self._paths(uid))
        try:
            return await self.vault.delete_all(uid)
        except Exception:  # noqa: BLE001 - an index that can't be opened: erase them by path
            return await erase(self.vault.store.docs, await self._paths(uid))


__all__ = ["CatalogData", "PhotoData"]
