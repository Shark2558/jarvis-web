# src/jarvis/notify/store.py
"""Notify storage on the Docs port (R3 D10; Layer 7).

    {prefix}notify/{uid}                  the NotifySettings fields + rev (no personal text)
    {prefix}notify_held/{uid}             {items:[{kind, at, camera?}]}  <= 50, kinds and times only
    {prefix}notify_rate/{uid}_{YYYYMMDDHH} {urgent, normal}     per hour
    {prefix}notify_rate/{uid}_{YYYYMMDD}   {urgent}             per day

A document that can't be read or parsed is `NotifyUnavailable` and is never overwritten. Errors
carry plain words, never the cause's text.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from pydantic import ValidationError

from jarvis.logging import get_logger
from jarvis.notify.models import NotifySettings
from jarvis.storage.docs import Delete, Docs, DocTx, Query
from jarvis.undo.store import owner_ok

log = get_logger(__name__)
MAX_HELD = 50
RATE_KEEP = timedelta(days=3)
UNAVAILABLE = "JARVIS couldn't open your alert settings just now. Try again in a minute."
_FIELDS = ("quiet", "ring_for", "kinds", "names_in_alerts", "snapshot", "vip")


class NotifyUnavailable(RuntimeError):
    """Settings or counters can't be read or saved right now (plain words)."""


class NotifyStore:
    def __init__(self, docs: Docs, *, prefix: str = "jarvis_") -> None:
        self._d = docs
        self._p = prefix

    def _path(self, coll: str, key: str) -> str:
        if coll != "notify_rate" and not owner_ok(key):
            raise ValueError("bad owner id")
        return f"{self._p}{coll}/{key}"

    @staticmethod
    def _parse(doc: dict[str, Any] | None) -> NotifySettings:
        if doc is None:
            return NotifySettings()
        try:
            body = {k: doc[k] for k in _FIELDS if k in doc}
            return NotifySettings.model_validate({**body, "rev": doc.get("rev", 0)})
        except (ValidationError, TypeError, ValueError):
            raise NotifyUnavailable(UNAVAILABLE) from None

    @staticmethod
    def _dump(s: NotifySettings) -> dict[str, Any]:
        return s.model_dump(mode="json")

    async def get(self, uid: str) -> NotifySettings:
        try:
            return self._parse(await self._d.get(self._path("notify", uid)))
        except NotifyUnavailable:
            raise
        except Exception as exc:  # noqa: BLE001
            log.warning("notify settings unreadable", extra={"error": type(exc).__name__})
            raise NotifyUnavailable(UNAVAILABLE) from None

    async def update(
        self, uid: str, change: Callable[[NotifySettings], NotifySettings]
    ) -> NotifySettings:
        """Read, change, write (rev + 1) in one transaction. The change may raise ValueError."""
        path = self._path("notify", uid)

        async def fn(tx: DocTx) -> NotifySettings:
            cur = self._parse(await tx.get(path))
            new = change(cur).model_copy(update={"rev": cur.rev + 1})
            new = NotifySettings.model_validate(new.model_dump())
            tx.set(path, self._dump(new))
            return new

        try:
            return await self._d.transaction(fn)
        except (NotifyUnavailable, ValueError):
            raise
        except Exception as exc:  # noqa: BLE001
            log.warning("notify settings not saved", extra={"error": type(exc).__name__})
            raise NotifyUnavailable(UNAVAILABLE) from None

    async def reset(self, uid: str) -> None:
        await self._d.write([Delete(self._path("notify", uid))])

    # ---- held alerts -------------------------------------------------------------------

    async def held_add(self, uid: str, item: dict[str, str]) -> int:
        """Keep one held alert (kind, time, camera id). The newest 50 stay. Returns the count."""
        path = self._path("notify_held", uid)

        async def fn(tx: DocTx) -> int:
            doc = await tx.get(path)
            items = list((doc or {}).get("items") or [])
            items.append(item)
            items = items[-MAX_HELD:]
            tx.set(path, {"items": items})
            return len(items)

        try:
            return await self._d.transaction(fn)
        except Exception as exc:  # noqa: BLE001
            log.warning("held alert not kept", extra={"error": type(exc).__name__})
            raise NotifyUnavailable(UNAVAILABLE) from None

    async def held_list(self, uid: str) -> list[dict[str, str]]:
        doc = await self._d.get(self._path("notify_held", uid))
        return list((doc or {}).get("items") or [])

    async def held_take(self, uid: str) -> list[dict[str, str]]:
        """All held alerts, removed in the same transaction (a crash can't send them twice)."""
        path = self._path("notify_held", uid)

        async def fn(tx: DocTx) -> list[dict[str, str]]:
            doc = await tx.get(path)
            items = list((doc or {}).get("items") or [])
            if items:
                tx.delete(path)
            return items

        try:
            return await self._d.transaction(fn)
        except Exception as exc:  # noqa: BLE001
            log.warning("held alerts not read", extra={"error": type(exc).__name__})
            raise NotifyUnavailable(UNAVAILABLE) from None

    async def held_owners(self) -> list[str]:
        rows = await self._d.query(Query(self._p + "notify_held"))
        return [uid for uid, d in rows if d.get("items")]

    # ---- the urgent bucket -------------------------------------------------------------

    async def take_urgent(self, uid: str, now: datetime, *, per_hour: int, per_day: int) -> bool:
        """Take one from the urgent allowance (its own bucket). Errors propagate: the caller
        fails OPEN for urgent kinds with an in-process cap."""
        if not owner_ok(uid):
            raise ValueError("bad owner id")
        at = now.astimezone(UTC)
        hour = self._path("notify_rate", f"{uid}_{at:%Y%m%d%H}")
        day = self._path("notify_rate", f"{uid}_{at:%Y%m%d}")

        async def fn(tx: DocTx) -> bool:
            h = await tx.get(hour) or {"urgent": 0, "normal": 0}
            d = await tx.get(day) or {"urgent": 0}
            if int(h.get("urgent", 0)) >= per_hour or int(d.get("urgent", 0)) >= per_day:
                return False
            tx.set(hour, {**h, "urgent": int(h.get("urgent", 0)) + 1})
            tx.set(day, {"urgent": int(d.get("urgent", 0)) + 1})
            return True

        return await self._d.transaction(fn)

    async def sweep(self, now: datetime) -> int:
        cutoff = f"{now.astimezone(UTC) - RATE_KEEP:%Y%m%d}"
        ops = [
            Delete(f"{self._p}notify_rate/{key}")
            for key, _ in await self._d.query(Query(self._p + "notify_rate"))
            if key.rsplit("_", 1)[-1][:8] < cutoff
        ]
        if ops:
            await self._d.write(ops)
        return len(ops)


__all__ = ["MAX_HELD", "NotifyStore", "NotifyUnavailable"]
