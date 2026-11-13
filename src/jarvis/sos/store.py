# src/jarvis/sos/store.py
"""Emergency SOS documents on the Docs port (docs/plans/r7-mobile.md data model, D19, D20).

    {prefix}sos/{uid}               v, kid, blob = AES-GCM(JSON Book) under the keyring's `sos` key,
                                    AAD "sos/{uid}/v1"; updated_at
    {prefix}sos_join/{mac}          uid, contact, until: a pending join word, kept ONLY as
                                    `keyring.mac("sos", word)` (the word itself never), 24 hours
    {prefix}sos_join/wrong          hour, count: wrong join words this hour (never the pairing's)
    {prefix}sos_log/{uid}_{id}      uid, at, kind, outcome, reached, joined, location (yes / no),
                                    via: one SOS, test or "I'm safe" (400 days)
    {prefix}sos_log/{uid}_budget    real, test: the send times of the last day (the limits)
    {prefix}sos_log/{uid}_last      the newest log entry, for the card

No keyring: `SosOff` (nothing is kept in clear). A store that fails raises `SosUnavailable`; a
sealed book that does not open is never overwritten. No document ever holds a coordinate, a word
a contact wrote or a join word. Logs carry class names and counts only.
"""

from __future__ import annotations

import json
import secrets
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

from pydantic import ValidationError

from jarvis.integrations.vault import VaultError
from jarvis.keyring import KEY_ID, Keyring
from jarvis.logging import get_logger
from jarvis.sos.models import Book
from jarvis.storage.docs import Delete, Doc, Docs, DocTx, Query, Set
from jarvis.storage.sessions import safe_id

log = get_logger(__name__)
PURPOSE = "sos"
VERSION = 1
JOIN_S = 24 * 3600
DAY_S = 24 * 3600
WRONG_ID = "wrong"  # the global wrong-word counter's document in sos_join
WRONG_PER_CHAT = 30  # wrong join words an hour from one chat before that chat waits for the hour
WRONG_GLOBAL_PER_HOUR = 300  # ... and from everyone together (a flood from many chats)
WRONG_BUCKETS = 256  # chats share 256 counters, so strangers can never make unbounded documents
SWEEP_MAX = 500
Pool = Literal["real", "test"]
_SPECIAL = ("budget", "last")


class SosOff(RuntimeError):
    WORDS = "Emergency SOS is off, Sir: JARVIS has no token key to keep your contacts sealed."

    def __init__(self) -> None:
        super().__init__(self.WORDS)


class SosUnavailable(RuntimeError):
    WORDS = "Your SOS set-up couldn't be read just now, Sir."

    def __init__(self) -> None:
        super().__init__(self.WORDS)


@dataclass(frozen=True)
class Budget:
    """The send times (unix seconds) of the last day, real and tests apart."""

    real: tuple[float, ...] = ()
    test: tuple[float, ...] = ()

    @classmethod
    def of(cls, doc: Doc | None, now: float) -> Budget:
        def times(key: str) -> tuple[float, ...]:
            raw = doc.get(key) if doc else None
            if raw is not None and not isinstance(raw, list):
                log.warning("the SOS budget has a bad list: read as empty", extra={"pool": key})
            items = raw if isinstance(raw, list) else []
            ok = [float(t) for t in items if isinstance(t, int | float) and not isinstance(t, bool)]
            if len(ok) != len(items):
                log.warning("the SOS budget had bad entries: dropped", extra={"pool": key})
            return tuple(t for t in ok if 0 <= now - t < DAY_S)

        return cls(times("real"), times("test"))

    def plus(self, pool: Pool, now: float) -> Budget:
        if pool == "real":
            return Budget((*self.real, now), self.test)
        return Budget(self.real, (*self.test, now))


@dataclass(frozen=True)
class Entry:
    at: str
    kind: str
    outcome: str
    reached: int
    joined: int
    location: bool
    via: str

    def doc(self, uid: str) -> Doc:
        return {
            "uid": uid,
            "at": self.at,
            "kind": self.kind,
            "outcome": self.outcome,
            "reached": self.reached,
            "joined": self.joined,
            "location": self.location,
            "via": self.via,
        }


