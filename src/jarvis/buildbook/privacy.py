# src/jarvis/buildbook/privacy.py
"""The build book's two rows in the privacy dashboard (R6 D16; builder B; cross-cutting security).
I1 registers both in `privacy_sources`.

- `BookSealedSource` (`book_sealed`, Documents): the sealed releases, their MB of the limit,
  encrypted by JARVIS. Export: each release's id, label, commit, dates and MB (the code itself
  downloads from Book). Delete needs the passkey (`privacy_delete`; nothing brings them back): the
  current release is held first so the sealer doesn't seal it again at its next run (the next
  release seals as usual), then every release is crypto-shredded (`BookVault.delete_all`).
- `BookSessionsSource` (`book_sessions`, Activity and messages): the live book session, if any.
  Delete is simple: it ends the session and wipes it through the book service (D14's steps, the
  audit line and the notice; I1 passes C's `BookService` as `end`), or, without one, closes it
  with reason `privacy`. Nothing to export: a session's turns are deleted when it ends.
Neither row ever shows book text, a question, a key or a token.
"""

from __future__ import annotations

import datetime as dt
import hashlib
from collections.abc import Awaitable, Callable
from typing import Any, Protocol

from jarvis.buildbook.model import MIB
from jarvis.buildbook.ports import BookSessions, BookVault
from jarvis.privacy.ports import CategoryView

# the dashboard's own section names (privacy/sources.py; pinned equal by the tests)
SEC_DOCUMENTS = "Documents"
SEC_ACTIVITY = "Activity and messages"
OURS = "Firestore, encrypted by JARVIS"


def _now() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


class Holder(Protocol):
    async def hold(self, uid: str) -> str | None: ...


def _rev(*parts: object) -> str:
    return hashlib.sha256(":".join(str(p) for p in parts).encode()).hexdigest()[:16]


class BookSealedSource:
    id = "book_sealed"
    section = SEC_DOCUMENTS
    label = "Sealed build books"

    def __init__(self, vault: BookVault, sealer: Holder | None, *, limit_mb: int) -> None:
        self._vault = vault
        self._sealer = sealer
        self._limit_mb = limit_mb

    async def describe(self, uid: str) -> CategoryView:
        releases = await self._vault.releases(uid)
        size = sum(r.size for r in releases)
        return CategoryView(
            id=self.id,
            section=self.section,
            label=self.label,
            what="Each release's build book and that release's source code, sealed in your vault.",
            count=len(releases),
            unit="releases",
            size_hint=f"{round(size / MIB, 1)} MB of {self._limit_mb} MB",
            retention="The last 3 releases; an older one is deleted when a new release is sealed.",
            where=OURS,
            encrypted_by_jarvis=True,
            export=True,
            delete="passkey" if releases else "none",
            recoverable=False,
            note="Deleting them also stops this release being sealed again; the next release is.",
            rev=_rev(",".join(r.id for r in releases), size),
        )

    async def export(self, uid: str) -> dict[str, Any] | None:
        rows = [
            {**r.view(), "sha": r.sha, "committed_at": r.committed_at}
            for r in await self._vault.releases(uid)
        ]
        return {"releases": rows, "note": "The code downloads from Book, on each release's row."}

    async def delete(self, uid: str) -> int:
        if self._sealer is not None:
            await self._sealer.hold(uid)
        return await self._vault.delete_all(uid)


class BookSessionsSource:
    id = "book_sessions"
    section = SEC_ACTIVITY
    label = "Build book session"

    def __init__(
        self,
        sessions: BookSessions,
        *,
        end: Callable[[str], Awaitable[int]] | None = None,
        session_minutes: int = 45,
        clock: Callable[[], dt.datetime] = _now,
    ) -> None:
        self._sessions = sessions
        self._end = end
        self._minutes = session_minutes
        self._clock = clock

    async def describe(self, uid: str) -> CategoryView:
        live = await self._sessions.live(uid, now=self._clock())
        if live is None:
            note = "No session is open."
        else:
            note = "A session is open now, for " + (
                "a guest." if live.audience == "guest" else "you."
            )
        return CategoryView(
            id=self.id,
            section=self.section,
            label=self.label,
            what="The build book session open now: its questions and replies, sealed. "
            "Nothing is learned from it.",
            count=0 if live is None else 1,
            unit="sessions",
            retention=f"Until it ends ({self._minutes} minutes at most); then it is deleted "
            "and you're told.",
            where=OURS,
            encrypted_by_jarvis=True,
            export=False,
            delete="none" if live is None else "simple",
            recoverable=False,
            note=note,
            rev=_rev(live.session_id, live.questions) if live else _rev("none"),
        )

    async def export(self, uid: str) -> dict[str, Any] | None:
        return None

    async def delete(self, uid: str) -> int:
        if self._end is not None:
            return await self._end(uid)
        now = self._clock()
        live = await self._sessions.live(uid, now=now)
        if live is None:
            return 0
        await self._sessions.close(uid, live.session_id, reason="privacy", now=now)
        return 1


__all__ = ["SEC_ACTIVITY", "SEC_DOCUMENTS", "BookSealedSource", "BookSessionsSource", "Holder"]
