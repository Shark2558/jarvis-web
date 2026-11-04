# src/jarvis/activity/store.py
"""Activity rows on the Docs port (R1 plan D7; Firestore in prod, MemoryDocs in tests).

Layout:  {prefix}activity/{user_id}/d{YYYYMMDD}/{act_id}   (the owner's LOCAL day at write time)
Per owner by path, so one owner's day or sweep never reads another's. Equality + one order_by
only, no composite index. No Firestore TTL (billed): the scheduler tick sweeps old days.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from datetime import UTC, date, datetime, timedelta
from typing import Any

from pydantic import ValidationError

from jarvis.activity.models import ACT_ID, ActivityItem
from jarvis.logging import get_logger
from jarvis.storage.docs import Create, Delete, Doc, Docs, Query

log = get_logger(__name__)

_OWNER = re.compile(r"[A-Za-z0-9_.@+-]{1,128}")
_DAY = re.compile(r"\d{8}")
MAX_PER_DAY = 500
SWEEP_LOOKBACK_DAYS = 14  # days before the cutoff a sweep still looks at (a missed tick is caught)
SWEEP_BATCH = 500


def owner_ok(uid: str) -> bool:
    return bool(_OWNER.fullmatch(uid)) and uid not in {".", ".."}


def day_key(d: date) -> str:
    return d.strftime("%Y%m%d")


def _iso(dt: datetime) -> str:
    return dt.astimezone(UTC).isoformat(timespec="microseconds")


def encode(item: ActivityItem) -> Doc:
    data: dict[str, Any] = item.model_dump(exclude={"id"})
    data["at"] = _iso(item.at)
    return data


def decode(item_id: str, raw: Doc) -> ActivityItem | None:
    try:
        at = raw["at"]
        when = at if isinstance(at, datetime) else datetime.fromisoformat(str(at))
        if when.tzinfo is None:
            when = when.replace(tzinfo=UTC)
        return ActivityItem(**{**raw, "id": item_id, "at": when})
    except (KeyError, ValueError, TypeError, ValidationError):
        log.error("unreadable activity row")
        return None


class ActivityStore:
    def __init__(self, docs: Docs, *, prefix: str = "jarvis_") -> None:
        self._d = docs
        self._prefix = prefix

    def _col(self, uid: str, day: str) -> str:
        if not owner_ok(uid) or not _DAY.fullmatch(day):
            raise ValueError("not a valid owner or day")
        return f"{self._prefix}activity/{uid}/d{day}"

    async def add(self, item: ActivityItem, day: str) -> None:
        if not ACT_ID.fullmatch(item.id):
            raise ValueError("not a valid activity id")
        await self._d.write([Create(f"{self._col(item.user_id, day)}/{item.id}", encode(item))])

    async def day(self, uid: str, day: str) -> list[ActivityItem]:
        """The owner's rows for one local day, newest first."""
        if not owner_ok(uid) or not _DAY.fullmatch(day):
            return []
        q = Query(self._col(uid, day), order_by="at", descending=True, limit=MAX_PER_DAY)
        rows = [decode(i, d) for i, d in await self._d.query(q)]
        return [r for r in rows if r is not None and r.user_id == uid]

    async def sweep(self, owners: Sequence[str], *, keep_from: str) -> int:
        """Delete this owner's days before `keep_from` (YYYYMMDD); returns rows removed. Never
        raises: housekeeping, one owner or day never blocks another."""
        gone = 0
        cut = datetime.strptime(keep_from, "%Y%m%d").date()
        for uid in owners:
            for back in range(1, SWEEP_LOOKBACK_DAYS + 1):
                day = day_key(cut - timedelta(days=back))
                try:
                    q = Query(self._col(uid, day), limit=SWEEP_BATCH)
                    ids = [i for i, _ in await self._d.query(q)]
                    if ids:
                        base = self._col(uid, day)
                        await self._d.write([Delete(f"{base}/{i}") for i in ids])
                        gone += len(ids)
                except Exception as exc:  # noqa: BLE001
                    log.warning("activity sweep failed", extra={"error": type(exc).__name__})
        return gone


__all__ = ["ActivityStore", "day_key", "owner_ok"]
