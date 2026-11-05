# src/jarvis/undo/service.py
"""The "Recently deleted" bin (slice 11 D1; Layer 3 service over the Layer 7 store).

keep     before an undo-able delete: the item's snapshot is stored, or `SnapshotFailed` is raised
         and the caller deletes NOTHING (fail-closed). Kept for 30 days.
restore  recreate the item from its snapshot through the restorer for its kind (calendar, to-do;
         registered by the tools that delete them): claimed in a transaction first, so a second
         restore — or two clicks at once — never makes two copies ("already restored"). An
         unknown or expired id, or a kind nothing can restore, is a plain message, never an
         exception. A restorer that fails releases the claim (try again) and raises its own
         plain-words error (a failed release is logged, never raised over it). A restorer that
         finds the original still there (`StillThere`: the delete never happened) makes nothing
         and says so; one that finds it removed for good (`Gone`, R2) drops the entry and the
         error propagates ("It's gone"). Marking the item restored is retried once; if it still
         fails, the restore is reported anyway (the item IS back) and the claim keeps a second
         click busy for 5 minutes. A restored item stays stored (a second restore says "already
         restored") but is no longer listed.
purge    the owner's "Remove now": the copy goes at once (it can no longer be restored).
sweep    the scheduler tick's housekeeping: expired items go (no Firestore TTL: it is billed).
"""

from __future__ import annotations

import contextvars
import json
import secrets
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

from jarvis.logging import get_logger
from jarvis.tools.card import one_line
from jarvis.undo.models import (
    IN_PLACE_KINDS,
    KIND_WORDS,
    RETENTION_DAYS,
    TITLE_LIMIT,
    DeletedItem,
    Kind,
    RestoreOutcome,
    RestoreStatus,
)
from jarvis.undo.store import ClaimResult, DeletedStore, owner_ok

log = get_logger(__name__)

MAX_SNAPSHOT_CHARS = 500_000  # far under Firestore's 1 MiB document limit
NOT_KEPT = (
    "Could not keep a copy in Recently deleted ({why}), so nothing was deleted. Try again shortly."
)
MSG_UNKNOWN = "That isn't in Recently deleted (it may have been cleared). Nothing was restored."
MSG_EXPIRED = (
    f"That was deleted more than {RETENTION_DAYS} days ago, so it can no longer be restored."
)
MSG_PURGE_FAILED = (
    "JARVIS couldn't remove that for good right now, so it is still in Recently deleted. "
    "Try again shortly."
)
MSG_BUSY = "That is being restored right now; check again in a moment."
MSG_UNAVAILABLE = (
    "JARVIS can't restore that right now: Google isn't connected for it. Reconnect Google in "
    "Integrations, then try again."
)
MSG_GONE = "It's gone: it was removed for good, so it can't be restored."


def utcnow() -> datetime:
    return datetime.now(UTC)


class SnapshotFailed(RuntimeError):
    """The copy for Undo could not be kept: the delete must not happen (plain words)."""


class PurgeFailed(RuntimeError):
    """The kind's purger failed: the bin entry stays for the next try (plain words)."""


class StillThere(RuntimeError):
    """The original is still there (its delete never happened): no copy is made (plain words)."""


class Gone(LookupError):
    """R2 review H2: what the entry stands for was removed for good (a privacy wipe, a purge):
    nothing can bring it back. The bin drops the entry; the API answers 404 with `MSG_GONE`."""

    def __init__(self, message: str = MSG_GONE) -> None:
        super().__init__(message)


# Review LOW: while a restore runs, how its restorer tells the bin "the root copy exists now" (the
# bin writes the new id into the claim). A crash after that point can then never lead to a second
# copy: a later click finds a claim that already carries the id. A context variable, so the
# Restorer signature stays as it was.
_made: contextvars.ContextVar[Callable[[str], Awaitable[None]] | None] = contextvars.ContextVar(
    "jarvis_undo_made", default=None
)


async def record_made(new_id: str) -> None:
    """Called by a restorer as soon as the item's root copy exists. Outside a restore: nothing."""
    note = _made.get()
    if note is not None:
        await note(new_id)


@dataclass(frozen=True)
class Restored:
    new_id: str
    note: str = ""


class Restorer(Protocol):
    """Recreates one kind of item from its kept copy (`item.snapshot`; `item.id` keys a restore
    that may be repeated); raises `StillThere` or other plain-words errors. `outside` (plan D8):
    the item was not the owner's own words, so the new copy must carry the outside mark — a
    restore made by JARVIS never turns someone else's words into his."""

    async def restore(self, uid: str, item: DeletedItem, *, outside: bool = False) -> Restored: ...


class Purger(Protocol):
    """Hard-deletes what a bin entry stands for (R2 D8): the vault item and its chunks, a note, a
    thing. Called before the entry goes, on "Remove now" and on the sweep; raises on failure so
    the entry is kept and retried. Must be safe to repeat."""

    async def purge(self, uid: str, item: DeletedItem) -> None: ...


