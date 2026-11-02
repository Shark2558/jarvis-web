# src/jarvis/undo/service.py
"""The "Recently deleted" bin (slice 11 D1; Layer 3 service over the Layer 7 store).

keep     before an undo-able delete: the item's snapshot is stored, or `SnapshotFailed` is raised
         and the caller deletes NOTHING (fail-closed). Kept for 30 days.
restore  recreate the item from its snapshot through the restorer for its kind (calendar, to-do;
         registered by the tools that delete them): claimed in a transaction first, so a second
         restore — or two clicks at once — never makes two copies ("already restored"). An
         unknown or expired id, or a kind nothing can restore, is a plain message, never an
         exception. A restorer that fails releases the claim (try again) and raises its own
         plain-words error.
sweep    the scheduler tick's housekeeping: expired items go (no Firestore TTL: it is billed).
"""

from __future__ import annotations

import json
import secrets
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

from jarvis.logging import get_logger
from jarvis.tools.card import one_line
from jarvis.undo.models import (
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
MSG_BUSY = "That is being restored right now; check again in a moment."
MSG_UNAVAILABLE = (
    "JARVIS can't restore that right now: Google isn't connected for it. Reconnect Google in "
    "Integrations, then try again."
)


def utcnow() -> datetime:
    return datetime.now(UTC)


class SnapshotFailed(RuntimeError):
    """The copy for Undo could not be kept: the delete must not happen (plain words)."""


@dataclass(frozen=True)
class Restored:
    new_id: str
    note: str = ""


class Restorer(Protocol):
    """Recreates one kind of item from its snapshot (new id); raises plain-words errors.
    `outside` (plan D8): the item was not the owner's own words, so the new copy must carry the
    outside mark — a restore made by JARVIS never turns someone else's words into his."""

    async def restore(
        self, uid: str, snapshot: dict[str, Any], *, outside: bool = False
    ) -> Restored: ...


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

    def register(self, kind: Kind, restorer: Restorer) -> None:
        """Wiring: the tools that delete a kind also know how to bring it back."""
        self._restorers[kind] = restorer

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
    ) -> DeletedItem:
        """`owner_authored` (plan D8): the deleting tool's verdict on the item, captured now."""
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
        if not owner_ok(uid):
            return []
        now = self._clock()
        return [i for i in await self.store.recent(uid) if not i.expired(now)]

    async def get(self, uid: str, item_id: str) -> DeletedItem | None:
        item = await self.store.get(uid, item_id)
        return item if item is not None and not item.expired(self._clock()) else None

    async def restore(self, uid: str, item_id: str) -> RestoreOutcome:
        result, item = await self.store.claim(uid, item_id, self._clock())
        if result is not ClaimResult.CLAIMED or item is None:
            return _not_claimed(result, item)
        restorer = self._restorers.get(item.kind)
        if restorer is None:
            await self.store.settle(uid, item.id, restored_id=None, now=self._clock())
            return _outcome(item, RestoreStatus.UNAVAILABLE, MSG_UNAVAILABLE)
        try:
            done = await restorer.restore(uid, item.snapshot, outside=not item.owner_authored)
        except Exception:  # released for another try; the restorer's plain words propagate
            await self.store.settle(uid, item.id, restored_id=None, now=self._clock())
            raise
        await self.store.settle(uid, item.id, restored_id=done.new_id, now=self._clock())
        word = KIND_WORDS[item.kind]
        msg = f"Restored the {word} (it is a new copy: links to the old one no longer work)."
        return _outcome(item, RestoreStatus.RESTORED, msg, new_id=done.new_id, note=done.note)

    async def sweep(self, owners: Sequence[str]) -> int:
        """Delete expired items of each owner; returns how many went. Never raises."""
        gone = 0
        for uid in owners:
            try:
                ids = await self.store.expired(uid, self._clock())
                await self.store.remove(uid, ids)
                gone += len(ids)
            except Exception as exc:  # noqa: BLE001 — housekeeping: one owner never blocks another
                log.warning("undo sweep failed for an owner", extra={"error": type(exc).__name__})
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
    "Restored",
    "Restorer",
    "SnapshotFailed",
    "UndoBin",
    "utcnow",
]
