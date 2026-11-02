# src/jarvis/undo/store.py
"""The "Recently deleted" bin on the Docs port (slice 11 D1; Firestore in prod, MemoryDocs in
tests).

Layout:  {prefix}deleted_items/{user_id}/items/{undo_id}
         user_id, kind, title, snapshot_json (the item as Google had it, as JSON text: field
         names Firestore would refuse stay inside a string), deleted_at, expires_at (UTC ISO
         strings: they sort as text), restored, restored_at, restored_id, restoring_since.

Per owner by path, so one owner's list or sweep never reads another's. No Firestore TTL policy
(TTL deletes are billed): the scheduler tick sweeps expired items (`UndoBin.sweep`). A new item is
written create-only; a restore is claimed and finished in transactions.
"""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import ValidationError

from jarvis.logging import get_logger
from jarvis.storage.docs import Create, Delete, Doc, Docs, DocTx, Query
from jarvis.undo.models import UNDO_ID, DeletedItem

log = get_logger(__name__)

_OWNER = re.compile(r"[A-Za-z0-9_.@+-]{1,128}")
STALE_CLAIM_S = 300  # a restore that crashed half-way may be tried again after 5 minutes
MAX_LISTED = 50
SWEEP_BATCH = 200


class ClaimResult(StrEnum):
    CLAIMED = "claimed"
    UNKNOWN = "unknown"
    RESTORED = "restored"
    EXPIRED = "expired"
    BUSY = "busy"


def _iso(dt: datetime) -> str:
    return dt.astimezone(UTC).isoformat(timespec="microseconds")


def _when(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    return datetime.fromisoformat(str(value))


def _required(value: Any) -> datetime:
    when = _when(value)
    if when is None:
        raise ValueError("missing time")
    return when


def owner_ok(uid: str) -> bool:
    return bool(_OWNER.fullmatch(uid)) and uid not in {".", ".."}


def encode(item: DeletedItem) -> Doc:
    return {
        "user_id": item.user_id,
        "kind": item.kind,
        "title": item.title,
        "snapshot_json": json.dumps(item.snapshot, ensure_ascii=False, separators=(",", ":")),
        "deleted_at": _iso(item.deleted_at),
        "expires_at": _iso(item.expires_at),
        "restored": item.restored,
        "restored_at": _iso(item.restored_at) if item.restored_at else None,
        "restored_id": item.restored_id,
        "restoring_since": _iso(item.restoring_since) if item.restoring_since else None,
    }


def decode(item_id: str, raw: Doc | None) -> DeletedItem | None:
    if raw is None:
        return None
    try:
        snapshot = json.loads(str(raw.get("snapshot_json") or "{}"))
        return DeletedItem(
            id=item_id,
            user_id=str(raw["user_id"]),
            kind=raw["kind"],
            title=str(raw.get("title") or ""),
            snapshot=snapshot if isinstance(snapshot, dict) else {},
            deleted_at=_required(raw["deleted_at"]),
            expires_at=_required(raw["expires_at"]),
            restored=raw.get("restored") is True,
            restored_at=_when(raw.get("restored_at")),
            restored_id=raw.get("restored_id"),
            restoring_since=_when(raw.get("restoring_since")),
        )
    except (KeyError, ValueError, TypeError, ValidationError):
        log.error("unreadable deleted item", extra={"item": item_id})
        return None


class DeletedStore:
    def __init__(self, docs: Docs, *, prefix: str = "jarvis_") -> None:
        self._d = docs
        self._prefix = prefix

    def _col(self, uid: str) -> str:
        if not owner_ok(uid):
            raise ValueError("not a valid owner id")
        return f"{self._prefix}deleted_items/{uid}/items"

    def _path(self, uid: str, item_id: str) -> str:
        if not UNDO_ID.fullmatch(item_id):
            raise ValueError("not a valid undo id")
        return f"{self._col(uid)}/{item_id}"

    async def add(self, item: DeletedItem) -> None:
        await self._d.write([Create(self._path(item.user_id, item.id), encode(item))])

    async def get(self, uid: str, item_id: str) -> DeletedItem | None:
        if not owner_ok(uid) or not UNDO_ID.fullmatch(item_id):
            return None
        item = decode(item_id, await self._d.get(self._path(uid, item_id)))
        return item if item is not None and item.user_id == uid else None

    async def recent(self, uid: str, limit: int = MAX_LISTED) -> list[DeletedItem]:
        q = Query(self._col(uid), order_by="deleted_at", descending=True, limit=limit)
        rows = [decode(i, d) for i, d in await self._d.query(q)]
        return [r for r in rows if r is not None and r.user_id == uid]

    async def remove(self, uid: str, item_ids: list[str]) -> None:
        if item_ids:
            await self._d.write([Delete(self._path(uid, i)) for i in item_ids])

    async def expired(self, uid: str, now: datetime) -> list[str]:
        """Ids of this owner's items past their expiry (oldest first, one batch)."""
        q = Query(self._col(uid), order_by="expires_at", limit=SWEEP_BATCH)
        cut = _iso(now)
        return [i for i, d in await self._d.query(q) if str(d.get("expires_at", "")) <= cut]

    async def claim(
        self, uid: str, item_id: str, now: datetime
    ) -> tuple[ClaimResult, DeletedItem | None]:
        """Take the item for a restore, in a transaction: only one restore recreates it."""
        if not owner_ok(uid) or not UNDO_ID.fullmatch(item_id):
            return ClaimResult.UNKNOWN, None
        path = self._path(uid, item_id)

        async def fn(tx: DocTx) -> tuple[ClaimResult, DeletedItem | None]:
            item = decode(item_id, await tx.get(path))
            if item is None or item.user_id != uid:
                return ClaimResult.UNKNOWN, None
            if item.restored:
                return ClaimResult.RESTORED, item
            if item.expired(now):
                return ClaimResult.EXPIRED, item
            since = item.restoring_since
            if since is not None and (now - since).total_seconds() < STALE_CLAIM_S:
                return ClaimResult.BUSY, item
            claimed = item.model_copy(update={"restoring_since": now})
            tx.set(path, encode(claimed))
            return ClaimResult.CLAIMED, claimed

        return await self._d.transaction(fn)

    async def settle(
        self, uid: str, item_id: str, *, restored_id: str | None, now: datetime
    ) -> None:
        """End a claim: restored (with the new item's id), or released for another try."""
        path = self._path(uid, item_id)

        async def fn(tx: DocTx) -> None:
            item = decode(item_id, await tx.get(path))
            if item is None:
                return
            done = restored_id is not None
            tx.set(
                path,
                encode(
                    item.model_copy(
                        update={
                            "restoring_since": None,
                            "restored": item.restored or done,
                            "restored_id": restored_id if done else item.restored_id,
                            "restored_at": now if done else item.restored_at,
                        }
                    )
                ),
            )

        await self._d.transaction(fn)


__all__ = ["STALE_CLAIM_S", "ClaimResult", "DeletedStore", "decode", "encode", "owner_ok"]
