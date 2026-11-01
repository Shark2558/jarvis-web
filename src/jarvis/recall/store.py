# src/jarvis/recall/store.py
"""Long-term memory on the Docs port (Layer 7, slice 8 D11).

Layout:  {prefix}memory/{uid}              user_id, rev, shard_count, json(Header: settings,
                                           profile, use counters, learning bookkeeping)
         {prefix}memory_shards/{uid}_{n}   user_id, n, json([Fact, …])   (≤ 100 facts each)

`rev` names the shard contents only. The header is read on every load (one read: settings,
profile and counters are always fresh); the shards come from an in-process copy while `rev`
matches, else ≤ 7 more reads. Outside a transaction the header and the shards are separate
reads, so a writer can land between them: shards are kept (cached under `rev`) only when they
hash to `rev`; otherwise the read is retried (bounded) and, if it stays torn, used uncached.
Every change is one transaction that reads the header (and the shards only when the copy is
stale), then writes the shards that differ and the header — a
writer elsewhere changes the header too, so Firestore retries us on any conflict. A document
that cannot be read fails closed (MemoryUnavailable) and is never overwritten.
"""

from __future__ import annotations

import hashlib
from collections import OrderedDict
from collections.abc import Awaitable, Callable
from dataclasses import replace
from typing import Any

from pydantic import TypeAdapter, ValidationError

from jarvis.logging import get_logger
from jarvis.recall.errors import MemoryUnavailable
from jarvis.recall.models import Fact, Header, MemoryState, Shards
from jarvis.storage.docs import Doc, Docs, DocTx
from jarvis.storage.sessions import safe_id

log = get_logger(__name__)

CACHE_OWNERS = 16
TORN_RETRIES = 3
_SHARD = TypeAdapter(tuple[Fact, ...])
Change = Callable[[MemoryState], MemoryState | None]
Reader = Callable[[str], Awaitable[Doc | None]]


class _ChangeFailed(Exception):
    """Carries an exception raised by the caller's change function out of the transaction."""

    def __init__(self, inner: BaseException) -> None:
        super().__init__(type(inner).__name__)
        self.inner = inner


class _Torn(Exception):
    """The shards read do not belong to the header's revision (a writer landed in between)."""

    def __init__(self, state: MemoryState | None) -> None:
        super().__init__("torn read")
        self.state = state


def _shard_json(shard: tuple[Fact, ...]) -> str:
    return _SHARD.dump_json(shard).decode()


def _rev_of(texts: list[str]) -> str:
    h = hashlib.sha256()
    for text in texts:
        h.update(text.encode())
        h.update(b"\x1e")
    return h.hexdigest()[:16]


def shards_rev(shards: Shards) -> str:
    return _rev_of([_shard_json(shard) for shard in shards])


def _consistent(rev: str, shards: Shards, docs: list[Doc]) -> bool:
    """Do these shards carry revision `rev`? By the stored JSON, or by the facts re-serialised
    (the writer hashed its own serialisation), so a later field added to Fact can't wedge it."""
    if not shards:
        return rev in ("", shards_rev(()))
    return _rev_of([str(d["json"]) for d in docs]) == rev or shards_rev(shards) == rev


def _decode_header(doc: Doc) -> tuple[Header, str, int]:
    try:
        header = Header.model_validate_json(str(doc["json"]))
        return header, str(doc["rev"]), int(doc["shard_count"])
    except (KeyError, TypeError, ValueError, ValidationError):
        log.error("unreadable memory header; memory is off until it is fixed")
        raise MemoryUnavailable() from None


def _decode_shard(doc: Doc | None, n: int) -> tuple[Fact, ...]:
    if doc is None:
        log.error("memory shard missing", extra={"shard": n})
        raise MemoryUnavailable()
    try:
        return _SHARD.validate_json(str(doc["json"]))
    except (KeyError, TypeError, ValueError, ValidationError):
        log.error("unreadable memory shard; memory is off until it is fixed", extra={"shard": n})
        raise MemoryUnavailable() from None