class UndoBin:
    def __init__(
        self,
        store: DeletedStore,
        *,
        clock: Callable[[], datetime] = utcnow,
        retention_days: int = RETENTION_DAYS,
    ) -> None:
        self.store = store
        self._clock = clock
        self._keep_for = timedelta(days=retention_days)
        self._restorers: dict[str, Restorer] = {}
        self._purgers: dict[str, Purger] = {}

    def register(self, kind: Kind, restorer: Restorer, purger: Purger | None = None) -> None:
        """Wiring: the tools that delete a kind also know how to bring it back (and, for kinds
        kept in their own store, how to delete them for good)."""
        self._restorers[kind] = restorer
        if purger is not None:
            self._purgers[kind] = purger

    def now(self) -> datetime:
        return self._clock()

    async def keep(
        self,
        uid: str,
        kind: Kind,
        title: str,
        snapshot: dict[str, Any],
        *,
        owner_authored: bool = False,
        session_id: str | None = None,
        trace_id: str | None = None,
    ) -> DeletedItem:
        """`owner_authored` (plan D8): the deleting tool's verdict on the item, captured now.
        `session_id` / `trace_id`: the conversation and request the delete came from."""
        if not owner_ok(uid):
            raise SnapshotFailed(NOT_KEPT.format(why="no owner"))
        if len(json.dumps(snapshot, ensure_ascii=False, default=str)) > MAX_SNAPSHOT_CHARS:
            raise SnapshotFailed(NOT_KEPT.format(why="it is too large to keep a copy of"))
        now = self._clock()
        item = DeletedItem(
            id=f"del_{secrets.token_hex(10)}",
            user_id=uid,
            kind=kind,
            title=one_line(title, TITLE_LIMIT) or "(no title)",
            snapshot=snapshot,
            deleted_at=now,
            expires_at=now + self._keep_for,
            owner_authored=owner_authored,
            session_id=session_id,
            trace_id=trace_id,
        )
        try:
            await self.store.add(item)
        except Exception as exc:  # noqa: BLE001 — any store failure: nothing gets deleted
            log.error("undo snapshot not stored", extra={"error": type(exc).__name__})
            raise SnapshotFailed(NOT_KEPT.format(why="storage is unavailable")) from exc
        return item

    async def discard(self, uid: str, item_id: str) -> None:
        """The delete did not happen after all: drop its snapshot (best effort, logged)."""
        try:
            await self.store.remove(uid, [item_id])
        except Exception as exc:  # noqa: BLE001
            log.error("undo snapshot not discarded", extra={"error": type(exc).__name__})

    async def recent(self, uid: str) -> list[DeletedItem]:
        """What can still be restored: not expired, not restored already (newest first)."""
        if not owner_ok(uid):
            return []
        now = self._clock()
        return [i for i in await self.store.recent(uid) if not i.expired(now) and not i.restored]

    async def get(self, uid: str, item_id: str) -> DeletedItem | None:
        item = await self.store.get(uid, item_id)
        return item if item is not None and not item.expired(self._clock()) else None

    async def purge(self, uid: str, item_id: str) -> bool:
        """The owner's "Remove now": False when there is no such item of theirs."""
        item = await self.store.get(uid, item_id)
        if item is None or item.restored:  # a restored item is live again: nothing to purge
            return False
        if not await self._purged(uid, item):
            raise PurgeFailed(MSG_PURGE_FAILED)
        await self.store.remove(uid, [item_id])
        return True

    async def _purged(self, uid: str, item: DeletedItem) -> bool:
        """The kind's purger ran (or there is none). False keeps the entry; logged, class only."""
        purger = self._purgers.get(item.kind)
        if purger is None:
            return True
        try:
            await purger.purge(uid, item)
        except Exception as exc:  # noqa: BLE001 - the entry stays; the sweep tries again
            log.error("purge failed", extra={"kind": item.kind, "error": type(exc).__name__})
            return False
        return True

    async def _purgeable(self, uid: str, ids: list[str]) -> list[str]:
        """Of the expired ids, those safe to drop: the kind's purger ran, or the kind has none."""
        ready: list[str] = []
        for item_id in ids:
            item = await self.store.get(uid, item_id)
            if item is None or item.restored or await self._purged(uid, item):
                ready.append(item_id)
        return ready

    async def restore(self, uid: str, item_id: str) -> RestoreOutcome:
        result, item = await self.store.claim(uid, item_id, self._clock())
        if result is not ClaimResult.CLAIMED or item is None:
            return _not_claimed(result, item)
        restorer = self._restorers.get(item.kind)
        if restorer is None:
            await self._release(uid, item.id)
            return _outcome(item, RestoreStatus.UNAVAILABLE, MSG_UNAVAILABLE)
        token = _made.set(lambda new_id: self._note_made(uid, item.id, new_id))
        try:
            done = await restorer.restore(uid, item, outside=not item.owner_authored)
        except StillThere as exc:  # never deleted: nothing to bring back, nothing made
            await self._release(uid, item.id)
            return _outcome(item, RestoreStatus.STILL_THERE, str(exc))
        except Gone:  # removed for good: no try can ever succeed, so the entry goes too
            await self.discard(uid, item.id)
            raise
        except Exception:  # released for another try; the restorer's plain words propagate
            await self._release(uid, item.id)
            raise
        finally:
            _made.reset(token)
        await self._mark_restored(uid, item.id, done.new_id)
        word = KIND_WORDS[item.kind]
        if item.kind in IN_PLACE_KINDS:
            msg = f"Restored the {word}."
        else:
            msg = f"Restored the {word} (it is a new copy: links to the old one no longer work)."
        return _outcome(item, RestoreStatus.RESTORED, msg, new_id=done.new_id, note=done.note)

    async def _note_made(self, uid: str, item_id: str, new_id: str) -> None:
        """Best effort, never raises: the copy exists either way and the restore carries on."""
        try:
            await self.store.note_made(uid, item_id, new_id)
        except Exception as exc:  # noqa: BLE001
            log.error(
                "restored copy not recorded on its claim", extra={"error": type(exc).__name__}
            )

    async def _release(self, uid: str, item_id: str) -> None:
        """End a claim without a restore. Never raises: the caller's own outcome or error
        matters more (a claim left behind goes stale after 5 minutes)."""
        try:
            await self.store.settle(uid, item_id, restored_id=None, now=self._clock())
        except Exception as exc:  # noqa: BLE001
            log.error("undo claim not released", extra={"error": type(exc).__name__})

    async def _mark_restored(self, uid: str, item_id: str, new_id: str) -> None:
        """The item IS back: record it (retried once). If that fails the restore still stands;
        the claim keeps a second click "busy" until it goes stale. Error class only in logs."""
        for attempt in (1, 2):
            try:
                await self.store.settle(uid, item_id, restored_id=new_id, now=self._clock())
                return
            except Exception as exc:  # noqa: BLE001
                log.error(
                    "restored item not marked restored",
                    extra={"error": type(exc).__name__, "attempt": attempt},
                )

    async def sweep(self, owners: Sequence[str]) -> int:
        """Delete expired items of each owner; returns how many went. Never raises."""
        gone = 0
        for uid in owners:
            try:
                spent = await self.store.expired_restored(uid, self._clock())
                await self.store.remove(uid, spent)  # restored: dropped, never purged
                gone += len(spent)
                ids = await self.store.expired(uid, self._clock())
                if self._purgers:
                    ids = await self._purgeable(uid, ids)
                await self.store.remove(uid, ids)
                gone += len(ids)
            except Exception as exc:  # noqa: BLE001 — housekeeping: one owner never blocks another
                log.warning("undo sweep failed for an owner", extra={"error": type(exc).__name__})
        return gone


