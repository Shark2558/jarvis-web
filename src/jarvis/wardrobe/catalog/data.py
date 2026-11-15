# src/jarvis/wardrobe/catalog/data.py
"""The catalog's data for D's Privacy rows (docs/plans/r13-wardrobe.md D20; `ports.WardrobeData`):
"Wardrobe pieces and places" and "Wardrobe photos and fingerprints".

- `count`: the pieces he owns (archived and merged-away records are not counted).
- `export`: a plain JSON of his own records (pieces, pairs, sets, places, labels and each piece's
  history), WITHOUT photos or fingerprints (D17); Privacy scrubs it again on the way out.
- `delete`: everything the catalog keeps for him (the index, every log page, every photo and
  fingerprint): the photos' and fingerprints' documents and the logs first, the index LAST, so a
  delete cut halfway leaves a readable index that a second delete finishes.
"""

from __future__ import annotations

from typing import Any

from jarvis.storage.docs import Delete, Op
from jarvis.wardrobe.catalog.photos import MAX_SHARDS, PhotoVault
from jarvis.wardrobe.catalog.store import CatalogStore


class CatalogData:
    name = "catalog"

    def __init__(self, store: CatalogStore, vault: PhotoVault) -> None:
        self.store, self.vault = store, vault

    async def count(self, uid: str) -> int:
        return len((await self.store.view(uid)).active())

    async def export(self, uid: str) -> dict[str, Any]:
        view = await self.store.view(uid)
        drop = {"photos", "fp_model", "events"}
        pieces = [
            {k: v for k, v in p.model_dump(mode="json").items() if k not in drop}
            for p in view.pieces.values()
        ]
        history = {
            pid: [e.model_dump(mode="json") for e in await self.store.events(uid, pid)]
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

    async def delete(self, uid: str) -> int:
        view = await self.store.view(uid)
        ops: list[Op] = []
        for p in view.pieces.values():
            ops += self.store.logs.drops(uid, p)
            ops += [Delete(self.vault.path(uid, ph)) for ph in p.photos]
        ops += [Delete(self.vault.prints.path(uid, s)) for s in range(MAX_SHARDS)]
        ops.append(Delete(self.store.index_path(uid)))
        await self.store.docs.write(ops)
        return len(view.pieces)


__all__ = ["CatalogData"]