class MemoryStore:
    def __init__(self, docs: Docs, *, prefix: str = "jarvis_") -> None:
        self._d = docs
        self._headers = f"{prefix}memory"
        self._shards = f"{prefix}memory_shards"
        self._known: OrderedDict[str, tuple[str, Shards]] = OrderedDict()

    def _hpath(self, uid: str) -> str:
        if not safe_id(uid):
            raise ValueError("invalid user id")
        return f"{self._headers}/{uid}"

    def _spath(self, uid: str, n: int) -> str:
        return f"{self._shards}/{uid}_{n}"

    def _remember(self, uid: str, rev: str, shards: Shards) -> None:
        self._known[uid] = (rev, shards)
        self._known.move_to_end(uid)
        while len(self._known) > CACHE_OWNERS:
            self._known.popitem(last=False)

    async def _state(
        self, uid: str, head: Doc | None, read: Reader, *, verify: bool
    ) -> MemoryState:
        if head is None:
            return MemoryState.empty()
        header, rev, count = _decode_header(head)
        known = self._known.get(uid)
        torn = False
        if known is not None and known[0] == rev:
            shards = known[1]
        else:
            docs = [await read(self._spath(uid, n)) for n in range(count)]
            if verify and any(d is None for d in docs):
                raise _Torn(None)  # a shard went away under us: read again
            shards = tuple(_decode_shard(d, n) for n, d in enumerate(docs))
            torn = verify and not _consistent(rev, shards, [d for d in docs if d is not None])
            if not torn:
                self._remember(uid, rev, shards)
        state = MemoryState(
            rev=rev,
            settings=header.settings,
            profile=header.profile,
            shards=shards,
            usage=header.usage,
            learn=header.learn,
        )
        if torn:
            raise _Torn(state)
        return state

    async def _load_verified(self, uid: str, path: str) -> MemoryState:
        last: _Torn | None = None
        for _ in range(TORN_RETRIES):
            try:
                return await self._state(uid, await self._d.get(path), self._d.get, verify=True)
            except _Torn as torn:
                last = torn
        log.warning("memory read kept racing a writer; used uncached")
        if last is None or last.state is None:
            raise MemoryUnavailable()
        return last.state

    async def load(self, uid: str) -> MemoryState:
        """One read when the shard copy is current; ≤ 8 on a cold start."""
        path = self._hpath(uid)
        try:
            return await self._load_verified(uid, path)
        except MemoryUnavailable:
            raise
        except Exception as exc:  # noqa: BLE001 — storage down: say so in plain words
            log.error("memory read failed", extra={"reason": type(exc).__name__})
            raise MemoryUnavailable() from None

    async def mutate(self, uid: str, change: Change) -> MemoryState:
        """Read-modify-write in one transaction. `change` returns the new state (None: nothing
        to write) and may raise: nothing is written and its exception reaches the caller."""
        hpath = self._hpath(uid)

        async def fn(tx: DocTx) -> tuple[MemoryState, MemoryState | None]:
            head = await tx.get(hpath)  # one consistent snapshot: nothing to verify
            cur = await self._state(uid, head, tx.get, verify=False)
            try:
                new = change(cur)
            except Exception as exc:  # noqa: BLE001 — re-raised outside the transaction
                raise _ChangeFailed(exc) from exc
            if new is None:
                return cur, None
            new = self._write(tx, uid, cur, new, first=head is None)
            return cur, new

        try:
            cur, new = await self._d.transaction(fn)
        except _ChangeFailed as wrapped:
            raise wrapped.inner from None
        except MemoryUnavailable:
            raise
        except Exception as exc:  # noqa: BLE001
            log.error("memory write failed", extra={"reason": type(exc).__name__})
            raise MemoryUnavailable() from None
        if new is None:
            return cur
        self._remember(uid, new.rev, new.shards)
        return new

    def _write(
        self, tx: DocTx, uid: str, cur: MemoryState, new: MemoryState, *, first: bool
    ) -> MemoryState:
        """Queue the writes that differ; returns `new` with its revision set."""
        moved = new.shards != cur.shards
        new = replace(new, rev=shards_rev(new.shards) if moved else cur.rev)
        for n, shard in enumerate(new.shards):
            if n >= len(cur.shards) or shard != cur.shards[n]:
                tx.set(self._spath(uid, n), {"user_id": uid, "n": n, "json": _shard_json(shard)})
        for n in range(len(new.shards), len(cur.shards)):
            tx.delete(self._spath(uid, n))
        if first or moved or new.header() != cur.header():
            tx.set(self._hpath(uid), self._header_doc(uid, new))
        return new

    @staticmethod
    def _header_doc(uid: str, s: MemoryState) -> dict[str, Any]:
        return {
            "user_id": uid,
            "rev": s.rev,
            "shard_count": len(s.shards),
            "json": s.header().model_dump_json(),
        }


__all__ = ["Change", "MemoryStore", "shards_rev"]
