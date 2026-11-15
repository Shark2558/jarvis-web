# src/jarvis/wardrobe/catalog/photos.py
"""A piece's photos and fingerprints, sealed (docs/plans/r13-wardrobe.md D9, D7; OPS-01, INV-06).

    {prefix}wardrobe_photo/{uid}_{photo}   {v, kid, owner, piece, view, bytes, blob, updated_at}
        blob = AES-GCM(the cleaned JPEG), purpose `wardrobe_photos`, AAD
        `wardrobe/photo/{uid}/{photo}/v1`
    {prefix}wardrobe_fp/{uid}_{shard}      {v, kid, owner, n, blob, updated_at}
        blob = AES-GCM([{p, w, m, v}] x <= 200: piece, view, model, 1,280 uint8 as base64)

A photo is kept only when he presses Save (the phone checked it for a person and a face on the
same bitmap, D9): JPEG only, a side <= `wardrobe_photo_side` read from its SOF marker (a 600-px
photo is refused), <= `wardrobe_photo_max_kb`, cleaned by structure (`photos.imaging.sanitise_jpeg`:
EXIF, GPS and comments dropped; never decoded here), one per view (front, back, detail) and at
most `wardrobe_photos_per_piece`. A private piece never has a photo or a fingerprint: both are
refused from the RECORD, never from the client's word, and marking a piece private deletes them in
the same change (`drop_ops`). Fingerprints of one model are listed for the signed-in console only
(decrypted, kept in its memory); the query fingerprint of a scan never reaches the server.
"""

from __future__ import annotations

import base64
import binascii
import struct
from collections.abc import Awaitable, Callable
from typing import Any

from jarvis.photos.errors import PickerError
from jarvis.photos.imaging import sanitise_jpeg
from jarvis.storage.docs import Create, Delete, DocTx, Op, Set
from jarvis.wardrobe.catalog.sealed import VERSION, aad_photo, aad_prints, check_owner, check_photo
from jarvis.wardrobe.catalog.store import NOT_IN, CatalogStore
from jarvis.wardrobe.model import Piece, WardrobeView, new_id
from jarvis.wardrobe.ports import Commit, Refused

PER_SHARD, MAX_SHARDS = 200, 9  # 600 pieces x 3 views = 1,800 fingerprints at most
FP_BYTES = 1280
MODELS = ("mnv2-int8-1", "mnv2-fp32-1")
VIEWS = ("front", "back", "detail")
PRIVATE = "A private piece never has a photo or a fingerprint."
NOT_JPEG = "Only a clean JPEG photo of a saved piece can be kept."
_SOF = frozenset({0xC0, 0xC1, 0xC2})
Get = Callable[[str], Awaitable[Any]]


def frame_size(jpeg: bytes) -> tuple[int, int]:
    """(width, height) from the SOF marker of a cleaned JPEG (no pixel is decoded)."""
    pos = 2
    while pos + 4 <= len(jpeg) and jpeg[pos] == 0xFF:
        marker = jpeg[pos + 1]
        (length,) = struct.unpack_from(">H", jpeg, pos + 2)
        if marker in _SOF and pos + 9 <= len(jpeg):
            height, width = struct.unpack_from(">HH", jpeg, pos + 5)
            return width, height
        pos += 2 + length
    raise Refused(NOT_JPEG)


def _keepable(view: WardrobeView, pid: str) -> Piece:
    p = view.piece(pid)
    if p is None or p.merged_into is not None or p.state == "archived":
        raise Refused(NOT_IN)
    if p.private:
        raise Refused(PRIVATE)
    return p


