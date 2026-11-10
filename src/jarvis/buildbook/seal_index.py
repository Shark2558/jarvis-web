# src/jarvis/buildbook/seal_index.py
"""The sealed build-book index and its envelope (R6 D6; builder B; Layer 7, cross-cutting security).

The envelope is the R2 vault's (`vault/crypto.py`): 512 KiB chunks, a random per-file DEK wrapped
by `Keyring.wrap`, AES-256-GCM via `TokenCipher`; only the AADs are the book's own, word for word
as D6 (`book/index/{uid}/v1`, `book/dek/{uid}/{rid}/{fid}/v1`,
`book/chunk/{uid}/{rid}/{fid}/{n}/{count}/v1`), so a chunk moved to another position, file,
release or owner, or a vault DEK swapped in, fails to open. The index is sealed under keyring
purpose `book_index`. No new crypto here.

`BookIndex` is what the index blob holds: the releases (`model.SealedRelease`), plus, as the R2
vault index keeps them, the chunk sets of seals still in flight (`pending`) and of releases already
shredded whose chunk deletes have yet to succeed (`orphans`).
"""

from __future__ import annotations

import datetime as dt
from typing import Literal

from pydantic import Field

from jarvis.buildbook.model import FILE_ID, Instant, SealedRelease
from jarvis.buildbook.sections import Frozen
from jarvis.integrations.vault import TokenCipher
from jarvis.keyring import Keyring
from jarvis.vault.crypto import CHUNK_BYTES, chunk_count


def index_aad(uid: str) -> str:
    return f"book/index/{uid}/v1"


def dek_aad(uid: str, rid: str, fid: str) -> str:
    return f"book/dek/{uid}/{rid}/{fid}/v1"


def chunk_aad(uid: str, rid: str, fid: str, n: int, count: int) -> str:
    return f"book/chunk/{uid}/{rid}/{fid}/{n}/{count}/v1"


class BookCrypto:
    """`vault.crypto.VaultCrypto` with D6's AADs: the same keyring, DEKs, chunks and cipher."""

    def __init__(self, ring: Keyring) -> None:
        self._ring = ring

    @property
    def kid(self) -> str:
        return self._ring.kid

    def seal(self, uid: str, rid: str, fid: str, data: bytes) -> tuple[str, list[str]]:
        """(wrapped DEK, sealed chunks) for one file's bytes."""
        dek = self._ring.new_dek()
        cipher = TokenCipher(dek)
        count = chunk_count(len(data))
        blobs = [
            cipher.encrypt(
                data[n * CHUNK_BYTES : (n + 1) * CHUNK_BYTES],
                aad=chunk_aad(uid, rid, fid, n, count),
            )
            for n in range(count)
        ]
        return self._ring.wrap(dek, aad=dek_aad(uid, rid, fid)), blobs

    def unwrap(self, uid: str, rid: str, fid: str, wrapped: str) -> bytes:
        return self._ring.unwrap(wrapped, aad=dek_aad(uid, rid, fid))

    def open_chunk(
        self, dek: bytes, uid: str, rid: str, fid: str, n: int, count: int, blob: str
    ) -> bytes:
        return TokenCipher(dek).decrypt(blob, aad=chunk_aad(uid, rid, fid, n, count))

    def seal_index(self, uid: str, payload: bytes) -> str:
        return self._ring.cipher("book_index").encrypt(payload, aad=index_aad(uid))

    def open_index(self, uid: str, blob: str) -> bytes:
        return self._ring.cipher("book_index").decrypt(blob, aad=index_aad(uid))


class Part(Frozen):
    """A file's chunk set outside any release: a seal in flight, or one waiting to be deleted."""

    fid: str = Field(pattern=FILE_ID)
    count: int = Field(ge=1, le=64)
    since: Instant


class BookIndex(Frozen):
    v: Literal[1] = 1
    releases: tuple[SealedRelease, ...] = ()
    pending: tuple[Part, ...] = ()
    orphans: tuple[Part, ...] = ()

    def find(self, rid: str) -> SealedRelease | None:
        return next((r for r in self.releases if r.id == rid), None)

    def size(self) -> int:
        return sum(r.size for r in self.releases)

    def newest_first(self) -> tuple[SealedRelease, ...]:
        order = sorted(
            enumerate(self.releases),
            key=lambda p: (dt.datetime.fromisoformat(p[1].sealed_at), p[0]),
            reverse=True,
        )
        return tuple(r for _, r in order)


def parts_of(release: SealedRelease, now: dt.datetime) -> tuple[Part, ...]:
    return tuple(Part(fid=f.fid, count=f.count, since=now.isoformat()) for f in release.files)


def age(part: Part, now: dt.datetime) -> float:
    return (now - dt.datetime.fromisoformat(part.since)).total_seconds()


__all__ = [
    "BookCrypto",
    "BookIndex",
    "Part",
    "age",
    "chunk_aad",
    "dek_aad",
    "index_aad",
    "parts_of",
]
