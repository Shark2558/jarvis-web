# src/jarvis/helpers/kitchen/store.py
"""The kitchen's documents on the Docs port (docs/plans/r11-free-helpers.md data model).

    {prefix}kitchen/{uid}             v, kid, blob = AES-GCM(JSON Kitchen) under the keyring's
                                      `kitchen` key, AAD "kitchen/{uid}/v1"; rev, updated_at
    {prefix}spend/{uid}_{yyyymm}      uid, month, v, kid, blob = AES-GCM(JSON SpendMonth) under
                                      `spend`, AAD "spend/{uid}/v1" (the month is checked inside)
    {prefix}spend_scan/{uid}          on, last_at, seen (keyed hashes, at most 500), rev: no text

No keyring: `KitchenOff`, and nothing is written (never in clear). A document that can't be read
or opened raises `KitchenUnavailable` and is never overwritten. Spend keeps 13 months (this one
and the 12 before); the orders of one key (one order, several mails) count once: the first
mail's day, the newest mail's amount; a cancelled order is dropped. Logs carry class names only.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from datetime import datetime
from typing import Any

from pydantic import ValidationError

from jarvis.helpers.kitchen.models import (
    MAX_SEEN,
    Kitchen,
    Order,
    ScanState,
    SpendMonth,
)
from jarvis.helpers.kitchen.receipts import Receipt
from jarvis.integrations.vault import VaultError
from jarvis.keyring import KEY_ID, Keyring
from jarvis.logging import get_logger
from jarvis.notify.quiet import local
from jarvis.storage.docs import Delete, Doc, Docs, DocTx, Query
from jarvis.storage.sessions import safe_id

log = get_logger(__name__)

KEEP_MONTHS = 13
VERSION = 1
KEY_CHARS = 32


class KitchenOff(RuntimeError):
    """No keyring: the kitchen keeps nothing (plain words for the owner)."""

    def __init__(self) -> None:
        super().__init__(
            "The kitchen is off, Sir: JARVIS has no token key to keep your pantry and receipts "
            "sealed."
        )


class KitchenUnavailable(RuntimeError):
    def __init__(self) -> None:
        super().__init__("Your kitchen couldn't be read just now, Sir.")


def _uid(uid: str) -> str:
    if not isinstance(uid, str) or not safe_id(uid):
        raise ValueError("invalid user id")
    return uid


class _Seal:
    """JSON in, AES-GCM out, under one keyring purpose; None keyring = off."""

    def __init__(self, keyring: Keyring | None, purpose: str) -> None:
        self._ring = keyring
        self._purpose = purpose

    @property
    def on(self) -> bool:
        return self._ring is not None

    def ring(self) -> Keyring:
        if self._ring is None:
            raise KitchenOff()
        return self._ring

    def seal(self, aad: str, data: dict[str, Any]) -> str:
        plain = json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode()
        return self.ring().cipher(self._purpose).encrypt(plain, aad=aad)

    def open(self, aad: str, doc: Doc) -> dict[str, Any]:
        try:
            raw = self.ring().cipher(self._purpose).decrypt(str(doc["blob"]), aad=aad)
            data = json.loads(raw)
            if not isinstance(data, dict):
                raise ValueError("not an object")
            return data
        except (KeyError, TypeError, ValueError, VaultError) as exc:
            log.error("a sealed kitchen document didn't open", extra={"error": type(exc).__name__})
            raise KitchenUnavailable() from None


class KitchenStore:
    def __init__(
        self,
        docs: Docs,
        keyring: Keyring | None,
        *,
        prefix: str = "jarvis_",
        now: Callable[[], datetime],
    ) -> None:
        self._docs = docs
        self._seal = _Seal(keyring, "kitchen")
        self._prefix = prefix
        self._now = now

    @property
    def sealed(self) -> bool:
        return self._seal.on

    def _path(self, uid: str) -> str:
        return f"{self._prefix}kitchen/{_uid(uid)}"

    def _decode(self, uid: str, doc: Doc | None) -> Kitchen:
        if doc is None:
            return Kitchen()
        try:
            return Kitchen.model_validate(self._seal.open(f"kitchen/{uid}/v1", doc))
        except ValidationError:
            log.error("the kitchen document is not a kitchen")
            raise KitchenUnavailable() from None

    async def load(self, uid: str) -> Kitchen:
        self._seal.ring()
        try:
            doc = await self._docs.get(self._path(uid))
        except Exception as exc:  # noqa: BLE001 - the store: plain words
            log.warning("kitchen unreadable", extra={"error": type(exc).__name__})
            raise KitchenUnavailable() from None
        return self._decode(uid, doc)

    async def change(self, uid: str, fn: Callable[[Kitchen], Kitchen]) -> Kitchen:
        """Read, change and write back in one transaction (`fn` may raise ValueError)."""
        self._seal.ring()
        path = self._path(uid)

        async def work(tx: DocTx) -> Kitchen:
            raw = await tx.get(path)
            new = fn(self._decode(uid, raw))
            rev = int(raw.get("rev", 0)) + 1 if raw else 1
            blob = self._seal.seal(f"kitchen/{uid}/v1", new.model_dump(mode="json"))
            at = self._now().isoformat()
            tx.set(path, {"v": VERSION, "kid": KEY_ID, "blob": blob, "rev": rev, "updated_at": at})
            return new

        return await self._docs.transaction(work)

    async def delete(self, uid: str) -> int:
        path = self._path(uid)
        if await self._docs.get(path) is None:
            return 0
        await self._docs.write([Delete(path)])
        return 1

    async def exists(self, uid: str) -> bool:
        return await self._docs.get(self._path(uid)) is not None


def _month_of(day: str) -> str:
    return day[:7]


def _keep_from(now: datetime, tz: str) -> str:
    d = local(now, tz)
    months = d.year * 12 + d.month - 1 - (KEEP_MONTHS - 1)
    return f"{months // 12:04d}-{months % 12 + 1:02d}"


class SpendStore:
    def __init__(
        self,
        docs: Docs,
        keyring: Keyring | None,
        *,
        prefix: str = "jarvis_",
        now: Callable[[], datetime],
        tz: str = "Asia/Kolkata",
    ) -> None:
        self._docs = docs
        self._seal = _Seal(keyring, "spend")
        self._prefix = prefix
        self._now = now
        self.tz = tz

    @property
    def sealed(self) -> bool:
        return self._seal.on

    def key(self, uid: str, text: str) -> str:
        """A keyed hash (the `spend` key): the same text of one owner, the same key."""
        return self._seal.ring().mac("spend", f"{_uid(uid)}/{text}")[:KEY_CHARS]

    def _month_path(self, uid: str, month: str) -> str:
        return f"{self._prefix}spend/{_uid(uid)}_{month.replace('-', '')}"

    def _scan_path(self, uid: str) -> str:
        return f"{self._prefix}spend_scan/{_uid(uid)}"

    def _decode(self, uid: str, doc: Doc) -> SpendMonth:
        try:
            got = SpendMonth.model_validate(self._seal.open(f"spend/{uid}/v1", doc))
        except ValidationError:
            raise KitchenUnavailable() from None
        if got.month != doc.get("month"):  # a month document moved to another month
            raise KitchenUnavailable()
        return got

    async def _rows(self, uid: str) -> list[tuple[str, Doc]]:
        q = Query(f"{self._prefix}spend", where=("uid", _uid(uid)))
        return await self._docs.query(q)

    async def months(self, uid: str) -> list[SpendMonth]:
        """His months, newest first (only those inside the 13 kept)."""
        self._seal.ring()
        keep = _keep_from(self._now(), self.tz)
        found = [self._decode(uid, d) for _, d in await self._rows(uid)]
        return sorted((m for m in found if m.month >= keep), key=lambda m: m.month, reverse=True)

    async def apply(self, uid: str, receipts: Sequence[Receipt]) -> int:
        """Add the receipts (one transaction over every month touched); the orders kept."""
        self._seal.ring()
        keep = _keep_from(self._now(), self.tz)
        known = {str(d.get("month")) for _, d in await self._rows(uid)}
        fresh = {r.day.isoformat()[:7] for r in receipts}
        paths = {m: self._month_path(uid, m) for m in sorted(known | fresh)}

        async def work(tx: DocTx) -> int:
            docs = {m: await tx.get(p) for m, p in paths.items()}
            kept = [
                o for m, d in docs.items() if d and m >= keep for o in self._decode(uid, d).orders
            ]
            orders = _merge(kept, [r for r in receipts if r.day.isoformat()[:7] >= keep])
            self._write(tx, uid, paths, docs, orders, keep)
            return len(orders)

        return await self._docs.transaction(work)

    def _write(
        self,
        tx: DocTx,
        uid: str,
        paths: dict[str, str],
        docs: dict[str, Doc | None],
        orders: dict[str, Order],
        keep: str,
    ) -> None:
        at = self._now().isoformat()
        for month, path in paths.items():
            mine = tuple(sorted((o for o in orders.values() if _month_of(o.day) == month),
                                key=lambda o: (o.day, o.key)))  # fmt: skip
            if month < keep or not mine:
                if docs.get(month) is not None:
                    tx.delete(path)
                continue
            blob = self._seal.seal(
                f"spend/{uid}/v1", SpendMonth(month=month, orders=mine).model_dump(mode="json")
            )
            doc = {"uid": uid, "month": month, "v": VERSION, "kid": KEY_ID, "blob": blob}
            tx.set(path, {**doc, "updated_at": at})

    async def scan(self, uid: str) -> ScanState:
        raw = await self._docs.get(self._scan_path(uid))
        if not raw:
            return ScanState()
        try:
            return ScanState.model_validate({k: raw.get(k) for k in ("on", "last_at", "seen", "rev")
                                             if raw.get(k) is not None})  # fmt: skip
        except ValidationError:
            log.error("the receipt scan state is unreadable; receipts stay off")
            return ScanState()

    async def set_scan(self, uid: str, fn: Callable[[ScanState], ScanState]) -> ScanState:
        path = self._scan_path(uid)

        async def work(tx: DocTx) -> ScanState:
            raw = await tx.get(path)
            cur = ScanState.model_validate(raw) if raw else ScanState()
            new = fn(cur)
            data = {**new.model_dump(mode="json"), "seen": list(new.seen[-MAX_SEEN:])}
            out = ScanState.model_validate({**data, "rev": cur.rev + 1})
            tx.set(path, out.model_dump(mode="json"))
            return out

        return await self._docs.transaction(work)

    async def delete_all(self, uid: str) -> int:
        rows = await self._rows(uid)
        ops = [Delete(f"{self._prefix}spend/{i}") for i, _ in rows]
        if await self._docs.get(self._scan_path(uid)) is not None:
            ops.append(Delete(self._scan_path(uid)))
        if ops:
            await self._docs.write(ops)
        return len(ops)


def _merge(existing: Sequence[Order], receipts: Sequence[Receipt]) -> dict[str, Order]:
    """key -> order: the first mail's day, the newest mail's amount; cancelled keys dropped."""
    orders = {o.key: o for o in existing}
    for r in sorted(receipts, key=lambda x: (x.day, x.cancelled)):
        if r.cancelled:
            orders.pop(r.key, None)
            continue
        old = orders.get(r.key)
        day = min(old.day, r.day.isoformat()) if old else r.day.isoformat()
        orders[r.key] = Order(key=r.key, merchant=r.merchant, day=day, paise=r.paise)
    return orders


__all__ = ["KEEP_MONTHS", "KitchenOff", "KitchenStore", "KitchenUnavailable", "SpendStore"]