class Prints:
    def __init__(self, store: CatalogStore) -> None:
        self.store, self._p = store, store.prefix

    def path(self, uid: str, shard: int) -> str:
        return f"{self._p}wardrobe_fp/{check_owner(uid)}_{shard}"

    async def _read(self, get: Get, uid: str) -> list[dict[str, str]]:
        out: list[dict[str, str]] = []
        for shard in range(MAX_SHARDS):
            doc = await get(self.path(uid, shard))
            if doc is None:
                break
            aad = aad_prints(uid, shard)
            out += self.store.sealer.open("wardrobe_photos", aad, doc.get("blob"))
        return out

    def _writes(self, uid: str, entries: list[dict[str, str]], had: int) -> list[Op]:
        stamp, ops = self.store.now().isoformat(), list[Op]()
        n = (len(entries) + PER_SHARD - 1) // PER_SHARD
        for shard in range(n):
            part = entries[shard * PER_SHARD : (shard + 1) * PER_SHARD]
            blob = self.store.sealer.seal("wardrobe_photos", aad_prints(uid, shard), part)
            body = {"v": VERSION, "kid": self.store.sealer.kid, "owner": uid, "n": len(part)}
            ops.append(Set(self.path(uid, shard), {**body, "blob": blob, "updated_at": stamp}))
        return ops + [Delete(self.path(uid, s)) for s in range(n, had)]

    async def save(self, uid: str, pid: str, view_: str, model: str, v: str) -> None:
        if view_ not in VIEWS or model not in MODELS or not _is_print(v):
            raise Refused("That isn't a fingerprint this JARVIS keeps.")

        async def fn(view: WardrobeView, tx: DocTx) -> Commit:
            p = _keepable(view, pid)
            found = await self._read(tx.get, uid)
            had = (len(found) + PER_SHARD - 1) // PER_SHARD
            keep = [e for e in found if (e["p"], e["w"], e["m"]) != (pid, view_, model)]
            if len(keep) >= MAX_SHARDS * PER_SHARD:
                raise Refused("Your wardrobe keeps as many fingerprints as it can.")
            entries = [*keep, {"p": pid, "w": view_, "m": model, "v": v}]
            rec = p.model_copy(update={"fp_model": model})
            return Commit(records=(rec,), extra=tuple(self._writes(uid, entries, had)))

        await self.store.transact(uid, fn)

    async def items(self, uid: str, model: str) -> tuple[dict[str, str], ...]:
        view = await self.store.view(uid)
        live = {p.id for p in view.active() if not p.private}
        found = await self._read(self.store.docs.get, uid)
        return tuple(e for e in found if e["m"] == model and e["p"] in live)

    async def drop_ops(self, uid: str, pids: set[str] | None, get: Get) -> list[Op]:
        """The writes that drop these pieces' fingerprints (None: every fingerprint)."""
        found = await self._read(get, uid)
        keep = [e for e in found if pids is not None and e["p"] not in pids]
        if len(keep) == len(found):
            return []
        return self._writes(uid, keep, (len(found) + PER_SHARD - 1) // PER_SHARD)


def _is_print(v: object) -> bool:
    try:
        return isinstance(v, str) and len(base64.b64decode(v, validate=True)) == FP_BYTES
    except (binascii.Error, ValueError):
        return False


class PhotoVault:
    """`ports.PhotoVault` (count, delete_all) and the routes' save, get and delete."""

    def __init__(self, store: CatalogStore, *, side: int, max_kb: int, per_piece: int) -> None:
        self.store, self.prints = store, Prints(store)
        self.side, self.max_bytes, self.per_piece = side, max_kb * 1024, per_piece
        self._p = store.prefix

    def path(self, uid: str, photo: str) -> str:
        return f"{self._p}wardrobe_photo/{check_owner(uid)}_{check_photo(photo)}"

    def clean(self, data: bytes) -> bytes:
        if len(data) > self.max_bytes:
            raise Refused(f"A photo is at most {self.max_bytes // 1024} KB.")
        try:
            clean = sanitise_jpeg(data)
        except PickerError:
            raise Refused(NOT_JPEG) from None
        width, height = frame_size(clean)
        if max(width, height) > self.side:
            raise Refused(f"A photo is at most {self.side} pixels a side: crop it to the piece.")
        return clean

    async def save(self, uid: str, pid: str, view_: str, data: bytes) -> tuple[str, int]:
        if view_ not in VIEWS:
            raise Refused("A photo is of the front, the back or a detail.")
        clean, photo = self.clean(data), new_id("wh")

        async def fn(view: WardrobeView, tx: DocTx) -> Commit:
            p = _keepable(view, pid)
            views = {ph: ((await tx.get(self.path(uid, ph))) or {}).get("view") for ph in p.photos}
            same = [ph for ph, v in views.items() if v == view_]
            rest = [ph for ph in p.photos if ph not in same]
            if len(rest) >= self.per_piece:
                raise Refused(f"A piece keeps at most {self.per_piece} photos.")
            blob = self.store.sealer.seal_bytes("wardrobe_photos", aad_photo(uid, photo), clean)
            body = {"v": VERSION, "kid": self.store.sealer.kid, "owner": uid, "piece": pid,
                    "view": view_, "bytes": len(clean), "blob": blob,
                    "updated_at": self.store.now().isoformat()}  # fmt: skip
            ops: list[Op] = [Create(self.path(uid, photo), body)]
            ops += [Delete(self.path(uid, ph)) for ph in same]
            rec = p.model_copy(update={"photos": (*rest, photo)})
            return Commit(records=(rec,), extra=tuple(ops))

        await self.store.transact(uid, fn)
        return photo, len(clean)

    async def get(self, uid: str, photo: str) -> bytes | None:
        doc = await self.store.docs.get(self.path(uid, photo))
        if doc is None or doc.get("owner") != uid:
            return None
        aad = aad_photo(uid, photo)
        return self.store.sealer.open_bytes("wardrobe_photos", aad, doc.get("blob"))

    async def delete(self, uid: str, photo: str) -> bool:
        path, gone = self.path(uid, photo), [False]

        async def fn(view: WardrobeView, tx: DocTx) -> Commit:
            owner = next((p for p in view.pieces.values() if photo in p.photos), None)
            gone[0] = owner is not None or (await tx.get(path)) is not None
            recs: tuple[Piece, ...] = ()
            if owner is not None:
                left = tuple(x for x in owner.photos if x != photo)
                recs = (owner.model_copy(update={"photos": left}),)
            return Commit(records=recs, extra=(Delete(path),) if gone[0] else ())

        await self.store.transact(uid, fn)
        return gone[0]

    async def drop_ops(self, uid: str, p: Piece, get: Get) -> list[Op]:
        """Everything a piece's photos and fingerprints are (private, or purged)."""
        ops: list[Op] = [Delete(self.path(uid, ph)) for ph in p.photos]
        return ops + await self.prints.drop_ops(uid, {p.id}, get)

    async def count(self, uid: str) -> int:
        return sum(len(p.photos) for p in (await self.store.view(uid)).pieces.values())

    async def delete_all(self, uid: str) -> int:
        """Privacy's "delete all wardrobe photos": the catalog stays usable (e2e 7)."""
        n = [0]

        async def fn(view: WardrobeView, tx: DocTx) -> Commit:
            have = [p for p in view.pieces.values() if p.photos or p.fp_model]
            n[0] = sum(len(p.photos) for p in have)
            ops: list[Op] = [Delete(self.path(uid, ph)) for p in have for ph in p.photos]
            ops += await self.prints.drop_ops(uid, None, tx.get)
            recs = tuple(p.model_copy(update={"photos": (), "fp_model": None}) for p in have)
            return Commit(records=recs, extra=tuple(ops))

        await self.store.transact(uid, fn)
        return n[0]


__all__ = [
    "FP_BYTES",
    "MODELS",
    "NOT_JPEG",
    "PRIVATE",
    "VIEWS",
    "PhotoVault",
    "Prints",
    "frame_size",
]