def _uid(uid: str) -> str:
    if not isinstance(uid, str) or not safe_id(uid):
        raise ValueError("invalid user id")
    return uid


def _at(doc_id: str, doc: Doc) -> str:
    """When a log document's entry happened ("" when it can't tell)."""
    entry = doc.get("entry") if doc_id.endswith("_last") else doc
    at = entry.get("at") if isinstance(entry, dict) else None
    return at if isinstance(at, str) else ""


def _special(doc_id: str) -> bool:
    return doc_id.endswith(tuple(f"_{s}" for s in _SPECIAL))


class SosStore:
    def __init__(
        self,
        docs: Docs,
        keyring: Keyring | None,
        *,
        prefix: str = "jarvis_",
        now: Callable[[], datetime],
    ) -> None:
        self._docs = docs
        self._ring = keyring
        self._prefix = prefix
        self._now = now

    @property
    def sealed(self) -> bool:
        return self._ring is not None

    def ring(self) -> Keyring:
        if self._ring is None:
            raise SosOff()
        return self._ring

    def mac(self, word: str) -> str:
        return self.ring().mac(PURPOSE, word)

    def _book_path(self, uid: str) -> str:
        return f"{self._prefix}sos/{_uid(uid)}"

    def _join_path(self, mac: str) -> str:
        return f"{self._prefix}sos_join/{mac}"

    def _log_path(self, uid: str, name: str) -> str:
        return f"{self._prefix}sos_log/{_uid(uid)}_{name}"

    # ---- the sealed book --------------------------------------------------------------------
    def _seal(self, uid: str, book: Book) -> Doc:
        plain = book.model_dump_json().encode()
        blob = self.ring().cipher(PURPOSE).encrypt(plain, aad=f"sos/{uid}/v1")
        return {"v": VERSION, "kid": KEY_ID, "blob": blob, "updated_at": self._now().isoformat()}

    def _open(self, uid: str, doc: Doc | None) -> Book:
        if doc is None:
            return Book()
        try:
            raw = self.ring().cipher(PURPOSE).decrypt(str(doc["blob"]), aad=f"sos/{uid}/v1")
            return Book.model_validate(json.loads(raw))
        except SosOff:
            raise
        except (KeyError, TypeError, ValueError, VaultError, ValidationError) as exc:
            log.error("the sealed SOS book didn't open", extra={"error": type(exc).__name__})
            raise SosUnavailable() from None

    async def book(self, uid: str) -> Book:
        self.ring()
        try:
            doc = await self._docs.get(self._book_path(uid))
        except Exception as exc:  # noqa: BLE001 - the store: plain words
            log.warning("SOS book unreadable", extra={"error": type(exc).__name__})
            raise SosUnavailable() from None
        return self._open(uid, doc)

    async def _tx(self, fn: Callable[[DocTx], Any]) -> Any:
        try:
            return await self._docs.transaction(fn)
        except (SosOff, SosUnavailable, ValueError):
            raise
        except Exception as exc:  # noqa: BLE001 - the store: plain words
            log.warning("SOS store transaction failed", extra={"error": type(exc).__name__})
            raise SosUnavailable() from None

    async def update(self, uid: str, change: Callable[[Book], Book]) -> Book:
        """Read, change and write the book in one transaction (`change` may raise to refuse)."""
        self.ring()
        path = self._book_path(uid)

        async def fn(tx: DocTx) -> Book:
            new = change(self._open(uid, await tx.get(path)))
            tx.set(path, self._seal(uid, new))
            return new

        result: Book = await self._tx(fn)
        return result

    # ---- join words ------------------------------------------------------------------------
    async def put_join(
        self, uid: str, contact: str, mac: str, until: float, old: str | None
    ) -> None:
        ops: list[Set | Delete] = [Delete(self._join_path(old))] if old else []
        ops.append(Set(self._join_path(mac), {"uid": uid, "contact": contact, "until": until}))
        await self._write(ops)

    async def drop_join(self, mac: str | None) -> None:
        if mac:
            await self._write([Delete(self._join_path(mac))])

    async def join(
        self, mac: str, now: float, change: Callable[[Book, str], Book | None]
    ) -> tuple[str, Book] | None:
        """Use a join word ONCE: its document is deleted and the book changed in one transaction.
        None when there is no such word, it ran out, or `change` finds no contact for it."""
        self.ring()
        jpath = self._join_path(mac)

        async def fn(tx: DocTx) -> tuple[str, Book] | None:
            doc = await tx.get(jpath)
            if doc is None:
                return None
            uid, contact, until = doc.get("uid"), doc.get("contact"), doc.get("until")
            if not isinstance(uid, str) or not safe_id(uid) or not isinstance(contact, str):
                tx.delete(jpath)
                return None
            bpath = self._book_path(uid)
            book = self._open(uid, await tx.get(bpath))
            tx.delete(jpath)
            if not isinstance(until, int | float) or until < now:
                return None
            new = change(book, contact)
            if new is None:
                return None
            tx.set(bpath, self._seal(uid, new))
            return uid, new

        result: tuple[str, Book] | None = await self._tx(fn)
        return result

    def _wrong_paths(self, chat_id: int) -> tuple[str, str]:
        bucket = chat_id % WRONG_BUCKETS
        return self._join_path(WRONG_ID), self._join_path(f"{WRONG_ID}_{bucket}")

    async def wrong_blocked(self, now: float, chat_id: int) -> bool:
        """True when this chat (or everyone together) got too many wrong words this hour."""
        hour = int(now // 3600)
        limits = zip(
            self._wrong_paths(chat_id), (WRONG_GLOBAL_PER_HOUR, WRONG_PER_CHAT), strict=True
        )
        for path, cap in limits:
            try:
                doc = await self._docs.get(path)
            except Exception as exc:  # noqa: BLE001 - fail closed: no join while it can't be read
                log.warning(
                    "SOS wrong-word counter unreadable", extra={"error": type(exc).__name__}
                )
                return True
            if doc and doc.get("hour") == hour and int(doc.get("count", 0)) >= cap:
                return True
        return False

    async def count_wrong(self, now: float, chat_id: int) -> None:
        hour = int(now // 3600)
        paths = self._wrong_paths(chat_id)

        async def fn(tx: DocTx) -> None:
            docs = [await tx.get(p) or {} for p in paths]
            for path, doc in zip(paths, docs, strict=True):
                count = int(doc.get("count", 0)) if doc.get("hour") == hour else 0
                tx.set(path, {"hour": hour, "count": count + 1})

        try:
            await self._docs.transaction(fn)
        except Exception as exc:  # noqa: BLE001 - the counter is a brake, never the gate itself
            log.warning("SOS wrong-word count not kept", extra={"error": type(exc).__name__})

    # ---- the budget and the log -------------------------------------------------------------
    async def take(
        self, uid: str, pool: Pool, now: float, decide: Callable[[Budget], str | None]
    ) -> str | None:
        """Reserve one send in `pool` when `decide` finds no reason to refuse; the reason else."""
        path = self._log_path(uid, "budget")

        async def fn(tx: DocTx) -> str | None:
            budget = Budget.of(await tx.get(path), now)
            why = decide(budget)
            if why is None:
                new = budget.plus(pool, now)
                tx.set(
                    path,
                    {"uid": uid, "kind": "budget", "real": list(new.real), "test": list(new.test)},
                )
            return why

        result: str | None = await self._tx(fn)
        return result

    async def give_back(self, uid: str, pool: Pool, stamp: float, now: float) -> None:
        """Return the slot taken at `stamp` (a press that reached nobody); never raises."""
        path = self._log_path(uid, "budget")

        async def fn(tx: DocTx) -> None:
            budget = Budget.of(await tx.get(path), now)
            times = list(getattr(budget, pool))
            if stamp not in times:
                return
            times.remove(stamp)
            new = (
                Budget(tuple(times), budget.test)
                if pool == "real"
                else Budget(budget.real, tuple(times))
            )
            tx.set(
                path, {"uid": uid, "kind": "budget", "real": list(new.real), "test": list(new.test)}
            )

        try:
            await self._tx(fn)
        except (SosOff, SosUnavailable, ValueError) as exc:
            log.warning("an SOS slot was not given back", extra={"error": type(exc).__name__})

    async def budget(self, uid: str, now: float) -> Budget:
        try:
            return Budget.of(await self._docs.get(self._log_path(uid, "budget")), now)
        except Exception as exc:  # noqa: BLE001 - the store: plain words
            log.warning("SOS budget unreadable", extra={"error": type(exc).__name__})
            raise SosUnavailable() from None

    async def log(self, uid: str, entry: Entry) -> None:
        name = f"{int(self._now().timestamp())}{secrets.token_hex(3)}"
        doc = entry.doc(uid)
        last = {"uid": uid, "kind": "last", "entry": doc}
        await self._write(
            [Set(self._log_path(uid, name), doc), Set(self._log_path(uid, "last"), last)]
        )

    async def last(self, uid: str) -> Doc | None:
        try:
            doc = await self._docs.get(self._log_path(uid, "last"))
        except Exception as exc:  # noqa: BLE001 - the card says it couldn't check
            log.warning("SOS last entry unreadable", extra={"error": type(exc).__name__})
            raise SosUnavailable() from None
        entry = doc.get("entry") if doc else None
        return entry if isinstance(entry, dict) else None

    async def _write(self, ops: Sequence[Set | Delete]) -> None:
        try:
            await self._docs.write(list(ops))
        except Exception as exc:  # noqa: BLE001 - the store: plain words
            log.warning("SOS store write failed", extra={"error": type(exc).__name__})
            raise SosUnavailable() from None

    async def _rows(self, coll: str, uid: str) -> list[tuple[str, Doc]]:
        try:
            return await self._docs.query(Query(f"{self._prefix}{coll}", where=("uid", _uid(uid))))
        except Exception as exc:  # noqa: BLE001 - the store: plain words
            log.warning("SOS documents unlisted", extra={"error": type(exc).__name__})
            raise SosUnavailable() from None

    async def log_count(self, uid: str) -> int:
        rows = await self._rows("sos_log", uid)
        return sum(1 for i, _ in rows if not _special(i))

    async def logs(self, uid: str) -> list[Doc]:
        rows = await self._rows("sos_log", uid)
        out = [d for i, d in rows if not _special(i)]
        return sorted(out, key=lambda d: str(d.get("at", "")))

    async def sweep(self, uid: str, *, keep_from: datetime, now: float) -> int:
        """Log entries older than `keep_from`, and join words that ran out."""
        cut = keep_from.isoformat()
        logs = [
            f"{self._prefix}sos_log/{i}"
            for i, d in await self._rows("sos_log", uid)
            if not i.endswith("_budget") and _at(i, d) < cut
        ]
        joins = [
            f"{self._prefix}sos_join/{i}"
            for i, d in await self._rows("sos_join", uid)
            if not isinstance(d.get("until"), int | float) or float(d["until"]) < now
        ]
        gone = (logs + joins)[:SWEEP_MAX]
        if gone:
            await self._write([Delete(p) for p in gone])
        return len(gone)

    async def delete_all(self, uid: str) -> int:
        """Everything of his: the book, join words, the log. The send limits' times STAY (a delete
        never resets the 3 an hour and 10 a day). It deletes even when the book will not open.
        Returns how many contacts and log entries went (the count the dashboard showed)."""
        rows = await self._rows("sos_log", uid)
        logs = [f"{self._prefix}sos_log/{i}" for i, _ in rows if not i.endswith("_budget")]
        joins = [f"{self._prefix}sos_join/{i}" for i, _ in await self._rows("sos_join", uid)]
        contacts = 0
        if self.sealed:
            try:
                contacts = len((await self.book(uid)).contacts)
            except SosUnavailable:
                log.warning("the SOS book would not open: deleted without counting it")
        await self._write([Delete(p) for p in [*logs, *joins, self._book_path(uid)]])
        return contacts + sum(1 for i, _ in rows if not _special(i))


__all__ = [
    "JOIN_S",
    "PURPOSE",
    "WRONG_GLOBAL_PER_HOUR",
    "WRONG_PER_CHAT",
    "Budget",
    "Entry",
    "SosOff",
    "SosStore",
    "SosUnavailable",
]
