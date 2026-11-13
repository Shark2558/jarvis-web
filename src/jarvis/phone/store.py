# src/jarvis/phone/store.py
"""The linked phones and the pending link code (R7 D5; data model `phone_link`, `phone_devices`).

    {prefix}phone_link/{uid}     ONE pending link code: {id, offered_at, code_hash, expires_at,
                                 tries}. The code itself is never stored: only its SHA-256. An
                                 offer (`pl_<12 hex>`) is made first; the code is issued for it
                                 after the passkey check bound to that id (or a fresh sign-in).
    {prefix}phone_devices/{uid}  {phones: [<= 3 Phone], lock: {on, keys}}. Public things only:
                                 the key's public half, the package, the signing fingerprint, the
                                 model word, when it was linked and last seen, its app version and
                                 what the app said it may do. `lock` is the app lock's switch and
                                 the references (`passkey_ref`) of passkeys registered from the app.

A link is ONE transaction: the code is checked (constant time), single use (spent in the same
commit that saves the phone) and refused when it is over, the phone already linked or a fourth.
A wrong code counts a try on every live code (five void it): the code is short, so a stranger's
guesses must cost him, not the code's strength.
"""

from __future__ import annotations

import hmac
import secrets
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from jarvis.logging import get_logger
from jarvis.storage.docs import Delete, Docs, DocTx, Set

log = get_logger(__name__)

CODE_TTL_S = 600  # the code lasts 10 minutes (R1 and R3 pairing rules)
OFFER_TTL_S = 300  # the passkey check for an offer must come within 5 minutes
MAX_TRIES = 5
LINK_COLL, DEVICES_COLL = "phone_link", "phone_devices"
DEVICE_ID = r"^ph_[0-9a-f]{12}$"
OFFER_ID = r"^pl_[0-9a-f]{12}$"


class PhoneStoreUnreadable(RuntimeError):
    """The store answered something that is not a phone document: never read as "no phone"."""


