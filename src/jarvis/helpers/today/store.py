# src/jarvis/helpers/today/store.py
"""Part A's documents (docs/plans/r11-free-helpers.md data model), on the Docs port only.

`{prefix}bills/{uid}`: {uid, prefs, sealed?, rev}. `sealed` is his bills (and any approved
payment's grant) as JSON, encrypted with the keyring purpose `bills` (AES-256-GCM, AAD
`bills/{uid}/v1`), so a blob copied to another owner fails to open. `prefs` (when reminders go,
birthdays on or off) are plain: no keyring means the bills are OFF (`BillsOff`, never kept in
clear) while the choices still work. A `Grant` is what an approved `bill_pay_prepare` leaves: the
bill, the approved amount and due date, and until when it can be shown (10 minutes) — never the
payment itself (the link and the QR are made when shown, never stored); `take_ready` spends it once.

`Claims`: `{prefix}<collection>/{uid}_{hash}`, created in a transaction before a reminder goes, so
it goes once across restarts; released when no channel took it (`SendResult.retry`). The id is
SHA-256 of the owner and the key (a bill, a due date and an offset; or a contact's resource name
and the year): no name, no date, no amount in it. `{uid, at}` only; swept after `keep_days`.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field, replace
from datetime import date, datetime, timedelta
from typing import Any

from jarvis.helpers.today.models import MAX_BILLS, Bill, BillRefused, Prefs
from jarvis.keyring import Keyring
from jarvis.storage.docs import Delete, DocExists, Docs, DocTx, Query

BILLS = "bills"
PURPOSE = "bills"
READY_FOR = timedelta(minutes=10)
MAX_READY = 20
OFF_NOTE = "Bills are off: JARVIS has no token key to keep them encrypted (JARVIS_TOKEN_KEY)."


class BillsOff(RuntimeError):
    """No keyring: bills are never stored in clear, so the feature is off."""


@dataclass(frozen=True)
class Grant:
    """An approved payment that may be shown once, until `until`."""

    until: datetime
    paise: int
    due: date

    def dump(self) -> dict[str, Any]:
        return {"until": self.until.isoformat(), "paise": self.paise, "due": self.due.isoformat()}

    @classmethod
    def load(cls, raw: Any) -> Grant | None:
        try:
            return cls(
                datetime.fromisoformat(raw["until"]),
                int(raw["paise"]),
                date.fromisoformat(raw["due"]),
            )
        except (KeyError, TypeError, ValueError):
            return None


@dataclass(frozen=True)
class Book:
    """What `bills/{uid}` holds, opened. A new Book from `with_*`; never mutated."""

    prefs: Prefs = field(default_factory=Prefs)
    bills: tuple[Bill, ...] = ()
    ready: Mapping[str, Grant] = field(default_factory=dict)
    rev: int = 0

    def with_bills(self, bills: tuple[Bill, ...]) -> Book:
        if len(bills) > MAX_BILLS:
            raise BillRefused(f"JARVIS keeps at most {MAX_BILLS} bills.")
        return replace(self, bills=bills)

    def with_prefs(self, prefs: Prefs) -> Book:
        return replace(self, prefs=prefs)

    def with_ready(self, ready: Mapping[str, Grant]) -> Book:
        return replace(self, ready=dict(ready))


def _iso(at: datetime) -> str:
    return at.isoformat()


def _parse(value: object) -> datetime | None:
    try:
        return datetime.fromisoformat(value) if isinstance(value, str) else None
    except ValueError:
        return None


class BillStore:
    def __init__(self, docs: Docs, keyring: Keyring | None, *, prefix: str = "jarvis_") -> None:
        self._docs = docs
        self._keyring = keyring
        self._prefix = prefix

    @property
    def available(self) -> bool:
        return self._keyring is not None

    def path(self, uid: str) -> str:
        return f"{self._prefix}{BILLS}/{uid}"

    @staticmethod
    def _aad(uid: str) -> str:
        return f"{BILLS}/{uid}/v1"

    def _seal(self, uid: str, book: Book) -> str:
        if self._keyring is None:
            raise BillsOff(OFF_NOTE)
        body = {
            "bills": [b.model_dump(mode="json") for b in book.bills],
            "ready": {k: g.dump() for k, g in book.ready.items()},
        }
        raw = json.dumps(body, separators=(",", ":")).encode()
        return self._keyring.cipher(PURPOSE).encrypt(raw, aad=self._aad(uid))

    def _open(self, uid: str, blob: object) -> tuple[tuple[Bill, ...], dict[str, Grant]]:
        if not isinstance(blob, str) or self._keyring is None:
            return (), {}
        body = json.loads(self._keyring.cipher(PURPOSE).decrypt(blob, aad=self._aad(uid)))
        bills = tuple(Bill.model_validate(b) for b in body.get("bills", []))
        grants = {str(k): Grant.load(v) for k, v in (body.get("ready") or {}).items()}
        return bills, {k: g for k, g in grants.items() if g is not None}

    def _book(self, uid: str, raw: dict[str, Any] | None) -> Book:
        if not raw:
            return Book()
        bills, ready = self._open(uid, raw.get("sealed"))
        return Book(
            prefs=Prefs.model_validate(raw.get("prefs") or {}),
            bills=bills,
            ready=ready,
            rev=int(raw.get("rev", 0)),
        )

    async def book(self, uid: str) -> Book:
        return self._book(uid, await self._docs.get(self.path(uid)))

    def _doc(
        self, uid: str, old: dict[str, Any] | None, book: Book, before: Book
    ) -> dict[str, Any]:
        doc: dict[str, Any] = {"uid": uid, "prefs": book.prefs.model_dump(), "rev": before.rev + 1}
        if book.bills != before.bills or book.ready != before.ready:
            doc["sealed"] = self._seal(uid, book)
        elif old and isinstance(old.get("sealed"), str):
            doc["sealed"] = old["sealed"]  # unchanged (or unreadable without the key): kept as is
        return doc

    async def change(self, uid: str, fn: Callable[[Book], Book]) -> Book:
        path = self.path(uid)

        async def run(tx: DocTx) -> Book:
            old = await tx.get(path)
            before = self._book(uid, old)
            after = fn(before)
            sealed_change = after.bills != before.bills or after.ready != before.ready
            if sealed_change and self._keyring is None:
                raise BillsOff(OFF_NOTE)
            tx.set(path, self._doc(uid, old, after, before))
            return replace(after, rev=before.rev + 1)

        return await self._docs.transaction(run)

    async def make_ready(
        self, uid: str, bill_id: str, *, paise: int, due: date, now: datetime
    ) -> datetime:
        until = now + READY_FOR

        def grant(b: Book) -> Book:
            live = {k: g for k, g in b.ready.items() if g.until > now and k != bill_id}
            live[bill_id] = Grant(until, paise, due)
            newest = sorted(live.items(), key=lambda kv: kv[1].until)[-MAX_READY:]
            return b.with_ready(dict(newest))

        await self.change(uid, grant)
        return until

    async def take_ready(self, uid: str, bill_id: str, now: datetime) -> Grant | None:
        """Spend the grant: it is returned once, within READY_FOR of the approval."""
        taken: list[Grant | None] = []

        def take(b: Book) -> Book:
            g = b.ready.get(bill_id)
            taken.append(g if g is not None and now <= g.until else None)
            return b.with_ready({k: v for k, v in b.ready.items() if k != bill_id})

        if bill_id not in (await self.book(uid)).ready:
            return None
        await self.change(uid, take)
        return taken[-1] if taken else None

    async def exists(self, uid: str) -> bool:
        return await self._docs.get(self.path(uid)) is not None

    async def delete_all(self, uid: str) -> int:
        if await self._docs.get(self.path(uid)) is None:
            return 0
        await self._docs.write([Delete(self.path(uid))])
        return 1


class Claims:
    def __init__(self, docs: Docs, collection: str, *, prefix: str, keep_days: int) -> None:
        self._docs = docs
        self._coll = f"{prefix}{collection}"
        self._keep = timedelta(days=keep_days)

    def path(self, uid: str, key: str) -> str:
        digest = hashlib.sha256(f"{uid}\x1f{key}".encode()).hexdigest()[:40]
        return f"{self._coll}/{uid}_{digest}"

    async def claim(self, uid: str, key: str, now: datetime) -> bool:
        """True when this call made the claim (send now); False when it was already made."""
        path = self.path(uid, key)

        async def run(tx: DocTx) -> bool:
            if await tx.get(path) is not None:
                return False
            tx.create(path, {"uid": uid, "at": _iso(now)})
            return True

        try:
            return await self._docs.transaction(run)
        except DocExists:
            return False

    async def release(self, uid: str, key: str) -> None:
        await self._docs.write([Delete(self.path(uid, key))])

    async def rows(self, uid: str) -> list[tuple[str, dict[str, Any]]]:
        return await self._docs.query(Query(self._coll, where=("uid", uid)))

    async def count(self, uid: str) -> int:
        return len(await self.rows(uid))

    async def sweep(self, uid: str, now: datetime) -> int:
        cutoff = now - self._keep
        old = [
            doc_id
            for doc_id, d in await self.rows(uid)
            if (t := _parse(d.get("at"))) is None or t < cutoff
        ]
        if old:
            await self._docs.write([Delete(f"{self._coll}/{i}") for i in old])
        return len(old)

    async def delete_all(self, uid: str) -> int:
        ids = [doc_id for doc_id, _ in await self.rows(uid)]
        if ids:
            await self._docs.write([Delete(f"{self._coll}/{i}") for i in ids])
        return len(ids)


__all__ = [
    "BILLS",
    "OFF_NOTE",
    "PURPOSE",
    "READY_FOR",
    "BillStore",
    "BillsOff",
    "Book",
    "Claims",
    "Grant",
]
