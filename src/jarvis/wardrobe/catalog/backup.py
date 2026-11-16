# src/jarvis/wardrobe/catalog/backup.py
"""The wardrobe's own backup file (docs/plans/r13-wardrobe.md D17, OPS-06; plan review H3, L9).

One file, made line by line and streamed (never whole in memory):

    JWB1 {"v": 1, "kid": "tk1", "photos": false}\\n          the head, in clear (no data of his)
    <base64 line 1>\\n ... <base64 line N>\\n                  each line sealed with the `wardrobe`
                                                            key, AAD `wardrobe/backup/{uid}/v1/{n}`

A line is `{"t": "index" | "log" | "photo" | "fp" | "end", "d": ...}`: the index (pieces, pairs,
sets, places, labels, states, his settings), each piece's whole event log, and ONLY when he ticks
"include photos" each photo's and fingerprint shard's stored document as it is (their own sealed
blobs, never opened for the backup); the last line counts the lines before it. The line number
in each AAD makes a reordered, spliced or cut file fail to open. It opens only on this JARVIS for
him with today's key; after a key change (`keyring.KEY_ID`) older files can't be read.
A file larger than `wardrobe_backup_max_mb` with photos is refused in words: download it without
photos (R14's Firestore backups keep them).
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

from jarvis.wardrobe.catalog.photos import MAX_SHARDS, PhotoVault
from jarvis.wardrobe.catalog.sealed import aad_backup, dumps
from jarvis.wardrobe.catalog.store import CatalogStore
from jarvis.wardrobe.ports import Refused

MAGIC = b"JWB1 "
VERSION = 1
TOO_BIG = "With photos this backup is over {mb} MB: download it without photos."
KEY_NOTE = "It opens only on this JARVIS; after a key change older backup files can't be read."


def aad_line(uid: str, n: int) -> str:
    return f"{aad_backup(uid)}/{n}"


class Backup:
    def __init__(self, store: CatalogStore, vault: PhotoVault, *, max_mb: int) -> None:
        self.store, self.vault, self.max_bytes = store, vault, max_mb * 1024 * 1024
        self.max_mb = max_mb

    def _line(self, uid: str, n: int, kind: str, data: Any) -> bytes:
        blob = self.store.sealer.seal("wardrobe", aad_line(uid, n), {"t": kind, "d": data})
        return blob.encode() + b"\n"

    async def _photo_docs(self, uid: str) -> list[tuple[str, dict[str, Any]]]:
        view = await self.store.view(uid)
        found = []
        for p in view.pieces.values():
            for ph in p.photos:
                doc = await self.store.docs.get(self.vault.path(uid, ph))
                if doc is not None:
                    found.append((ph, doc))
        return found

    async def check_size(self, uid: str, photos: bool) -> None:
        """Before a byte is sent: refuse (in words) a file with photos over the cap."""
        if not photos:
            return
        size = sum(len(json.dumps(doc)) for _, doc in await self._photo_docs(uid)) * 4 // 3
        if size > self.max_bytes:
            raise Refused(TOO_BIG.format(mb=self.max_mb))

    async def lines(self, uid: str, *, photos: bool = False) -> AsyncIterator[bytes]:
        """The file, line by line (the route streams it)."""
        head = {"v": VERSION, "kid": self.store.sealer.kid, "photos": photos}
        yield MAGIC + dumps(head) + b"\n"
        view = await self.store.view(uid)
        n = 1
        yield self._line(uid, n, "index", view.to_json())
        for pid in view.pieces:
            n += 1
            events = [e.to_json() for e in await self.store.events(uid, pid, view=view)]
            yield self._line(uid, n, "log", {"p": pid, "e": events})
        if photos:
            for ph, doc in await self._photo_docs(uid):
                n += 1
                yield self._line(uid, n, "photo", {"id": ph, "doc": doc})
            for shard in range(MAX_SHARDS):
                found = await self.store.docs.get(self.vault.prints.path(uid, shard))
                if found is None:
                    break
                n += 1
                yield self._line(uid, n, "fp", {"n": shard, "doc": found})
        yield self._line(uid, n + 1, "end", {"lines": n})

    async def file(self, uid: str, *, photos: bool = False) -> bytes:
        """The whole file (tests and the eval; the route streams `lines`)."""
        await self.check_size(uid, photos)
        return b"".join([chunk async for chunk in self.lines(uid, photos=photos)])


__all__ = ["KEY_NOTE", "MAGIC", "TOO_BIG", "VERSION", "Backup", "aad_line"]
