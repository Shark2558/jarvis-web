# src/jarvis/buildbook/sealer.py
"""Seal the release this server runs, once (R6 D7; builder B; L7 vault, L8 notify).

`BookSealer.ensure(uid)` for the primary owner: the current release (`BookSource.current()`) not
yet in the sealed index -> take the lease `{prefix}book_lease/{uid}` (120 s, a transaction) ->
look again under the lease (sealed meanwhile? held by Privacy meanwhile?) -> refuse a book that
names an owner e-mail or its local part (D3) -> make room under `book_max_total_mb` (the oldest
goes first, one at a time, the newest always stays; a release that can't fit even so is refused
and nothing is pruned) -> seal -> prune to 3 -> audit `book_seal` (ids and MB only) -> ONE
`book_sealed` notice. Anything that stops it, a crash included -> `book_seal_failed` once per
release and cause, never repeated (not even after a restart); the next run simply tries again. It
runs from the `book_seal` TickJob and inside `GET /v1/book` (`ensure_bounded`: one shared run per
owner, a request waits at most 20 s), NEVER at start-up: a Cloud Run candidate that fails gets no
traffic, so it never seals a release that didn't go live.

The lease document (`seal_state.SealState`) also remembers what was told (claimed before a notice
goes) and what Privacy held. No content goes in it, nor in a log or a notice (`seal_words`).
"""

from __future__ import annotations

import asyncio
import datetime as dt
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Literal

from jarvis.buildbook.model import KEEP, MIB, FileKind, Release, SealedRelease
from jarvis.buildbook.ports import BookError, BookSource, BookUnavailable, BookVault, VaultTampered
from jarvis.buildbook.seal_index import KINDS
from jarvis.buildbook.seal_notices import Audit, SealNotices
from jarvis.buildbook.seal_state import SealHeld, SealState, held_of
from jarvis.buildbook.seal_words import (
    FAILED,
    INDEX_TAMPERED,
    OVER_LIMIT,
    PERSONAL,
    READ_TAMPERED,
    UNBUILT,
    holds_owner_email,
)
from jarvis.logging import get_logger
from jarvis.notify.ports import Notifier
from jarvis.storage.docs import Docs
from jarvis.ticks import FAILED_COUNT

log = get_logger(__name__)

BOUNDED_S = 20.0  # a request's wait (Cloud Run gives CPU only during a request)
JOB_BUDGET_S = 45.0
State = Literal["none", "unbuilt", "failed", "held", "busy", "sealing", "kept", "sealed"]


def _now() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


@dataclass(frozen=True)
class SealOutcome:
    state: State
    release: str | None = None
    kept: int = 0
    removed: tuple[str, ...] = ()