async def discard_kind(bin_: UndoBin | None, uid: str, kind: Kind) -> int:
    """R2 review H2: after a category is deleted for good (the privacy dashboard), drop this
    owner's Recently deleted entries of that kind; nothing could restore them. Public `UndoBin`
    methods only; best effort (logged, class only), never raises; returns how many went."""
    if bin_ is None:
        return 0
    gone = 0
    try:
        for item in await bin_.recent(uid):
            if item.kind == kind:
                await bin_.discard(uid, item.id)
                gone += 1
    except Exception as exc:  # noqa: BLE001 - the data is gone; entries expire on their own
        log.warning("bin entries not cleared", extra={"kind": kind, "error": type(exc).__name__})
    return gone


def _outcome(
    item: DeletedItem, status: RestoreStatus, message: str, **extra: Any
) -> RestoreOutcome:
    return RestoreOutcome(
        status=status,
        message=message,
        undo_id=item.id,
        kind=item.kind,
        title=item.title,
        owner_authored=item.owner_authored,
        **extra,
    )


def _not_claimed(result: ClaimResult, item: DeletedItem | None) -> RestoreOutcome:
    if item is None:
        return RestoreOutcome(status=RestoreStatus.UNKNOWN, message=MSG_UNKNOWN)
    if result is ClaimResult.RESTORED:
        word = KIND_WORDS[item.kind]
        return _outcome(
            item,
            RestoreStatus.ALREADY_RESTORED,
            f"That {word} was already restored; nothing more to do.",
            new_id=item.restored_id,
        )
    if result is ClaimResult.EXPIRED:
        return _outcome(item, RestoreStatus.EXPIRED, MSG_EXPIRED)
    return _outcome(item, RestoreStatus.BUSY, MSG_BUSY)


__all__ = [
    "MAX_SNAPSHOT_CHARS",
    "MSG_GONE",
    "Gone",
    "PurgeFailed",
    "Purger",
    "Restored",
    "Restorer",
    "SnapshotFailed",
    "StillThere",
    "UndoBin",
    "discard_kind",
    "record_made",
    "utcnow",
]
