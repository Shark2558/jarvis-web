# src/jarvis/wardrobe/styling/sealed.py
"""R13 Part C's documents (docs/plans/r13-wardrobe.md "Data model"): sealed with the keyring's
`wardrobe` purpose (AAD `<collection>/<uid>/v1`), never in clear; flat ids; every document with
`updated_at` (R14's drill samples on it).

- `SealedDoc`: one document per owner (`wardrobe_plans/{uid}`, `wardrobe_cal/{uid}`,
  `wardrobe_outlook/{uid}`), read whole, changed in a transaction (a write never loses another).
  No key: `Off` (C is off and says so; nothing is ever written in clear). A document that can't
  be opened is never overwritten (`Unreadable`).
- `Told`: once-only claims in `wardrobe_told/{uid}_styling_<key>` (shared with B; each key starts
  with the part's name, `ports.TOLD_KEY_PREFIX`), written BEFORE the send: `once` (create-only)
  and `every` (at most once per gap). A claim holds a hash of its key and its time, nothing else;
  kept 30 days (`prune`).
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any, Generic, TypeVar

from pydantic import BaseModel

from jarvis.keyring import Keyring
from jarvis.logging import get_logger
from jarvis.storage.docs import Create, Delete, DocExists, Docs, DocTx, Query
from jarvis.wardrobe.ports import TOLD_KEY_PREFIX

log = get_logger(__name__)
PURPOSE = "wardrobe"
TOLD = "wardrobe_told"
TOLD_PREFIX = TOLD_KEY_PREFIX["styling"]
TOLD_KEEP = timedelta(days=30)
M = TypeVar("M", bound=BaseModel)


class Off(RuntimeError):
    """No token key (or no storage): C's documents are sealed or not kept at all."""


class Unreadable(RuntimeError):
    """A sealed document that can't be opened: it is never overwritten."""


class SealedDoc(Generic[M]):
    def __init__(
        self,
        docs: Docs | None,
        keyring: Keyring | None,
        *,
        collection: str,
        model: type[M],
        now: Callable[[], datetime],
        prefix: str = "jarvis_",
    ) -> None:
        self._docs, self._ring, self._model = docs, keyring, model
        self._collection, self._now, self._prefix = collection, now, prefix

    @property
    def available(self) -> bool:
        return self._docs is not None and self._ring is not None

    def path(self, uid: str) -> str:
        return f"{self._prefix}{self._collection}/{uid}"

    def _aad(self, uid: str) -> str:
        return f"{self._collection}/{uid}/v1"

    def _ready(self) -> tuple[Docs, Keyring]:
        if self._docs is None or self._ring is None:
            raise Off
        return self._docs, self._ring

    def _open(self, uid: str, raw: dict[str, Any] | None) -> M:
        _, ring = self._ready()
        if not raw:
            return self._model()
        try:
            plain = ring.cipher(PURPOSE).decrypt(str(raw.get("blob", "")), aad=self._aad(uid))
            return self._model.model_validate(json.loads(plain))
        except Exception as exc:  # noqa: BLE001 - never overwrite what can't be opened
            err = {"error": type(exc).__name__}
            log.error("outfits: a sealed document can't be opened", extra=err)
            raise Unreadable(self._collection) from None  # never chain decrypted values (L6)

    def _body(self, uid: str, value: M, rev: int) -> dict[str, Any]:
        _, ring = self._ready()
        plain = json.dumps(value.model_dump(mode="json"), separators=(",", ":")).encode()
        blob = ring.cipher(PURPOSE).encrypt(plain, aad=self._aad(uid))
        return {"uid": uid, "rev": rev, "blob": blob, "updated_at": self._now().isoformat()}

    async def read(self, uid: str) -> M:
        docs, _ = self._ready()
        return self._open(uid, await docs.get(self.path(uid)))

    async def change(self, uid: str, fn: Callable[[M], M]) -> M:
        docs, _ = self._ready()
        path = self.path(uid)

        async def run(tx: DocTx) -> M:
            raw = await tx.get(path)
            new = fn(self._open(uid, raw))
            tx.set(path, self._body(uid, new, int((raw or {}).get("rev", 0)) + 1))
            return new

        return await docs.transaction(run)

    async def exists(self, uid: str) -> bool:
        docs, _ = self._ready()
        return await docs.get(self.path(uid)) is not None

    async def delete(self, uid: str) -> int:
        if self._docs is None or await self._docs.get(self.path(uid)) is None:
            return 0
        await self._docs.write([Delete(self.path(uid))])
        return 1


class Told:
    """Once-only claims for C's alerts (D19), written before the send."""

    def __init__(self, docs: Docs | None, *, now: Callable[[], datetime], prefix: str = "jarvis_"):
        self._docs, self._now, self._prefix = docs, now, prefix

    def path(self, uid: str, key: str) -> str:
        return f"{self._prefix}{TOLD}/{uid}_{TOLD_PREFIX}{key}"

    def _body(self, uid: str, key: str) -> dict[str, Any]:
        stamp = self._now().isoformat()
        digest = hashlib.sha256(f"{TOLD_PREFIX}{key}".encode()).hexdigest()[:16]
        return {"uid": uid, "part": "styling", "h": digest, "at": stamp, "updated_at": stamp}

    async def once(self, uid: str, key: str) -> bool:
        """True the first time only (a create-only write: two clock runs never both win)."""
        if self._docs is None:
            return False
        try:
            await self._docs.write([Create(self.path(uid, key), self._body(uid, key))])
        except DocExists:
            return False
        return True

    async def every(self, uid: str, key: str, gap: timedelta) -> bool:
        """True when the last claim for `key` is at least `gap` old (or there is none)."""
        if self._docs is None:
            return False
        path, now = self.path(uid, key), self._now()

        async def run(tx: DocTx) -> bool:
            raw = await tx.get(path)
            at = datetime.fromisoformat(str(raw["at"])) if raw and raw.get("at") else None
            if at is not None and now - at < gap:
                return False
            tx.set(path, self._body(uid, key))
            return True

        return await self._docs.transaction(run)

    async def _mine(self, uid: str) -> list[tuple[str, dict[str, Any]]]:
        if self._docs is None:
            return []
        rows = await self._docs.query(Query(f"{self._prefix}{TOLD}", where=("uid", uid)))
        return [(i, d) for i, d in rows if d.get("part") == "styling"]

    async def prune(self, uid: str) -> int:
        cut = self._now() - TOLD_KEEP
        old = [i for i, d in await self._mine(uid) if str(d.get("at", "")) < cut.isoformat()]
        if old and self._docs is not None:
            await self._docs.write([Delete(f"{self._prefix}{TOLD}/{i}") for i in old])
        return len(old)

    async def delete(self, uid: str) -> int:
        mine = [i for i, _ in await self._mine(uid)]
        if mine and self._docs is not None:
            await self._docs.write([Delete(f"{self._prefix}{TOLD}/{i}") for i in mine])
        return len(mine)

    async def count(self, uid: str) -> int:
        return len(await self._mine(uid))


__all__ = ["PURPOSE", "TOLD", "TOLD_PREFIX", "Off", "SealedDoc", "Told", "Unreadable"]
