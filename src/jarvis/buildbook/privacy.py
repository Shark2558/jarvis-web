# src/jarvis/buildbook/privacy.py
"""The build book's rows in the privacy dashboard (R6 D16; builder B; cross-cutting security).
I1 registers them in `privacy_sources`.

- `BookSealedSource` (`book_sealed`, Documents): the sealed releases, their MB of the limit,
  encrypted by JARVIS. Export: each release's id, label, commit, dates and MB (the code itself
  downloads from Book). Delete needs the passkey (`privacy_delete`; nothing brings them back): the
  current release is held first so the sealer doesn't seal it again at its next run (the next
  release seals as usual), then every release is crypto-shredded (`BookVault.delete_all`). An
  index that fails its check is never read, but it is still shown (count unknown) and deletable,
  so the owner is never left with code he can't remove.
- `BookSessionsSource` (`book_sessions`, Activity and messages): the live book session, if any.
  Delete is simple: it ends the session and wipes it through the book service (D14's steps, the
  audit line and the notice; I1 passes C's `BookService` as `end`), or, without one, closes it
  with reason `privacy`. Nothing to export: a session's turns are deleted when it ends.
- `BookSettingsSource` (`book_settings`, Settings and safety): the creator name the closing credit
  names (D13 `{by}`, the owner's own name) and the other Book choices. Export: all of them. Delete
  is simple and clears the name only: the other choices stay (a privacy click never changes how
  the talk-through behaves). Not one of D16's two rows: added so the name is exported and
  deletable like every other personal datum (review, security 7).
No row ever shows book text, a question, a key, a token or the creator name itself.
"""

from __future__ import annotations

import datetime as dt
import hashlib
from collections.abc import Awaitable, Callable
from typing import Any, Protocol

from jarvis.buildbook.model import MIB
from jarvis.buildbook.owner import BookSettingsStore
from jarvis.buildbook.ports import BookSessions, BookVault, VaultTampered
from jarvis.privacy.ports import CategoryView

# the dashboard's own section names (privacy/sources.py; pinned equal by the tests)
SEC_DOCUMENTS = "Documents"
SEC_ACTIVITY = "Activity and messages"
SEC_SAFETY = "Settings and safety"
OURS = "Firestore, encrypted by JARVIS"
SEALED_WHAT = "Each release's build book and that release's source code, sealed in your vault."
SEALED_KEPT = "The last 3 releases; an older one is deleted when a new release is sealed."
UNREADABLE = "They can't be read: they failed their integrity check. Delete removes them all."


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
        try:
            releases = await self._vault.releases(uid)
        except VaultTampered:
            return self._unreadable()
        size = sum(r.size for r in releases)
        return CategoryView(
            id=self.id,
            section=self.section,
            label=self.label,
            what=SEALED_WHAT,
            count=len(releases),
            unit="releases",
            size_hint=f"{round(size / MIB, 1)} MB of {self._limit_mb} MB",
            retention=SEALED_KEPT,
            where=OURS,
            encrypted_by_jarvis=True,
            export=True,
            delete="passkey" if releases else "none",
            recoverable=False,
            note="Deleting them also stops this release being sealed again; the next release is.",
            rev=_rev(",".join(r.id for r in releases), size),
        )

    def _unreadable(self) -> CategoryView:
        """The index failed its check: nothing is read, but the owner can still delete it all."""
        return CategoryView(
            id=self.id,
            section=self.section,
            label=self.label,
            what=SEALED_WHAT,
            count=None,
            unit="releases",
            retention=SEALED_KEPT,
            where=OURS,
            encrypted_by_jarvis=True,
            export=False,
            delete="passkey",
            recoverable=False,
            note=UNREADABLE,
            rev=_rev("unreadable"),
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


class BookSettingsSource:
    id = "book_settings"
    section = SEC_SAFETY
    label = "Book settings"

    def __init__(self, store: BookSettingsStore) -> None:
        self._store = store

    async def describe(self, uid: str) -> CategoryView:
        named = bool((await self._store.get(uid)).creator_name)
        return CategoryView(
            id=self.id,
            section=self.section,
            label=self.label,
            what="The creator name the build book's closing credit names, and your other Book "
            "choices (the show's voice, the talk-through and its brain).",
            count=1 if named else 0,
            unit="names",
            retention="Until you change or delete it.",
            where="Firestore",
            export=True,
            delete="simple" if named else "none",
            recoverable=True,
            note="Delete clears the creator name only; your other Book choices stay.",
            rev=_rev("named" if named else "none"),
        )

    async def export(self, uid: str) -> dict[str, Any] | None:
        return (await self._store.get(uid)).model_dump()

    async def delete(self, uid: str) -> int:
        return int(await self._store.clear_name(uid))


__all__ = [
    "SEC_ACTIVITY",
    "SEC_DOCUMENTS",
    "SEC_SAFETY",
    "BookSealedSource",
    "BookSessionsSource",
    "BookSettingsSource",
    "Holder",
]
