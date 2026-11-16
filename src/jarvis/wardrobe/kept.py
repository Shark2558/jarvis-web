# src/jarvis/wardrobe/kept.py
"""What the wardrobe keeps on disk, found WITHOUT a key (I1 fixer, the security review's M1).

Privacy must never say "Nothing kept yet" for sealed documents it can't open (no keyring, a failed
setup, a changed key), and delete must still erase them: a sealed document needs no key to go.
So the catalog's and the outfits' data find their documents by existence and by their plain owner
field, and `KeptData` stands in for a part that could not be built.

- `kept_paths(docs, prefix, uid, singles=, owned=)`: the paths that exist for him. `owned` are
  collections whose documents carry the owner's id in a plain field (`wardrobe_log`,
  `wardrobe_photo`, `wardrobe_fp`), found by one equality query; `singles` are `{collection}/{uid}`
  documents. The `owned` ones come first and the `singles` in the order given, so a delete cut
  halfway leaves the index (the last single) and a second delete finishes.
- `erase(docs, paths)`: delete them.
- `KeptData`: a `WardrobeData` for a part that is off or failed: `kept` says what is there,
  `count` and `export` say "Couldn't check right now" (they raise `WardrobeUnavailable`) while
  anything is kept, and `delete` erases it all.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from jarvis.storage.docs import Delete, Docs, Query
from jarvis.wardrobe.ports import PrivacyRow

OWNER_FIELD = "owner"


class WardrobeUnavailable(RuntimeError):
    """The data is kept but can't be opened right now: Privacy says "Couldn't check right now"."""


async def kept_paths(
    docs: Docs,
    prefix: str,
    uid: str,
    *,
    singles: Sequence[str] = (),
    owned: Sequence[tuple[str, str]] = (),
) -> list[str]:
    """Every document that exists for `uid`: `owned` (collection, field) pairs, then `singles`."""
    found: list[str] = []
    for collection, field in owned:
        rows = await docs.query(Query(f"{prefix}{collection}", where=(field, uid)))
        found += [f"{prefix}{collection}/{doc_id}" for doc_id, _ in rows]
    for collection in singles:
        path = f"{prefix}{collection}/{uid}"
        if await docs.get(path) is not None:
            found.append(path)
    return found


async def erase(docs: Docs, paths: Sequence[str]) -> int:
    if paths:
        await docs.write([Delete(p) for p in paths])
    return len(paths)


class KeptData:
    """A part that is off or failed still answers for what it left on disk."""

    def __init__(
        self,
        docs: Docs,
        prefix: str,
        *,
        name: str,
        row: PrivacyRow,
        singles: Sequence[str] = (),
        owned: Sequence[tuple[str, str]] = (),
    ) -> None:
        self._docs, self._prefix = docs, prefix
        self.name, self.row = name, row
        self._singles, self._owned = tuple(singles), tuple(owned)

    async def _paths(self, uid: str) -> list[str]:
        return await kept_paths(
            self._docs, self._prefix, uid, singles=self._singles, owned=self._owned
        )

    async def kept(self, uid: str) -> int:
        return len(await self._paths(uid))

    async def count(self, uid: str) -> int:
        if await self._paths(uid):
            raise WardrobeUnavailable(self.name)
        return 0

    async def export(self, uid: str) -> dict[str, Any]:
        await self.count(uid)
        return {}

    async def delete(self, uid: str) -> int:
        return await erase(self._docs, await self._paths(uid))


PIECES_SINGLES = ("wardrobe_restore", "wardrobe")  # the index LAST
PIECES_OWNED = (
    ("wardrobe_log", OWNER_FIELD),
    ("wardrobe_photo", OWNER_FIELD),
    ("wardrobe_fp", OWNER_FIELD),
)
PHOTOS_OWNED = (("wardrobe_photo", OWNER_FIELD), ("wardrobe_fp", OWNER_FIELD))
PLANS_SINGLES = ("wardrobe_plans", "wardrobe_cal", "wardrobe_outlook")


def stand_ins(part: str, docs: Docs, prefix: str) -> tuple[KeptData, ...]:
    """The `KeptData` for a part that is off or failed (the catalog's two rows, C's plans)."""
    if part == "catalog":
        return (
            KeptData(docs, prefix, name="pieces", row="pieces",
                     singles=PIECES_SINGLES, owned=PIECES_OWNED),
            KeptData(docs, prefix, name="photos", row="photos", owned=PHOTOS_OWNED),
        )  # fmt: skip
    if part == "styling":
        return (KeptData(docs, prefix, name="outfits", row="plans", singles=PLANS_SINGLES),)
    return ()


__all__ = [
    "OWNER_FIELD",
    "PHOTOS_OWNED",
    "PIECES_OWNED",
    "PIECES_SINGLES",
    "PLANS_SINGLES",
    "KeptData",
    "WardrobeUnavailable",
    "erase",
    "kept_paths",
    "stand_ins",
]
