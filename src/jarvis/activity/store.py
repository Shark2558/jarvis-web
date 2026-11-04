# src/jarvis/activity/store.py
"""Activity rows on the Docs port (R1 plan D7; Firestore in prod, MemoryDocs in tests).

Layout:  {prefix}activity/{user_id}/d{YYYYMMDD}/{act_id}   (the owner's LOCAL day at write time)
Per owner by path, so one owner's day or sweep never reads another's. Equality + one order_by
only, no composite index. No Firestore TTL (billed): the scheduler tick sweeps old days.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from datetime import UTC, date, datetime
from typing import Any

from pydantic import ValidationError

from jarvis.activity.models import ACT_ID, ActivityItem
from jarvis.logging import get_logger
from jarvis.storage.docs import Create, Delete, Doc, Docs, Query, Set

log = get_logger(__name__)

_OWNER = re.compile(r"[A-Za-z0-9_.@+-]{1,128}")
_DAY = re.compile(r"\d{8}")
MAX_PER_DAY = 500
SWEEP_BATCHES_PER_DAY = 4  # batches of SWEEP_BATCH rows removed per day per sweep call
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
        self._indexed: set[tuple[str, str]] = set()

    def _col(self, uid: str, day: str) -> str:
        if not owner_ok(uid) or not _DAY.fullmatch(day):
            raise ValueError("not a valid owner or day")
        return f"{self._prefix}activity/{uid}/d{day}"

    def _index(self, uid: str) -> str:
        if not owner_ok(uid):
            raise ValueError("not a valid owner")
        return f"{self._prefix}activity_days/{uid}/days"

    async def add(self, item: ActivityItem, day: str) -> None:
        if not ACT_ID.fullmatch(item.id):
            raise ValueError("not a valid activity id")
        col = self._col(item.user_id, day)
        # the day is listed in an index first (once per process per day), so a sweep can find
        # every day however old: the Docs port cannot list sub-collections
        if (item.user_id, day) not in self._indexed:
            await self._d.write([Set(f"{self._index(item.user_id)}/{day}", {"day": day})])
            self._indexed.add((item.user_id, day))
        await self._d.write([Create(f"{col}/{item.id}", encode(item))])

    async def day(self, uid: str, day: str) -> list[ActivityItem]:
        """The owner's rows for one local day, newest first."""
        if not owner_ok(uid) or not _DAY.fullmatch(day):
            return []
        q = Query(self._col(uid, day), order_by="at", descending=True, limit=MAX_PER_DAY)
        rows = [decode(i, d) for i, d in await self._d.query(q)]
        return [r for r in rows if r is not None and r.user_id == uid]

    async def sweep(self, owners: Sequence[str], *, keep_from: str) -> int:
        """Delete every day of these owners before `keep_from` (YYYYMMDD), however old; returns
        rows removed. At most SWEEP_BATCHES_PER_DAY batches per day per call (the next tick
        carries on; a day is un-indexed only once it is empty). Never raises: one owner or day
        never blocks another."""
        gone = 0
        for uid in owners:
            try:
                days = [d for d, _ in await self._d.query(Query(self._index(uid)))]
            except Exception as exc:  # noqa: BLE001
                log.warning("activity sweep failed", extra={"error": type(exc).__name__})
                continue
            for day in sorted(d for d in days if _DAY.fullmatch(d) and d < keep_from):
                try:
                    gone += await self._sweep_day(uid, day)
                except Exception as exc:  # noqa: BLE001
                    log.warning("activity sweep failed", extra={"error": type(exc).__name__})
        return gone

    async def _sweep_day(self, uid: str, day: str) -> int:
        base, gone = self._col(uid, day), 0
        for _ in range(SWEEP_BATCHES_PER_DAY):
            ids = [i for i, _ in await self._d.query(Query(base, limit=SWEEP_BATCH))]
            if not ids:
                await self._d.write([Delete(f"{self._index(uid)}/{day}")])
                self._indexed.discard((uid, day))
                return gone
            await self._d.write([Delete(f"{base}/{i}") for i in ids])
            gone += len(ids)
        return gone


__all__ = ["ActivityStore", "day_key", "owner_ok"]
