# src/jarvis/buildbook/ports.py
"""The seams between the R6 parts (docs/plans/r6-build-book.md "Workstreams"). Each part implements
its own port in its own files; I1 wires them on the app (api/r6_wiring.py). A part that needs more
from another asks I1 to widen the port here: no part reaches into another's module.

- `BookSource` (A, `buildbook/release.py`): the release this server runs and its two files.
- `BookVault` (B, `buildbook/seal.py`): the sealed releases, newest first (D6).
- `BookSessions` (C, `buildbook/sessions.py`): owner / guest sessions, token shown once (D9, D14).
- `ShowLock` (C, `buildbook/lock.py`): the per-owner guest lock (D10).
- `BookTalker` (C, `buildbook/talk.py`): one talk-through answer, guarded (D11, D12).
- `BookAudit`: the audit chain as `jarvis.buildbook` sees it. D11 forbids importing `jarvis.tools`
  here; `tools.audit.AuditTrail` satisfies this structurally. Ids, counts and minutes only.

`BookUnavailable` is the one "fail closed" error a port raises (storage down, a sha256 that does
not match, an undecryptable blob): nothing partial is shown and nothing is overwritten.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Literal, Protocol, runtime_checkable

from jarvis.buildbook.model import (
    KEEP,
    Audience,
    CloseResult,
    FileKind,
    GuestLock,
    Release,
    SealedRelease,
    SessionView,
    TalkReply,
)
from jarvis.core.guardrails import ActionRisk

CloseReason = Literal["closing_done", "ended", "expired", "idle", "replaced", "resumed", "privacy"]


class BookUnavailable(Exception):
    """The book can't be read or written safely right now (fail closed; plain words only)."""


@runtime_checkable
class BookSource(Protocol):
    def current(self) -> Release | None:
        """The release this server runs; None: "This server has no build book"."""
        ...

    def read(self, kind: FileKind) -> bytes:
        """book.json or source.zip, checked against the release's sha256 (else BookUnavailable)."""
        ...


@runtime_checkable
class BookVault(Protocol):
    async def releases(self, uid: str) -> tuple[SealedRelease, ...]:
        """The owner's sealed releases, newest first."""
        ...

    async def seal(
        self, uid: str, release: Release, files: Mapping[FileKind, bytes]
    ) -> SealedRelease: ...

    async def read(self, uid: str, rid: str, kind: FileKind) -> bytes:
        """One sealed file; a chunk or sha256 that does not match raises BookUnavailable."""
        ...

    async def prune(self, uid: str, *, keep: int = KEEP) -> tuple[str, ...]:
        """Index entry first (crypto-shred), then chunks; the release ids removed."""
        ...


@runtime_checkable
class BookSessions(Protocol):
    async def open(self, uid: str, audience: Audience) -> tuple[SessionView, str]:
        """A new session (ending the owner's live one); its token, shown once."""
        ...

    async def check(self, token: str) -> tuple[str, SessionView] | None:
        """(owner uid, session) for a live token; None if unknown, expired or idle."""
        ...

    async def live(self, uid: str) -> SessionView | None: ...

    async def close(self, uid: str, session_id: str, *, reason: CloseReason) -> CloseResult: ...


@runtime_checkable
class ShowLock(Protocol):
    async def get(self, uid: str) -> GuestLock | None:
        """The owner's guest lock, or None; unreadable -> BookUnavailable (the middleware 503s)."""
        ...

    async def set(self, uid: str, session_id: str) -> GuestLock: ...

    async def clear(self, uid: str, lock_id: str) -> bool: ...


@runtime_checkable
class BookTalker(Protocol):
    async def ask(self, uid: str, session: SessionView, text: str) -> TalkReply: ...


@runtime_checkable
class BookAudit(Protocol):
    async def append(
        self,
        *,
        agent: str,
        tool: str,
        risk: ActionRisk,
        outcome: str,
        args: dict[str, Any],
        detail: str = "",
    ) -> object: ...


__all__ = [
    "BookAudit",
    "BookSessions",
    "BookSource",
    "BookTalker",
    "BookUnavailable",
    "BookVault",
    "CloseReason",
    "ShowLock",
]