class BookSealer:
    def __init__(
        self,
        source: BookSource,
        vault: BookVault,
        docs: Docs,
        *,
        notifier: Notifier | None,
        audit: Audit | None,
        owner_emails: Sequence[str] = (),
        honorific: str = "Sir",
        limit_mb: int = 60,
        prefix: str = "jarvis_",
        clock: Callable[[], dt.datetime] = _now,
        keep: int = KEEP,
    ) -> None:
        self._source = source
        self._vault = vault
        self._emails = tuple(owner_emails)
        self._limit = limit_mb * MIB
        self._limit_mb = limit_mb
        self._st = SealState(docs, prefix=prefix, clock=clock)
        self._say = SealNotices(self._st, notifier=notifier, audit=audit, honorific=honorific)
        self._clock = clock
        self._keep = keep  # D5: fixed at 3; a parameter only so the seal eval's control can vary it
        self._inflight: dict[str, asyncio.Task[SealOutcome]] = {}

    # ---- the run -------------------------------------------------------------------------------

    async def ensure(self, uid: str) -> SealOutcome:
        """Seal the current release for `uid` if it isn't yet. Never raises a BookError."""
        release = self._source.current()
        if release is None:
            return SealOutcome("none")
        try:
            if not release.ok:
                await self._say.fail_once(uid, release.id, self._say.words(UNBUILT, release))
                return SealOutcome("unbuilt", release.id)
            return await self._ensure_good(uid, release)
        except SealHeld:
            return SealOutcome("held", release.id)
        except BookError as exc:
            log.error("book seal check failed", extra={"error": type(exc).__name__})
            await self._say.fail_quietly(uid, release)
            return SealOutcome("failed", release.id)

    async def _ensure_good(self, uid: str, release: Release) -> SealOutcome:
        try:
            sealed = await self._vault.releases(uid)
        except VaultTampered:
            await self._say.fail_once(uid, "index", self._say.words(INDEX_TAMPERED))
            return SealOutcome("failed", release.id)
        if any(r.id == release.id for r in sealed):
            return await self._kept(uid, release, len(sealed))
        if await self._held(uid, release):
            return SealOutcome("held", release.id)
        holder = await self._st.lease(uid)
        if holder is None:
            return SealOutcome("busy", release.id)
        try:
            return await self._seal_leased(uid, release)
        finally:
            await self._st.unlease(uid, holder)

    async def _held(self, uid: str, release: Release) -> bool:
        return held_of(await self._st.read(uid)) == release.id

    async def _kept(self, uid: str, release: Release, count: int) -> SealOutcome:
        removed = await self._prune(uid)  # also retries chunk deletes that failed before
        kept = count - len(removed)
        await self._say.tell_if_untold(uid, release, kept)
        return SealOutcome("kept", release.id, kept=kept, removed=removed)

    async def _prune(self, uid: str) -> tuple[str, ...]:
        try:
            return await self._vault.prune(uid, keep=self._keep)
        except BookError as exc:
            log.warning("book prune deferred", extra={"error": type(exc).__name__})
            return ()

    async def _seal_leased(self, uid: str, release: Release) -> SealOutcome:
        sealed = await self._vault.releases(uid)  # look again: another run may have sealed it
        if any(r.id == release.id for r in sealed):
            return await self._kept(uid, release, len(sealed))
        if await self._held(uid, release):  # Privacy deleted while the lease was being taken
            return SealOutcome("held", release.id)
        try:
            files: dict[FileKind, bytes] = {k: self._source.read(k) for k in KINDS}
        except BookUnavailable:
            await self._say.fail_once(uid, release.id, self._say.words(FAILED, release))
            return SealOutcome("failed", release.id)
        if holds_owner_email(files["book"], self._emails):
            log.error("book seal refused: the book names an owner address")
            words = self._say.words(PERSONAL, release)
            await self._say.fail_once(uid, f"{release.id}:personal", words)
            return SealOutcome("failed", release.id)
        removed = await self._store(uid, release, files, sealed)
        if removed is None:
            return SealOutcome("failed", release.id)
        kept = len(sealed) + 1 - len(removed)
        await self._say.audit_seal(release, removed, sum(len(b) for b in files.values()))
        await self._say.tell(uid, release, kept)
        return SealOutcome("sealed", release.id, kept=kept, removed=removed)

    def _room(self, sealed: Sequence[SealedRelease], incoming: int) -> int | None:
        """How many of the newest sealed releases stay so the new one fits under the limit: all
        of them when they fit, else fewer (the oldest go first, never the newest); None when
        even the newest alone leaves no room (nothing is pruned for a seal that can't fit)."""
        sizes = [r.size for r in sealed]  # newest first
        if sum(sizes) + incoming <= self._limit:
            return len(sizes)
        for stay in range(min(len(sizes), self._keep - 1), 0, -1):
            if sum(sizes[:stay]) + incoming <= self._limit:
                return stay
        return None

    async def _store(
        self,
        uid: str,
        release: Release,
        files: Mapping[FileKind, bytes],
        sealed: Sequence[SealedRelease],
    ) -> tuple[str, ...] | None:
        """Make room, seal, prune to 3: the release ids that went, or None when it failed."""
        stay = self._room(sealed, sum(len(b) for b in files.values()))
        if stay is None:
            words = self._say.words(OVER_LIMIT, release, mb=str(self._limit_mb))
            await self._say.fail_once(uid, f"{release.id}:limit", words)
            return None
        try:
            early = await self._vault.prune(uid, keep=stay) if stay < len(sealed) else ()
            await self._vault.seal(uid, release, files, now=self._clock())
        except SealHeld:
            raise
        except VaultTampered:
            await self._say.fail_once(uid, "index", self._say.words(INDEX_TAMPERED))
            return None
        except BookError as exc:
            log.error("book seal failed", extra={"error": type(exc).__name__})
            await self._say.fail_once(uid, release.id, self._say.words(FAILED, release))
            return None
        return early + await self._prune(uid)

    async def _guarded(self, uid: str) -> SealOutcome:
        try:
            return await self.ensure(uid)
        except Exception as exc:  # noqa: BLE001 - a run never takes a request or the tick down
            log.error("book seal run failed", extra={"error": type(exc).__name__})
        try:
            release = self._source.current()
        except Exception:  # noqa: BLE001 - no release to name: logged above
            return SealOutcome("failed")
        await self._say.fail_quietly(uid, release)
        return SealOutcome("failed", None if release is None else release.id)

    async def ensure_bounded(self, uid: str, *, within_s: float = BOUNDED_S) -> SealOutcome:
        """`ensure` shared by every caller in this process, waited on at most `within_s`; past
        that the run goes on and the answer is "sealing" (ask again)."""
        task = self._inflight.get(uid)
        if task is None or task.done():
            task = asyncio.ensure_future(self._guarded(uid))
            self._inflight[uid] = task

            def forget(done: asyncio.Task[SealOutcome], uid: str = uid) -> None:
                if self._inflight.get(uid) is done:
                    del self._inflight[uid]

            task.add_done_callback(forget)
        try:
            return await asyncio.wait_for(asyncio.shield(task), within_s)
        except TimeoutError:
            return SealOutcome("sealing")

    # ---- Privacy and reads -----------------------------------------------------------------------

    async def hold(self, uid: str) -> str | None:
        """Privacy -> Delete: don't seal the current release again (the next one seals)."""
        release = self._source.current()
        if release is None or not release.ok:
            return None
        await self._st.set(uid, "held", release.id)
        return release.id

    async def report_tampered(self, uid: str, rid: str, label: str) -> None:
        """A sealed read failed its check (the routes): `book_seal_failed` once per release."""
        text = self._say.words(READ_TAMPERED, label=label, id=rid)
        try:
            await self._say.fail_once(uid, f"{rid}:read", text)
        except BookError:
            log.warning("book tamper notice deferred")


class BookSealJob:
    """D7's `book_seal` on the existing tick and R5.1's 5-minute watchdog: the PRIMARY owner only
    (`identity.primary_user_id`), whatever owners the tick passes."""

    name = "book_seal"
    budget_s = JOB_BUDGET_S

    def __init__(self, sealer: BookSealer, uid: str) -> None:
        self._sealer = sealer
        self._uid = uid

    async def run(self, owners: Sequence[str]) -> dict[str, int]:
        out = await self._sealer.ensure_bounded(self._uid, within_s=self.budget_s - 5)
        return {
            "sealed": int(out.state == "sealed"),
            "removed": len(out.removed),
            FAILED_COUNT: int(out.state == "failed"),
        }


__all__ = [  # Audit and holds_owner_email are re-exported (INTEGRATION-B names them here)
    "BOUNDED_S",
    "JOB_BUDGET_S",
    "Audit",
    "BookSealJob",
    "BookSealer",
    "SealOutcome",
    "holds_owner_email",
]
