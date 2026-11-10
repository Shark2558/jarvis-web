# src/jarvis/buildbook/ports.py
"""The build book's ports (R6 I0; docs/plans/r6-build-book.md "Contract", D4-D14). Builders A-C
implement them independently; the routes (api/book.py, api/book_show.py), the lock middleware
(api/book_lock.py) and I1's wiring depend on these Protocols only. Every time is an aware
`datetime` passed in (`now=`), so tests drive the clock. Nothing here logs a question, a reply,
book text, a token or a key; errors carry plain words for the owner, never content.

    BookSource    A: buildbook/release.py   the release this server runs and its two files
    BookVault     B: buildbook/seal.py      sealed releases in the vault family (D6)
    BookSessions  C: buildbook/sessions.py  book sessions and their sealed turns (D9, D14)
    ShowLock      C: buildbook/lock.py      the per-owner guest lock (D10)
    BookTalker    C: buildbook/talk.py      the talk-through's minimal lane (D11, D12)

Errors: `BookUnavailable` (no book on this server: 404 no_book / "This server has no build
book"), `BookOff` (the feature can't run here, e.g. no keyring: 503 book_off), `SessionGone`
(token unknown, expired, idle or closed: 401), `LockUnreadable` (the lock can't be read: the
middleware answers 503, never "unlocked"), `VaultTampered` (a sealed read didn't match its
SHA-256: fail closed, book_seal_failed).
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Protocol, runtime_checkable

from jarvis.buildbook.model import (
    KEEP,
    Audience,
    Book,
    ClosedSession,
    CloseReason,
    FileKind,
    OpenedSession,
    Release,
    SealedRelease,
    SessionView,
    ShowLockState,
    TalkReply,
    TalkState,
)


class BookError(Exception):
    """Base of the book's errors; the message is plain words, never content."""


class BookUnavailable(BookError):
    """This server has no build book (no release.json, a failed build, a SHA-256 mismatch)."""


class BookOff(BookError):
    """The book can't run on this server (no keyring / token key, storage not persistent)."""


class SessionGone(BookError):
    """The book token is unknown, expired, idle or its session was closed (401)."""


class LockUnreadable(BookError):
    """The guest lock could not be read: treat as locked-and-unknown (503), never unlocked."""


class VaultTampered(BookError):
    """A sealed index or chunk failed its AAD or SHA-256 check: fail closed."""


@runtime_checkable
class BookSource(Protocol):
    """The release this server runs (D4; A's `buildbook/release.py`, `importlib.resources`)."""

    def current(self) -> Release | None:
        """release.json, checked once per process: None when there is none or a file's SHA-256
        doesn't match (the book is then absent); a `Release` with `error` for a failed build."""
        ...

    def read(self, kind: FileKind) -> bytes:
        """The verified bytes of book.json or source.zip. BookUnavailable when `current()` is
        None or failed."""
        ...

    def book(self) -> Book:
        """book.json parsed (`model.load_book`). BookUnavailable as `read`."""
        ...


@runtime_checkable
class BookVault(Protocol):
    """Sealed releases (D6; B's `buildbook/seal.py`): `{prefix}book/{uid}` = the index sealed under
    keyring purpose `book_index` (AAD `book/index/{uid}/v1`), chunks of 512 KiB with a per-file
    DEK. At most 6 chunk writes a commit, the index last; prune index first (crypto-shred)."""

    async def releases(self, uid: str) -> tuple[SealedRelease, ...]:
        """Newest first (by sealed_at). VaultTampered when the index fails its check."""
        ...

    async def seal(
        self, uid: str, release: Release, files: Mapping[FileKind, bytes], *, now: datetime
    ) -> SealedRelease:
        """Seal one release's book.json and source.zip (both required, each <= its cap). Idempotent
        for a release already sealed (returns the existing entry). Raises BookOff past
        `book_max_total_mb`."""
        ...

    async def prune(self, uid: str, *, keep: int = KEEP) -> tuple[str, ...]:
        """Drop all but the newest `keep`; returns the release ids removed (index entry first,
        then chunks by path; a chunk delete that fails is retried by the next run)."""
        ...

    async def read(self, uid: str, rid: str, kind: FileKind) -> bytes:
        """One sealed file, verified against its SHA-256. LookupError: no such release.
        VaultTampered: a chunk or the digest doesn't match."""
        ...

    async def used_bytes(self, uid: str) -> int: ...

    async def delete_all(self, uid: str) -> int:
        """Privacy -> Delete (with a passkey, D16): every sealed release; returns how many."""
        ...