class Phone(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")

    id: str = Field(pattern=DEVICE_ID)
    model: str = Field(min_length=1, max_length=40)
    public_key: str = Field(pattern=r"^04[0-9a-f]{128}$")  # X9.62 uncompressed P-256 point
    package: str = Field(min_length=3, max_length=100)
    fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")  # SHA-256 of the signing certificate
    linked_at: float
    last_seen: float | None = None
    app_version: str = Field(default="", max_length=20)
    android: int | None = Field(default=None, ge=0, le=99)
    version_code: int | None = Field(default=None, ge=0, le=10**9)
    can: dict[str, bool] = Field(default_factory=dict)


class LockPrefs(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")

    on: bool = True  # D21: ON by default, in effect once a passkey was registered from the app
    keys: tuple[str, ...] = ()  # passkey_ref of each passkey registered from the app


@dataclass(frozen=True)
class Owner:
    phones: tuple[Phone, ...] = ()
    lock: LockPrefs = LockPrefs()


LinkResult = Literal["linked", "bad_code", "too_many", "already_linked"]


@dataclass(frozen=True)
class LinkOutcome:
    result: LinkResult
    uid: str = ""
    phone: Phone | None = None


def _owner(raw: dict[str, Any] | None) -> Owner:
    if raw is None:
        return Owner()
    try:
        phones = tuple(Phone.model_validate(p) for p in raw.get("phones") or ())
        lock = LockPrefs.model_validate(raw.get("lock") or {})
    except (ValidationError, TypeError, AttributeError):
        raise PhoneStoreUnreadable("a phone document is not readable") from None
    return Owner(phones, lock)


def _dump(owner: Owner) -> dict[str, Any]:
    return {
        "phones": [p.model_dump() for p in owner.phones],
        "lock": {"on": owner.lock.on, "keys": list(owner.lock.keys)},
    }


def _live_code(doc: dict[str, Any] | None, now: float) -> bool:
    if not doc or not isinstance(doc.get("code_hash"), str):
        return False
    expires, tries = doc.get("expires_at"), doc.get("tries", 0)
    return isinstance(expires, int | float) and expires > now and int(tries or 0) < MAX_TRIES


class PhoneStore:
    def __init__(self, docs: Docs, *, prefix: str, owners: Sequence[str]) -> None:
        self.docs = docs
        self._link = f"{prefix}{LINK_COLL}"
        self._devices = f"{prefix}{DEVICES_COLL}"
        self.owners = tuple(dict.fromkeys(owners))

    def _code_path(self, uid: str) -> str:
        return f"{self._link}/{uid}"

    def _dev_path(self, uid: str) -> str:
        return f"{self._devices}/{uid}"

    # ---- the phones ---------------------------------------------------------------------------
    async def owner(self, uid: str) -> Owner:
        return _owner(await self.docs.get(self._dev_path(uid)))

    async def _change(self, uid: str, fn: Callable[[Owner], Owner | None]) -> Owner | None:
        """Read, change and write the owner's document in one transaction (None: no change)."""

        async def work(tx: DocTx) -> Owner | None:
            new = fn(_owner(await tx.get(self._dev_path(uid))))
            if new is not None:
                tx.set(self._dev_path(uid), _dump(new))
            return new

        return await self.docs.transaction(work)

    async def put_phone(self, uid: str, phone: Phone) -> None:
        """Save one phone (replacing the one with its id)."""

        def put(o: Owner) -> Owner:
            rest = tuple(p for p in o.phones if p.id != phone.id)
            return Owner((*rest, phone), o.lock)

        await self._change(uid, put)

    async def find(self, device_id: str) -> tuple[str, Phone] | None:
        """(owner, phone) for a linked device id; read fresh, so an unlink counts at once."""
        for uid in self.owners:
            for phone in (await self.owner(uid)).phones:
                if hmac.compare_digest(phone.id, device_id):
                    return uid, phone
        return None

    async def fingerprints(self) -> list[str]:
        out: set[str] = set()
        for uid in self.owners:
            out.update(p.fingerprint for p in (await self.owner(uid)).phones)
        return sorted(out)

    async def update_phone(self, uid: str, device_id: str, changes: dict[str, Any]) -> bool:
        def upd(o: Owner) -> Owner | None:
            if not any(p.id == device_id for p in o.phones):
                return None
            phones = tuple(
                p.model_copy(update=changes) if p.id == device_id else p for p in o.phones
            )
            return Owner(phones, o.lock)

        return await self._change(uid, upd) is not None

    async def unlink(self, uid: str, device_id: str) -> Phone | None:
        gone: list[Phone] = []

        def drop(o: Owner) -> Owner | None:
            gone.extend(p for p in o.phones if p.id == device_id)
            if not gone:
                return None
            return Owner(tuple(p for p in o.phones if p.id != device_id), o.lock)

        await self._change(uid, drop)
        return gone[0] if gone else None

    async def unlink_all(self, uid: str) -> int:
        count: list[int] = []

        def drop(o: Owner) -> Owner | None:
            count.append(len(o.phones))
            return Owner((), o.lock) if o.phones else None

        await self._change(uid, drop)
        return count[0] if count else 0

    async def set_lock(self, uid: str, on: bool) -> Owner:
        def upd(o: Owner) -> Owner:
            return Owner(o.phones, LockPrefs(on=on, keys=o.lock.keys))

        new = await self._change(uid, upd)
        assert new is not None
        return new

    async def add_lock_keys(self, uid: str, refs: Sequence[str]) -> Owner:
        def upd(o: Owner) -> Owner:
            keys = tuple(dict.fromkeys((*o.lock.keys, *refs)))[-10:]  # at most 10 passkeys exist
            return Owner(o.phones, LockPrefs(on=o.lock.on, keys=keys))

        new = await self._change(uid, upd)
        assert new is not None
        return new

    # ---- the link code ------------------------------------------------------------------------
    async def offer(self, uid: str, now: float) -> str:
        """A new offer; any earlier code of this owner is void."""
        offer_id = f"pl_{secrets.token_hex(6)}"
        doc = {"id": offer_id, "offered_at": now, "code_hash": None, "expires_at": None, "tries": 0}
        await self.docs.write([Set(self._code_path(uid), doc)])
        return offer_id

    async def issue(
        self, uid: str, offer_id: str, code_hash: str, now: float
    ) -> Literal["issued", "expired", "unknown"]:
        """The code for the offer the passkey check was bound to: once, within OFFER_TTL_S."""

        async def work(tx: DocTx) -> Literal["issued", "expired", "unknown"]:
            doc = await tx.get(self._code_path(uid))
            if not doc or doc.get("code_hash") is not None or doc.get("id") != offer_id:
                return "unknown"
            at = doc.get("offered_at")
            if not isinstance(at, int | float) or now - at > OFFER_TTL_S or now < at:
                tx.delete(self._code_path(uid))
                return "expired"
            tx.set(
                self._code_path(uid),
                {**doc, "code_hash": code_hash, "expires_at": now + CODE_TTL_S, "tries": 0},
            )
            return "issued"

        return await self.docs.transaction(work)

    async def code_left(self, uid: str, now: float) -> int | None:
        doc = await self.docs.get(self._code_path(uid))
        if not _live_code(doc, now):
            return None
        assert doc is not None
        return max(0, int(float(doc["expires_at"]) - now))

    async def link(
        self, code_hash: str, make: Callable[[], Phone], now: float, *, max_phones: int
    ) -> LinkOutcome:
        """The whole link in one transaction: find the live code (constant time), refuse a key
        already linked or a phone too many, save the phone and spend the code together."""

        async def work(tx: DocTx) -> LinkOutcome:
            codes = {u: await tx.get(self._code_path(u)) for u in self.owners}
            owners = {u: _owner(await tx.get(self._dev_path(u))) for u in self.owners}
            uid = ""
            for u, doc in codes.items():
                live = _live_code(doc, now)
                same = hmac.compare_digest(str((doc or {}).get("code_hash") or ""), code_hash)
                if live and same:
                    uid = u
            if not uid:
                return LinkOutcome("bad_code")
            phone = make()
            if any(p.public_key == phone.public_key for o in owners.values() for p in o.phones):
                return LinkOutcome("already_linked", uid)
            mine = owners[uid]
            if len(mine.phones) >= max_phones:
                return LinkOutcome("too_many", uid)
            tx.set(self._dev_path(uid), _dump(Owner((*mine.phones, phone), mine.lock)))
            tx.delete(self._code_path(uid))
            return LinkOutcome("linked", uid, phone)

        return await self.docs.transaction(work)

    async def wrong_try(self, now: float) -> None:
        """A wrong code: one try on every live code; the fifth voids it."""

        async def work(tx: DocTx) -> None:
            docs = {u: await tx.get(self._code_path(u)) for u in self.owners}
            for u, doc in docs.items():
                if not _live_code(doc, now):
                    continue
                assert doc is not None
                tries = int(doc.get("tries") or 0) + 1
                if tries >= MAX_TRIES:
                    tx.delete(self._code_path(u))
                else:
                    tx.set(self._code_path(u), {**doc, "tries": tries})

        await self.docs.transaction(work)

    async def drop_code(self, uid: str) -> None:
        await self.docs.write([Delete(self._code_path(uid))])


__all__ = [
    "CODE_TTL_S",
    "DEVICE_ID",
    "MAX_TRIES",
    "OFFER_ID",
    "OFFER_TTL_S",
    "LinkOutcome",
    "LockPrefs",
    "Owner",
    "Phone",
    "PhoneStore",
    "PhoneStoreUnreadable",
]
