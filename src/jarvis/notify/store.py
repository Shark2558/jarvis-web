# src/jarvis/notify/store.py
"""Notify storage on the Docs port (R3 D10; Layer 7).

    {prefix}notify/{uid}                  the NotifySettings fields + rev; the VIP list (phone and
                                          email references) is sealed in `vip_blob` (keyring purpose
                                          `faces`, AAD `notify_vip/{uid}/v1`)
    {prefix}notify_held/{uid}             {items:[{kind, at, camera?}]}  <= 50, kinds and times only
    {prefix}notify_rate/{uid}_{YYYYMMDDHH} {urgent, normal, push}  per hour
    {prefix}notify_rate/{uid}_{YYYYMMDD}   {urgent}             per day

A document that can't be read or parsed is `NotifyUnavailable` and is never overwritten. Errors
carry plain words, never the cause's text.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from jarvis.keyring import Keyring
from jarvis.logging import get_logger
from jarvis.notify.models import NotifySettings
from jarvis.storage.docs import Delete, Docs, DocTx, Query
from jarvis.undo.store import owner_ok

log = get_logger(__name__)
MAX_HELD = 50
RATE_KEEP = timedelta(days=3)
UNAVAILABLE = "JARVIS couldn't open your alert settings just now. Try again in a minute."
_FIELDS = ("quiet", "ring_for", "kinds", "names_in_alerts", "snapshot")
VIP_PURPOSE = "faces"  # an existing purpose; the AAD below is the domain tag


class NotifyUnavailable(RuntimeError):
    """Settings or counters can't be read or saved right now (plain words)."""


class NotifyStore:
    def __init__(self, docs: Docs, keyring: Keyring, *, prefix: str = "jarvis_") -> None:
        self._d = docs
        self._ring = keyring
        self._p = prefix

    def _path(self, coll: str, key: str) -> str:
        if coll != "notify_rate" and not owner_ok(key):
            raise ValueError("bad owner id")
        return f"{self._p}{coll}/{key}"

    @staticmethod
    def _aad(uid: str) -> str:
        return f"notify_vip/{uid}/v1"

    def _parse(self, uid: str, doc: dict[str, Any] | None) -> NotifySettings:
        if doc is None:
            return NotifySettings()
        try:
            body: dict[str, Any] = {k: doc[k] for k in _FIELDS if k in doc}
            blob = doc.get("vip_blob")
            if blob is not None:
                raw = self._ring.cipher(VIP_PURPOSE).decrypt(blob, aad=self._aad(uid))
                body["vip"] = json.loads(raw)
            elif doc.get("vip"):  # legacy plaintext: read it, the next save seals it
                body["vip"] = doc["vip"]
            return NotifySettings.model_validate({**body, "rev": doc.get("rev", 0)})
        except Exception:  # noqa: BLE001 - bad shape, wrong key, tampered blob: fail closed
            raise NotifyUnavailable(UNAVAILABLE) from None

    def _dump(self, uid: str, s: NotifySettings) -> dict[str, Any]:
        out = s.model_dump(mode="json")
        vips = out.pop("vip", [])
        if vips:
            plain = json.dumps(vips).encode()
            out["vip_blob"] = self._ring.cipher(VIP_PURPOSE).encrypt(plain, aad=self._aad(uid))
        return out

    async def get(self, uid: str) -> NotifySettings:
        try:
            return self._parse(uid, await self._d.get(self._path("notify", uid)))
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
            cur = self._parse(uid, await tx.get(path))
            new = change(cur).model_copy(update={"rev": cur.rev + 1})
            new = NotifySettings.model_validate(new.model_dump())
            tx.set(path, self._dump(uid, new))
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

    async def held_discard(self, uid: str, items: list[dict[str, str]]) -> None:
        """Remove exactly these items (one occurrence each) after they were delivered; items
        held in the meantime stay."""
        path = self._path("notify_held", uid)

        async def fn(tx: DocTx) -> None:
            doc = await tx.get(path)
            rest = list((doc or {}).get("items") or [])
            for item in items:
                if item in rest:
                    rest.remove(item)
            if rest:
                tx.set(path, {"items": rest})
            elif doc is not None:
                tx.delete(path)

        try:
            await self._d.transaction(fn)
        except Exception as exc:  # noqa: BLE001
            log.warning("held alerts not cleared", extra={"error": type(exc).__name__})
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

    async def take_push(self, uid: str, now: datetime, *, per_hour: int) -> bool:
        """Take one from the owner's hourly push allowance (shared by every instance). Errors
        propagate: the caller fails closed for normal kinds and never asks for urgent ones."""
        if not owner_ok(uid):
            raise ValueError("bad owner id")
        hour = self._path("notify_rate", f"{uid}_{now.astimezone(UTC):%Y%m%d%H}")

        async def fn(tx: DocTx) -> bool:
            h = await tx.get(hour) or {"urgent": 0, "normal": 0}
            if int(h.get("push", 0)) >= per_hour:
                return False
            tx.set(hour, {**h, "push": int(h.get("push", 0)) + 1})
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
