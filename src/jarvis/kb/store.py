# src/jarvis/kb/store.py
"""Notes on the Docs port, encrypted by JARVIS before they reach Firestore (R2 D2, Layer 7).

    {prefix}kb/{uid}               rev, v, kid, shards: [{id, h}], counts, updated_at
    {prefix}kb_shards/{uid}_{id}   blob = AES-GCM(JSON [Note, ...]) under the `notes` key,
                                   AAD "notes/shard/{uid}/{id}/v1"

The header holds no text: only ids, a short hash of each shard blob, and four counters. A shard
holds as many notes as fit in `SHARD_PLAIN_MAX` bytes (ciphertext stays under `SHARD_CIPHER_MAX`
characters, inside Firestore's 1 MiB document limit). The AAD names the owner and the shard, so a
shard moved to another owner or position does not open.

Every change is one transaction: it reads the header (and the shards only when the in-process copy
is stale), writes the shards that differ and the header last. A non-transactional read checks each
shard against the header's hash, so a read that landed between two writes is retried (bounded) and
then fails closed. A document that cannot be read or decrypted raises `NotesError` 503 and is never
overwritten. Nothing is logged but class names.
"""

from __future__ import annotations

import asyncio
import hashlib
import secrets
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, TypeVar

from pydantic import TypeAdapter, ValidationError

from jarvis.integrations.vault import VaultError
from jarvis.kb.models import Note, NotesError, unavailable
from jarvis.keyring import KEY_ID, Keyring
from jarvis.logging import get_logger
from jarvis.storage.docs import Delete, Doc, Docs, DocTx, Set
from jarvis.storage.sessions import safe_id

log = get_logger(__name__)

SHARD_PLAIN_MAX = 400_000  # bytes of JSON per shard
SHARD_CIPHER_MAX = 600_000  # characters of base64 ciphertext per shard document
CACHE_OWNERS = 8
TORN_RETRIES = 3
T = TypeVar("T")
_NOTES = TypeAdapter(tuple[Note, ...])
Change = Callable[[tuple[Note, ...]], tuple[tuple[Note, ...], T]]


@dataclass(frozen=True)
class NotesState:
    rev: str
    notes: tuple[Note, ...]


@dataclass(frozen=True)
class _Loaded:
    rev: str
    entries: tuple[tuple[str, str], ...]  # (shard id, hash of its blob)
    plains: tuple[str, ...]
    notes: tuple[Note, ...]


_EMPTY = _Loaded("", (), (), ())


def _hash(blob: str) -> str:
    return hashlib.sha256(blob.encode()).hexdigest()[:16]


def _pack(notes: tuple[Note, ...]) -> list[str]:
    """Greedy: the notes in order, split into JSON arrays of at most SHARD_PLAIN_MAX bytes."""
    shards: list[list[str]] = []
    size = 0
    for n in notes:
        one = n.model_dump_json()
        w = len(one.encode()) + 1
        if not shards or size + w > SHARD_PLAIN_MAX:
            shards.append([])
            size = 2
        shards[-1].append(one)
        size += w
    return ["[" + ",".join(s) + "]" for s in shards]


def _counts(notes: tuple[Note, ...]) -> dict[str, int]:
    out = {"note": 0, "memo": 0, "link": 0, "deleted": 0}
    for n in notes:
        out["deleted" if n.deleted_at is not None else n.kind] += 1
    return out


