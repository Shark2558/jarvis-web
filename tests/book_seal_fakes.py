# tests/book_seal_fakes.py -- shared by the R6 builder-B tests and evals/r6_book/seal.py: releases
# made from the committed `_book` fixture, a book source, a recording notifier and audit chain, a
# book-session stand-in, and a Docs wrapper that fails on cue. No network, no pytest import (the
# eval imports this file too). Imported bare: `from book_seal_fakes import ...`.
from __future__ import annotations

import datetime as dt
import hashlib
import io
import random
import zipfile
from collections.abc import Awaitable, Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

from jarvis.buildbook.model import (
    Audience,
    Book,
    FileKind,
    Release,
    SessionView,
    canonical_bytes,
    load_book,
)
from jarvis.buildbook.ports import BookUnavailable, SessionGone
from jarvis.keyring import Keyring
from jarvis.notify.ports import Delivery, Signal
from jarvis.storage.docs import Delete, Docs, DocTx, MemoryDocs, Op, Query

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "book" / "_book"
KEY = bytes(range(7, 39))
UID = "u_bookowner000001"
OTHER = "u_bookother000002"
NOW = dt.datetime(2026, 11, 10, 9, 0, tzinfo=dt.UTC)
OWNER_TOKEN = "o" * 43
GUEST_TOKEN = "g" * 43


def ring() -> Keyring:
    return Keyring(KEY)


def fixture_book() -> Book:
    return load_book((FIXTURE / "book.json").read_bytes())


def fixture_zip() -> bytes:
    return (FIXTURE / "source.zip").read_bytes()


