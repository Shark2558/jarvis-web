# src/jarvis/helpers/house/store.py
"""Part B's storage on the Docs port (docs/plans/r11-free-helpers.md data model).

- `chores/{uid}` and `maintenance/{uid}`: his chores and upkeep items, plain (his own labels; no
  place, no outside text). Changed only in a transaction, so a route and a tool never race.
- `house_told/{uid}_{key}`: a reminder's claim, `key` the SHA-256 of (uid, tag, what, when) and
  the doc `{uid, tag, at}` only: created in a transaction BEFORE the send, released when no
  channel took it (`SendResult.retry`), swept after 30 days. Tags: chore, upkeep, wx, cap, breach.
- `outside/{uid}`: his place and the feeds' bookkeeping, sealed with the keyring purpose
  `alerts_place` (AAD `outside/{uid}/v1`). No keyring: `OutsideOff` (never kept in clear). The
  doc in clear holds only `uid`, `rev` and the blob.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any, TypeVar

from pydantic import BaseModel

from jarvis.helpers.house.models import MAX_CHORES, MAX_UPKEEP, Chore, Outside, Upkeep
from jarvis.keyring import Keyring
from jarvis.storage.docs import Delete, Docs, DocTx, Query

M = TypeVar("M", bound=BaseModel)
CLAIM_KEEP = timedelta(days=30)
PURPOSE = "alerts_place"
HOUSE_TAGS = ("chore", "upkeep")
PLACE_TAGS = ("wx", "cap", "breach")
OFF_WORDS = (
    "Weather and alerts are off on this server: it has no token key, so your place can't be kept "
    "sealed."
)


class OutsideOff(RuntimeError):
    """No keyring: his place is never kept, so weather, disaster alerts and breach notices are
    off (plain words)."""

    def __init__(self) -> None:
        super().__init__(OFF_WORDS)


def claim_key(uid: str, tag: str, ident: str) -> str:
    return hashlib.sha256(f"{uid}|{tag}|{ident}".encode()).hexdigest()[:40]


def _items(raw: dict[str, Any] | None, model: type[M]) -> tuple[M, ...]:
    rows = raw.get("items") if raw else None
    return tuple(model.model_validate(r) for r in rows) if isinstance(rows, list) else ()


class HouseStore:
    def __init__(self, docs: Docs, *, prefix: str = "jarvis_") -> None:
        self._docs = docs
        self._prefix = prefix

    def _chores(self, uid: str) -> str:
        return f"{self._prefix}chores/{uid}"

    def _upkeep(self, uid: str) -> str:
        return f"{self._prefix}maintenance/{uid}"

    def _told(self, uid: str, key: str) -> str:
        return f"{self._prefix}house_told/{uid}_{key}"

    async def _list(self, path: str, model: type[M]) -> tuple[M, ...]:
        return _items(await self._docs.get(path), model)

    async def _change(
        self, uid: str, path: str, model: type[M], top: int, fn: Callable[[tuple[M, ...]], Any]
    ) -> tuple[M, ...]:
        async def run(tx: DocTx) -> tuple[M, ...]:
            now = _items(await tx.get(path), model)
            new = tuple(fn(now))
            if len(new) > top:
                raise ValueError(f"At most {top} of these, Sir.")
            tx.set(path, {"uid": uid, "items": [x.model_dump(mode="json") for x in new]})
            return new

        return await self._docs.transaction(run)

    async def chores(self, uid: str) -> tuple[Chore, ...]:
        return await self._list(self._chores(uid), Chore)

    async def change_chores(
        self, uid: str, fn: Callable[[tuple[Chore, ...]], tuple[Chore, ...]]
    ) -> tuple[Chore, ...]:
        return await self._change(uid, self._chores(uid), Chore, MAX_CHORES, fn)

    async def upkeep(self, uid: str) -> tuple[Upkeep, ...]:
        return await self._list(self._upkeep(uid), Upkeep)

    async def change_upkeep(
        self, uid: str, fn: Callable[[tuple[Upkeep, ...]], tuple[Upkeep, ...]]
    ) -> tuple[Upkeep, ...]:
        return await self._change(uid, self._upkeep(uid), Upkeep, MAX_UPKEEP, fn)

    # ---- claims ---------------------------------------------------------------------------------
    async def claim(self, uid: str, tag: str, ident: str, at: datetime) -> bool:
        """True when this run made the claim (send now); False when one exists (sent before)."""
        path = self._told(uid, claim_key(uid, tag, ident))

        async def run(tx: DocTx) -> bool:
            if await tx.get(path) is not None:
                return False
            tx.create(path, {"uid": uid, "tag": tag, "at": at.isoformat()})
            return True

        return await self._docs.transaction(run)

    async def release(self, uid: str, tag: str, ident: str) -> None:
        await self._docs.write([Delete(self._told(uid, claim_key(uid, tag, ident)))])

    async def claims(self, uid: str) -> list[tuple[str, dict[str, Any]]]:
        return await self._docs.query(Query(f"{self._prefix}house_told", where=("uid", uid)))

    async def _drop(self, uid: str, keep: Callable[[dict[str, Any]], bool]) -> int:
        gone = [self._told_id(i) for i, d in await self.claims(uid) if not keep(d)]
        if gone:
            await self._docs.write([Delete(p) for p in gone])
        return len(gone)

    def _told_id(self, doc_id: str) -> str:
        return f"{self._prefix}house_told/{doc_id}"

    async def sweep(self, uid: str, now: datetime) -> int:
        cutoff = (now - CLAIM_KEEP).isoformat()
        return await self._drop(uid, lambda d: str(d.get("at", "")) >= cutoff)

    async def drop_claims(self, uid: str, tags: tuple[str, ...]) -> int:
        return await self._drop(uid, lambda d: d.get("tag") not in tags)

    async def delete_house(self, uid: str) -> int:
        paths = [p for p in (self._chores(uid), self._upkeep(uid)) if await self._docs.get(p)]
        if paths:
            await self._docs.write([Delete(p) for p in paths])
        return len(paths) + await self.drop_claims(uid, HOUSE_TAGS)


class OutsideStore:
    """His place and the feeds' state, sealed. Every change is a transaction (the routes, the
    tools and the jobs never lose each other's writes)."""

    def __init__(self, docs: Docs, keyring: Keyring | None, *, prefix: str = "jarvis_") -> None:
        self._docs = docs
        self._ring = keyring
        self._prefix = prefix

    @property
    def available(self) -> bool:
        return self._ring is not None

    def _path(self, uid: str) -> str:
        return f"{self._prefix}outside/{uid}"

    @staticmethod
    def _aad(uid: str) -> str:
        return f"outside/{uid}/v1"

    def _open(self, uid: str, raw: dict[str, Any] | None) -> Outside:
        if self._ring is None:
            raise OutsideOff
        if not raw or not isinstance(raw.get("blob"), str):
            return Outside()
        plain = self._ring.cipher(PURPOSE).decrypt(raw["blob"], aad=self._aad(uid))
        return Outside.model_validate(json.loads(plain))

    def _seal(self, uid: str, value: Outside) -> str:
        if self._ring is None:
            raise OutsideOff
        plain = json.dumps(value.model_dump(mode="json"), separators=(",", ":")).encode()
        return self._ring.cipher(PURPOSE).encrypt(plain, aad=self._aad(uid))

    async def read(self, uid: str) -> Outside:
        if self._ring is None:
            raise OutsideOff
        return self._open(uid, await self._docs.get(self._path(uid)))

    async def change(self, uid: str, fn: Callable[[Outside], Outside]) -> Outside:
        path = self._path(uid)

        async def run(tx: DocTx) -> Outside:
            raw = await tx.get(path)
            new = fn(self._open(uid, raw))
            rev = int(raw.get("rev", 0)) + 1 if raw else 1
            tx.set(path, {"uid": uid, "rev": rev, "blob": self._seal(uid, new)})
            return new

        return await self._docs.transaction(run)

    async def rev(self, uid: str) -> int | None:
        """The doc's revision without opening it (None: nothing kept)."""
        raw = await self._docs.get(self._path(uid))
        return int(raw.get("rev", 0)) if raw else None

    async def delete(self, uid: str) -> int:
        if await self._docs.get(self._path(uid)) is None:
            return 0
        await self._docs.write([Delete(self._path(uid))])
        return 1


__all__ = [
    "CLAIM_KEEP",
    "HOUSE_TAGS",
    "OFF_WORDS",
    "PLACE_TAGS",
    "PURPOSE",
    "HouseStore",
    "OutsideOff",
    "OutsideStore",
    "claim_key",
]