class NotesStore:
    def __init__(self, docs: Docs, keyring: Keyring, *, prefix: str = "jarvis_") -> None:
        self._d = docs
        self._cipher = keyring.cipher("notes")
        self._keyring = keyring
        self._fetch_doc = f"{prefix}kb_fetch"
        self._headers = f"{prefix}kb"
        self._shards = f"{prefix}kb_shards"
        self._known: OrderedDict[str, _Loaded] = OrderedDict()

    # ---- paths and crypto ---------------------------------------------------------------------

    def _hpath(self, uid: str) -> str:
        if not isinstance(uid, str) or not safe_id(uid):
            raise ValueError("invalid user id")
        return f"{self._headers}/{uid}"

    def _spath(self, uid: str, sid: str) -> str:
        return f"{self._shards}/{uid}_{sid}"

    @staticmethod
    def _aad(uid: str, sid: str) -> str:
        return f"notes/shard/{uid}/{sid}/v1"

    def _remember(self, uid: str, loaded: _Loaded) -> None:
        self._known[uid] = loaded
        self._known.move_to_end(uid)
        while len(self._known) > CACHE_OWNERS:
            self._known.popitem(last=False)

    def _open(self, uid: str, sid: str, doc: Doc | None, want: str) -> tuple[str, tuple[Note, ...]]:
        """(plaintext JSON, notes) of one shard document, or `NotesError` 503."""
        try:
            if doc is None:
                raise KeyError("missing")
            blob = str(doc["blob"])
            if _hash(blob) != want:
                raise ValueError("hash")
            plain = self._cipher.decrypt(blob, aad=self._aad(uid, sid)).decode()
            return plain, _NOTES.validate_json(plain)
        except (KeyError, TypeError, ValueError, VaultError, ValidationError) as exc:
            log.error("notes shard unreadable", extra={"error": type(exc).__name__})
            raise unavailable() from None

    @staticmethod
    def _entries(head: Doc) -> tuple[str, tuple[tuple[str, str], ...]]:
        try:
            entries = tuple((str(e["id"]), str(e["h"])) for e in head["shards"])
            return str(head["rev"]), entries
        except (KeyError, TypeError, ValueError):
            log.error("notes header unreadable")
            raise unavailable() from None

    # ---- reading --------------------------------------------------------------------------------

    async def _read_all(
        self, uid: str, head: Doc | None, get: Callable[[str], Any], *, use_cache: bool
    ) -> _Loaded:
        if head is None:
            return _EMPTY
        rev, entries = self._entries(head)
        known = self._known.get(uid)
        if use_cache and known is not None and known.rev == rev:
            return known
        plains: list[str] = []
        notes: list[Note] = []
        for sid, want in entries:
            doc = await get(self._spath(uid, sid))
            plain, got = await asyncio.to_thread(self._open, uid, sid, doc, want)
            plains.append(plain)
            notes.extend(got)
        return _Loaded(rev, entries, tuple(plains), tuple(notes))

    async def load(self, uid: str) -> NotesState:
        """One read when the in-process copy is current; header + shards on a cold start."""
        path = self._hpath(uid)
        last: NotesError | None = None
        for _ in range(TORN_RETRIES):
            try:
                loaded = await self._read_all(
                    uid, await self._d.get(path), self._d.get, use_cache=True
                )
            except NotesError as exc:
                last = exc  # maybe a writer landed between the header and a shard: read again
                continue
            except Exception as exc:  # noqa: BLE001 - storage down: say so in plain words
                log.error("notes read failed", extra={"error": type(exc).__name__})
                raise unavailable() from None
            if loaded.rev:
                self._remember(uid, loaded)
            return NotesState(loaded.rev, loaded.notes)
        raise last if last is not None else unavailable()

    # ---- writing --------------------------------------------------------------------------------

    async def change(self, uid: str, fn: Change[T]) -> tuple[NotesState, T]:
        """Read-modify-write in one transaction. `fn(notes)` returns (the new notes, an answer) and
        may raise: nothing is written and its exception reaches the caller."""
        hpath = self._hpath(uid)
        refused: list[BaseException] = []
        result: list[tuple[_Loaded, T]] = []

        async def tx_fn(tx: DocTx) -> None:
            refused.clear()
            result.clear()
            head = await tx.get(hpath)
            cur = await self._read_all(uid, head, tx.get, use_cache=True)
            try:
                new_notes, answer = fn(cur.notes)
            except Exception as exc:  # noqa: BLE001 - the caller's refusal, re-raised below
                refused.append(exc)
                return
            if new_notes == cur.notes:
                result.append((cur, answer))
                return
            plains = await asyncio.to_thread(_pack, new_notes)  # CPU: off the event loop
            result.append((await self._write(tx, uid, cur, new_notes, plains), answer))

        try:
            await self._d.transaction(tx_fn)
        except NotesError:
            raise
        except Exception as exc:  # noqa: BLE001
            log.error("notes write failed", extra={"error": type(exc).__name__})
            raise unavailable() from None
        if refused:
            raise refused[0]
        loaded, answer = result[0]
        if loaded.rev:
            self._remember(uid, loaded)
        return NotesState(loaded.rev, loaded.notes), answer

    async def _write(
        self, tx: DocTx, uid: str, cur: _Loaded, notes: tuple[Note, ...], plains: list[str]
    ) -> _Loaded:
        entries: list[tuple[str, str]] = []
        for i, plain in enumerate(plains):
            sid = f"s{i}"
            if i < len(cur.plains) and cur.plains[i] == plain and cur.entries[i][0] == sid:
                entries.append(cur.entries[i])
                continue
            blob = await asyncio.to_thread(
                self._cipher.encrypt, plain.encode(), aad=self._aad(uid, sid)
            )
            if len(blob) > SHARD_CIPHER_MAX:  # cannot happen with SHARD_PLAIN_MAX; fail closed
                raise unavailable()
            tx.set(self._spath(uid, sid), {"blob": blob})
            entries.append((sid, _hash(blob)))
        for sid, _ in cur.entries[len(plains) :]:
            tx.delete(self._spath(uid, sid))
        rev = secrets.token_hex(8)
        tx.set(
            self._hpath(uid),
            {
                "rev": rev,
                "v": 1,
                "kid": KEY_ID,
                "shards": [{"id": s, "h": h} for s, h in entries],
                "counts": _counts(notes),
                "updated_at": datetime.now(UTC).isoformat(),
            },
        )
        return _Loaded(rev, tuple(entries), tuple(plains), notes)

    # ---- export signature and the hourly fetch window ------------------------------------------

    def mac(self, data: str) -> str:
        """HMAC of `data` under the notes MAC key (the export signature)."""
        return self._keyring.mac("notes", data)

    def mac_matches(self, data: str, tag: object) -> bool:
        return isinstance(tag, str) and self._keyring.mac_matches("notes", data, tag)

    def _fetch_path(self, uid: str) -> str:
        if not isinstance(uid, str) or not safe_id(uid):
            raise ValueError("invalid user id")
        return f"{self._fetch_doc}/{uid}"

    async def take_fetch_slot(self, uid: str, now: float, limit: int, window: float) -> bool:
        """Record a fetch at `now` unless `limit` already happened in the last `window` seconds
        (one transaction, so two servers cannot both take the last slot)."""
        path = self._fetch_path(uid)
        took: list[bool] = []

        async def tx_fn(tx: DocTx) -> None:
            took.clear()
            doc = await tx.get(path)
            raw = doc.get("at") if doc else None
            at = (
                [float(x) for x in raw if isinstance(x, int | float)]
                if isinstance(raw, list)
                else []
            )
            at = [x for x in at if now - x < window]
            if len(at) >= limit:
                took.append(False)
                return
            tx.set(path, {"at": [*at, now]})
            took.append(True)

        try:
            await self._d.transaction(tx_fn)
        except Exception as exc:  # noqa: BLE001
            log.error("notes fetch window failed", extra={"error": type(exc).__name__})
            raise unavailable() from None
        return took[0]

    async def give_back_fetch_slot(self, uid: str, now: float) -> None:
        """Take back the slot recorded at `now` (the fetch did not happen)."""
        path = self._fetch_path(uid)

        async def tx_fn(tx: DocTx) -> None:
            doc = await tx.get(path)
            raw = doc.get("at") if doc else None
            if not isinstance(raw, list) or now not in raw:
                return
            left = list(raw)
            left.remove(now)
            tx.set(path, {"at": left})

        try:
            await self._d.transaction(tx_fn)
        except Exception as exc:  # noqa: BLE001
            log.error("notes fetch window refund failed", extra={"error": type(exc).__name__})

    async def summary(self, uid: str) -> tuple[str, dict[str, int]]:
        """(the revision, the header's counters): one read, no decryption. ("", zeros) when the
        owner has nothing yet. The revision changes with every write."""
        head = await self._d.get(self._hpath(uid))
        zero = {"note": 0, "memo": 0, "link": 0, "deleted": 0}
        if head is None:
            return "", zero
        raw = head.get("counts")
        if not isinstance(raw, dict):
            raise unavailable()
        return str(head.get("rev", "")), {k: int(raw.get(k, 0)) for k in zero}

    async def wipe(self, uid: str) -> int:
        """Delete every shard and the header in one write; returns the live notes that went."""
        hpath = self._hpath(uid)
        head = await self._d.get(hpath)
        if head is None:
            return 0
        try:
            live = sum(1 for n in (await self.load(uid)).notes if n.live)
        except NotesError:
            live = 0  # unreadable data can still be deleted
        try:
            ids = [str(e["id"]) for e in head.get("shards", [])]
        except (KeyError, TypeError):
            ids = []
        ops = [Delete(self._spath(uid, sid)) for sid in ids]
        await self._d.write([*ops, Delete(hpath)])
        self._known.pop(uid, None)
        return live


__all__ = ["SHARD_CIPHER_MAX", "SHARD_PLAIN_MAX", "NotesState", "NotesStore", "Set"]
