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
shredded whose chunk deletes have yet to succeed (`orphans`). `checked_files` is the check a seal
starts with: exactly the release's files (its book and source; from R6.3.1 on its pages and
flows too, `kinds_of`), each under its cap and matching its SHA-256.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import secrets
from collections.abc import Mapping
from typing import Literal

from pydantic import Field

from jarvis.buildbook.model import (
    BOOK_JSON_CAP_BYTES,
    FILE_ID,
    SNAPSHOT_CAP_BYTES,
    FileKind,
    Instant,
    Release,
    SealedFile,
    SealedRelease,
)
from jarvis.buildbook.ports import BookUnavailable
from jarvis.buildbook.sections import Frozen
from jarvis.buildbook.writer.model import FLOWS_FILE_CAP_BYTES, PAGES_FILE_CAP_BYTES
from jarvis.integrations.vault import TokenCipher
from jarvis.keyring import Keyring
from jarvis.vault.crypto import CHUNK_BYTES, chunk_count

KINDS: tuple[FileKind, ...] = ("book", "source")  # every sealed release has these two
EXTRA_KINDS: tuple[FileKind, ...] = ("pages", "flows")  # R6.3.1 D7: from v6.3.2 on
CAPS: Mapping[FileKind, int] = {
    "book": BOOK_JSON_CAP_BYTES,
    "source": SNAPSHOT_CAP_BYTES,
    "pages": PAGES_FILE_CAP_BYTES,  # R6.3.1 D7
    "flows": FLOWS_FILE_CAP_BYTES,  # R6.3.1 D7
}


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

    def seal_file(
        self, uid: str, rid: str, kind: FileKind, data: bytes
    ) -> tuple[SealedFile, list[str]]:
        """One file sealed under a new file id: its index entry and its chunks (VaultError)."""
        fid = f"bf_{secrets.token_hex(6)}"
        wrapped, blobs = self.seal(uid, rid, fid, data)
        digest = hashlib.sha256(data).hexdigest()
        meta = SealedFile(
            kind=kind, fid=fid, size=len(data), sha256=digest, count=len(blobs), dek=wrapped
        )
        return meta, blobs

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


def digest_of(release: Release, kind: FileKind) -> str | None:
    """The SHA-256 release.json names for one of its files (None: it has no such file)."""
    return {"book": release.book_sha256, "source": release.source_sha256,
            "pages": release.pages_sha256, "flows": release.flows_sha256}[kind]  # fmt: skip


def has_file(sealed: SealedRelease, kind: FileKind) -> bool:
    """R6.3.1: a release sealed before v6.3.2 has no pages or flows file."""
    return any(f.kind == kind for f in sealed.files)


def kinds_of(release: Release) -> tuple[FileKind, ...]:
    """The files a release has: its book and source, then (R6.3.1) its pages and flows when
    release.json names them; a failed build has none."""
    if not release.ok:
        return ()
    return (*KINDS, *(k for k in EXTRA_KINDS if digest_of(release, k) is not None))


def checked_files(release: Release, files: Mapping[FileKind, bytes]) -> dict[FileKind, bytes]:
    """The release's files in `kinds_of` order, each checked (R6.3.1: with its pages and
    flows when release.json names them)."""
    if not release.ok:
        raise BookUnavailable("This release has no build book.")
    kinds = kinds_of(release)
    if set(files) != set(kinds):
        raise ValueError("a sealed release is its book and its source snapshot (and its pages)")
    for kind in kinds:
        if len(files[kind]) > CAPS[kind]:
            raise BookUnavailable("A file of this release is over its size cap.")
        if hashlib.sha256(files[kind]).hexdigest() != digest_of(release, kind):
            raise BookUnavailable("The files don't match their release.")
    return {kind: files[kind] for kind in kinds}


__all__ = [
    "CAPS",
    "EXTRA_KINDS",
    "KINDS",
    "BookCrypto",
    "BookIndex",
    "Part",
    "age",
    "checked_files",
    "chunk_aad",
    "dek_aad",
    "digest_of",
    "has_file",
    "index_aad",
    "kinds_of",
    "parts_of",
]