@runtime_checkable
class BookSessions(Protocol):
    """Book sessions (D9; C's `buildbook/sessions.py`): `{prefix}book_sessions/{bk}` holds uid,
    audience, mac(token) (keyring MAC domain `book_session`), created, last_seen, until,
    questions and the turns sealed under `book_session` (AAD `book/session/{uid}/{bk}/v1`).
    One live session per owner; 45 min absolute, 10 min idle (Settings)."""

    async def open(
        self, uid: str, audience: Audience, *, now: datetime
    ) -> tuple[OpenedSession, ClosedSession | None]:
        """A new session (its token shown once) and the one it ended, if any (reason new_open)."""
        ...

    async def resolve(self, uid: str, token: str, *, now: datetime) -> SessionView:
        """The live session this token opens for this owner. SessionGone otherwise (an expired
        or idle one is closed on the spot, D14)."""
        ...

    async def beat(self, uid: str, token: str, *, now: datetime) -> SessionView:
        """The show's 60-second beat: moves the idle limit (never the absolute one)."""
        ...

    async def live(self, uid: str, *, now: datetime) -> SessionView | None: ...

    async def add_turn(self, uid: str, session_id: str, question: str, reply: str) -> int:
        """Store one guarded turn, sealed; returns the questions left."""
        ...

    async def turns(self, uid: str, session_id: str) -> tuple[tuple[str, str], ...]:
        """The last 8 (question, reply) pairs for the talk lane's context (D11)."""
        ...

    async def close(
        self, uid: str, session_id: str, *, reason: CloseReason, now: datetime
    ) -> ClosedSession:
        """Mark closing, delete the document, read it back absent (D14 steps 1-2). `wiped` False
        when the read-back still finds it (the sweep retries)."""
        ...

    async def sweep(self, *, now: datetime) -> tuple[ClosedSession, ...]:
        """Close every expired or idle session (the book_sweep TickJob, D14)."""
        ...


@runtime_checkable
class ShowLock(Protocol):
    """The guest lock (D10; C's `buildbook/lock.py`): `{prefix}book_lock/{uid}` = {id, bk, since}.
    Read by `ShowLockMiddleware` on every cookie request (cached <= 3 s per instance)."""

    async def get(self, uid: str) -> ShowLockState | None:
        """None: not locked. LockUnreadable: the read failed (the middleware answers 503)."""
        ...

    async def set(self, uid: str, session_id: str, *, now: datetime) -> ShowLockState:
        """At a guest open: a new lock id `bl_<12 hex>` (the target of a book_resume proof)."""
        ...

    async def lift(self, uid: str, lock_id: str, *, signed_out_before: float | None = None) -> bool:
        """Only after a `book_resume` passkey check bound to `lock_id`; False when the current
        lock has another id (nothing changes). `signed_out_before` (SEC-4): every owner cookie
        session issued before it stops counting."""
        ...


@runtime_checkable
class BookTalker(Protocol):
    """The talk-through (D11, D12; C's `buildbook/talk.py` `BookTalk(brains, billing, mode, book,
    sessions)`): no Brain, gateway, memory, session store or documents; `tools=None` always."""

    async def state(self, uid: str) -> TalkState:
        """{on, why}: off with plain words for no-AI mode, a training brain not allowed, or the
        monthly limit (the contract's `talk`)."""
        ...

    async def ask(self, uid: str, session: SessionView, text: str, *, now: datetime) -> TalkReply:
        """Pre-guard -> (billing, one model call) -> post-guard. A refusal is a `lines.LINES` line
        with NO model call; only the guarded reply is stored (`BookSessions.add_turn`)."""
        ...


__all__ = [
    "BookError",
    "BookOff",
    "BookSessions",
    "BookSource",
    "BookTalker",
    "BookUnavailable",
    "BookVault",
    "LockUnreadable",
    "SessionGone",
    "ShowLock",
    "VaultTampered",
]
