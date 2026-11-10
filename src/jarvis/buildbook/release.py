# src/jarvis/buildbook/release.py
"""R6 D4: the release this server runs, and its build book (the `BookSource` port).

CI writes `_book/{release.json, book.json, source.zip}` before `docker build`, and the package data
(`"jarvis.buildbook" = ["_book/*"]`) carries them into the image. `ReleaseSource` reads them with
importlib.resources and checks both SHA-256s ONCE per process:

    current()  None: no release.json, it doesn't parse, or a file is missing or doesn't match
               ("This server has no build book"); a `Release` with `error`: the build failed at
               deploy (best effort) and there is no book — the sealer sends book_seal_failed
    read(kind) the verified bytes of book.json or source.zip (re-verified on every read)
    book()     book.json parsed (`model.load_book`), once

`owner_mentioned` is D3's check (`owner_id`, the D3 amendment): a book naming a configured owner
must not be sealed. Nothing here logs book text or an address.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable
from functools import lru_cache
from importlib.resources import files
from importlib.resources.abc import Traversable
from pathlib import Path
from threading import Lock

from pydantic import ValidationError

from jarvis.buildbook import owner_id
from jarvis.buildbook.model import Book, FileKind, Release, load_book
from jarvis.buildbook.ports import BookUnavailable
from jarvis.logging import get_logger

log = get_logger(__name__)

BOOK_DIR: Traversable | Path = files("jarvis.buildbook") / "_book"
NO_BOOK = "This server has no build book"
FILE_OF: dict[FileKind, str] = {"book": "book.json", "source": "source.zip"}


def _digest(release: Release, kind: FileKind) -> str | None:
    return release.book_sha256 if kind == "book" else release.source_sha256


class ReleaseSource:
    """`BookSource` over a `_book` folder (the packaged one by default)."""

    def __init__(self, root: Traversable | Path | None = None) -> None:
        self._root = root if root is not None else BOOK_DIR
        self._lock = Lock()
        self._checked = False
        self._current: Release | None = None
        self._book: Book | None = None

    def _bytes(self, name: str) -> bytes | None:
        try:
            return self._root.joinpath(name).read_bytes()
        except OSError:
            return None

    def _verified(self, release: Release, kind: FileKind) -> bytes | None:
        data = self._bytes(FILE_OF[kind])
        if data is None or hashlib.sha256(data).hexdigest() != _digest(release, kind):
            return None
        return data

    def _load(self) -> Release | None:
        raw = self._bytes("release.json")
        if raw is None:
            return None
        try:
            release = Release.model_validate_json(raw)
        except ValidationError:
            log.warning("build book release.json unreadable; the book is off")
            return None
        if release.ok and any(self._verified(release, k) is None for k in FILE_OF):
            log.warning("build book files don't match release.json; the book is off")
            return None
        return release

    def current(self) -> Release | None:
        with self._lock:
            if not self._checked:
                self._current, self._checked = self._load(), True
            return self._current

    def read(self, kind: FileKind) -> bytes:
        release = self.current()
        data = self._verified(release, kind) if release is not None and release.ok else None
        if data is None:
            raise BookUnavailable(NO_BOOK)
        return data

    def book(self) -> Book:
        if self._book is None:
            try:
                self._book = load_book(self.read("book"))
            except ValueError:
                raise BookUnavailable(NO_BOOK) from None
        return self._book


@lru_cache(maxsize=1)
def default_source() -> ReleaseSource:
    return ReleaseSource(BOOK_DIR)


def current() -> Release | None:
    """The release this process runs (None: no build book on this server)."""
    return default_source().current()


def owner_mentioned(data: bytes, emails: Iterable[str]) -> bool:
    """D3: does the book name an owner? The one rule (`owner_id.in_book`, D3 amendment) the
    sealer, the guest door and the reply guard use: the full address in any form, or a
    distinctive word of its local part."""
    return owner_id.in_book(data, emails) is not None


__all__ = ["BOOK_DIR", "NO_BOOK", "ReleaseSource", "current", "default_source", "owner_mentioned"]