def big_zip(n: int, size: int) -> bytes:
    """A real zip of `size` incompressible bytes (more than one 512 KiB chunk when large)."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_STORED) as zf:
        zf.writestr(f"JARVIS-source-{n:07x}/blob.bin", random.Random(n).randbytes(size))
    return buf.getvalue()


def make_release(
    n: int, *, label: str = "R6", source: bytes | None = None, book: Book | None = None
) -> tuple[Release, dict[FileKind, bytes]]:
    """Release number `n`: its own commit, a book that names it, and a source snapshot."""
    sha = hashlib.sha1(f"jarvis release {n}".encode()).hexdigest()
    committed = (NOW - dt.timedelta(days=30) + dt.timedelta(days=n)).isoformat()
    base = book or fixture_book()
    ref = base.release.model_copy(
        update={"id": sha[:7], "sha": sha, "label": label, "committed_at": committed}
    )
    book_bytes = canonical_bytes(base.model_copy(update={"release": ref}))
    zip_bytes = source if source is not None else big_zip(n, 2_000)
    release = Release(
        id=sha[:7],
        sha=sha,
        label=label,
        committed_at=committed,
        book_sha256=hashlib.sha256(book_bytes).hexdigest(),
        source_sha256=hashlib.sha256(zip_bytes).hexdigest(),
        source_bytes=len(zip_bytes),
    )
    return release, {"book": book_bytes, "source": zip_bytes}


def failed_release(n: int) -> Release:
    sha = hashlib.sha1(f"jarvis release {n}".encode()).hexdigest()
    return Release(
        id=sha[:7], sha=sha, label="R6", committed_at=NOW.isoformat(), error="the build failed"
    )


class FakeSource:
    """ports.BookSource over one release held in memory (A's release.py in production)."""

    def __init__(
        self, release: Release | None = None, files: Mapping[FileKind, bytes] | None = None
    ) -> None:
        self.release = release
        self.files: dict[FileKind, bytes] = dict(files or {})
        self.reads = 0

    def use(self, release: Release | None, files: Mapping[FileKind, bytes] | None = None) -> None:
        self.release, self.files = release, dict(files or {})

    def current(self) -> Release | None:
        return self.release

    def read(self, kind: FileKind) -> bytes:
        self.reads += 1
        if self.release is None or not self.release.ok or kind not in self.files:
            raise BookUnavailable("This server has no build book.")
        return self.files[kind]

    def book(self) -> Book:
        return load_book(self.read("book"))


class FakeNotifier:
    def __init__(self) -> None:
        self.sent: list[tuple[str, str, str]] = []  # (uid, kind, message)
        self.fail = False

    async def notify(
        self,
        uid: str,
        signal: Signal,
        message: str,
        *,
        named_message: str | None = None,
        photo: bytes | None = None,
    ) -> Delivery:
        if self.fail:
            raise RuntimeError("telegram down")
        self.sent.append((uid, signal.kind, message))
        return Delivery(action="ring", reason="test", telegram=True)

    def kinds(self) -> list[str]:
        return [k for _, k, _ in self.sent]


class FakeAudit:
    def __init__(self) -> None:
        self.rows: list[dict[str, Any]] = []
        self.fail = False

    async def append(self, **kw: Any) -> None:
        if self.fail:
            raise RuntimeError("audit down")
        self.rows.append(kw)

    def tools(self) -> list[str]:
        return [str(r["tool"]) for r in self.rows]


def view(audience: Audience, sid: str = "bk_" + "1" * 16) -> SessionView:
    until = (NOW + dt.timedelta(minutes=45)).isoformat()
    return SessionView(
        session_id=sid,
        audience=audience,
        created_at=NOW.isoformat(),
        until=until,
        idle_until=(NOW + dt.timedelta(minutes=10)).isoformat(),
        questions=0,
        questions_left=20,
    )


class FakeSessions:
    """The slice of ports.BookSessions builder B's routes use: resolve and live. Tokens map to
    (uid, audience); anything else is SessionGone (C's sessions.py in production)."""

    def __init__(self) -> None:
        self.tokens: dict[str, tuple[str, Audience]] = {}
        self.live_view: SessionView | None = None
        self.closed: list[tuple[str, str]] = []

    def grant(self, token: str, uid: str, audience: Audience) -> None:
        self.tokens[token] = (uid, audience)

    async def resolve(self, uid: str, token: str, *, now: dt.datetime) -> SessionView:
        found = self.tokens.get(token)
        if found is None or found[0] != uid:
            raise SessionGone("Open the build book again.")
        return view(found[1])

    async def live(self, uid: str, *, now: dt.datetime) -> SessionView | None:
        return self.live_view

    async def close(self, uid: str, session_id: str, *, reason: str, now: dt.datetime) -> Any:
        self.closed.append((session_id, reason))
        self.live_view = None
        return None


class FlakyDocs(Docs):
    """MemoryDocs that can fail writes, deletes or reads on cue (a storage outage)."""

    def __init__(self, inner: MemoryDocs | None = None) -> None:
        self.inner = inner or MemoryDocs()
        self.fail_writes = 0  # fail the next n write() calls
        self.fail_deletes = 0  # fail the next n write() calls holding a Delete
        self.fail_reads = False

    async def get(self, path: str) -> dict[str, Any] | None:
        if self.fail_reads:
            raise RuntimeError("firestore down")
        return await self.inner.get(path)

    async def query(self, q: Query) -> list[tuple[str, dict[str, Any]]]:
        return await self.inner.query(q)

    async def write(self, ops: Sequence[Op]) -> None:
        if self.fail_deletes and any(isinstance(o, Delete) for o in ops):
            self.fail_deletes -= 1
            raise RuntimeError("delete failed")
        if self.fail_writes:
            self.fail_writes -= 1
            raise RuntimeError("write failed")
        await self.inner.write(ops)

    async def transaction(self, fn: Callable[[DocTx], Awaitable[Any]]) -> Any:
        if self.fail_reads:
            raise RuntimeError("firestore down")
        return await self.inner.transaction(fn)


def chunk_paths(docs: MemoryDocs, prefix: str = "jarvis_") -> list[str]:
    return sorted(p for p in docs._data if p.startswith(f"{prefix}book/") and "/book_chunks/" in p)


__all__ = [
    "FIXTURE",
    "GUEST_TOKEN",
    "KEY",
    "NOW",
    "OTHER",
    "OWNER_TOKEN",
    "UID",
    "FakeAudit",
    "FakeNotifier",
    "FakeSessions",
    "FakeSource",
    "FlakyDocs",
    "big_zip",
    "chunk_paths",
    "failed_release",
    "fixture_book",
    "fixture_zip",
    "make_release",
    "ring",
    "view",
]
