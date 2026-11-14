# src/jarvis/watch/store.py
"""The watch's documents on the Docs port (docs/plans/r7-mobile.md data model, D17).

    {prefix}watch_days/{uid}_{date}   uid, date, v, kid, blob = AES-GCM(JSON StoredDay) under the
                                      keyring's `watch` key, AAD "watch_days/{uid}_{date}/v1" (a
                                      blob moved to another day does not open); updated_at
    {prefix}watch_state/{uid}         last_sync, first_sync, last_data_day (newest DATE with data),
                                      kinds {steps, heart, sleep}: which arrive (yes / no, never a
                                      value), first_refused / refused (a run of refused syncs),
                                      stale_told: the silence he was told about (the moment it
                                      counted from; a good sync clears it)

No keyring: `WatchOff`, nothing is written (never in clear). A document that cannot be read or
opened raises `WatchUnavailable`; a stored day that will not open is replaced only by the
phone's own sync of that day (logged), never by a guess. Logs carry class names and
counts only, never a value. A night he typed is kept inside the sealed day (so it is sealed too,
and a sync of that day never drops it). Days are kept `watch_keep_days` (400) and then swept.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import Any

from pydantic import ValidationError

from jarvis.integrations.vault import VaultError
from jarvis.keyring import KEY_ID, Keyring
from jarvis.logging import get_logger
from jarvis.storage.docs import Delete, Doc, Docs, DocTx, Query, Set
from jarvis.storage.sessions import safe_id
from jarvis.watch.models import DayIn, Session, StoredDay

log = get_logger(__name__)
PURPOSE = "watch"
VERSION = 1
KINDS = ("steps", "heart", "sleep")
SWEEP_MAX = 500  # documents one sweep may delete for one owner


class WatchOff(RuntimeError):
    WORDS = "Watch data is off, Sir: JARVIS has no token key to keep it sealed."

    def __init__(self) -> None:
        super().__init__(self.WORDS)


class WatchUnavailable(RuntimeError):
    WORDS = "Your watch data couldn't be read just now, Sir. Please try again in a moment."

    def __init__(self) -> None:
        super().__init__(self.WORDS)


@dataclass(frozen=True)
class WatchState:
    last_sync: datetime | None = None
    kinds: Mapping[str, bool] = field(default_factory=lambda: dict.fromkeys(KINDS, False))
    stale_told: datetime | None = None
    first_sync: datetime | None = None
    last_data_day: date | None = None
    first_refused: datetime | None = None
    refused: int = 0


def _uid(uid: str) -> str:
    if not isinstance(uid, str) or not safe_id(uid):
        raise ValueError("invalid user id")
    return uid


def _when(v: object) -> datetime | None:
    if not isinstance(v, str):
        return None
    try:
        at = datetime.fromisoformat(v)
    except ValueError:
        return None
    return at if at.tzinfo is not None else at.replace(tzinfo=UTC)


def _day_of(v: object) -> date | None:
    try:
        return date.fromisoformat(v) if isinstance(v, str) else None
    except ValueError:
        return None


class WatchStore:
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

    def _ringed(self) -> Keyring:
        if self._ring is None:
            raise WatchOff()
        return self._ring

    def _day_path(self, uid: str, d: date) -> str:
        return f"{self._prefix}watch_days/{_uid(uid)}_{d.isoformat()}"

    def _state_path(self, uid: str) -> str:
        return f"{self._prefix}watch_state/{_uid(uid)}"

    @staticmethod
    def _aad(uid: str, d: date) -> str:
        return f"watch_days/{uid}_{d.isoformat()}/v1"

    # ---- sealing ----------------------------------------------------------------------------
    def _seal(self, uid: str, d: date, day: StoredDay) -> Doc:
        plain = day.model_dump_json(exclude_none=False).encode()
        blob = self._ringed().cipher(PURPOSE).encrypt(plain, aad=self._aad(uid, d))
        return {
            "uid": uid,
            "date": d.isoformat(),
            "v": VERSION,
            "kid": KEY_ID,
            "blob": blob,
            "updated_at": self._now().isoformat(),
        }

    def _open(self, uid: str, d: date, doc: Doc) -> StoredDay:
        try:
            raw = self._ringed().cipher(PURPOSE).decrypt(str(doc["blob"]), aad=self._aad(uid, d))
            return StoredDay.model_validate(json.loads(raw))
        except WatchOff:
            raise
        except (KeyError, TypeError, ValueError, VaultError, ValidationError) as exc:
            log.error("a sealed watch day didn't open", extra={"error": type(exc).__name__})
            raise WatchUnavailable() from None

    async def _get(self, path: str) -> Doc | None:
        try:
            return await self._docs.get(path)
        except Exception as exc:  # noqa: BLE001 - the store: plain words
            log.warning("watch store unreadable", extra={"error": type(exc).__name__})
            raise WatchUnavailable() from None

    async def _write(self, ops: Sequence[Set | Delete]) -> None:
        try:
            await self._docs.write(list(ops))
        except Exception as exc:  # noqa: BLE001 - the store: plain words
            log.warning("watch store write failed", extra={"error": type(exc).__name__})
            raise WatchUnavailable() from None

    # ---- days -------------------------------------------------------------------------------
    async def day(self, uid: str, d: date) -> StoredDay | None:
        self._ringed()
        doc = await self._get(self._day_path(uid, d))
        return None if doc is None else self._open(uid, d, doc)

    async def days(self, uid: str, dates: Sequence[date]) -> dict[date, StoredDay]:
        self._ringed()
        got = await asyncio.gather(*(self.day(uid, d) for d in dates))
        return {d: g for d, g in zip(dates, got, strict=True) if g is not None}

    async def _tx(self, fn: Callable[[DocTx], Awaitable[Any]]) -> Any:
        try:
            return await self._docs.transaction(fn)
        except (WatchOff, WatchUnavailable, ValueError):
            raise
        except Exception as exc:  # noqa: BLE001 - the store: plain words
            log.warning("watch store transaction failed", extra={"error": type(exc).__name__})
            raise WatchUnavailable() from None

    async def put(self, uid: str, days: Sequence[DayIn]) -> int:
        """The phone's days replace what was kept for those days; a typed night stays. All in ONE
        transaction (a typed night saved at the same moment, or another sync, is never lost). A
        stored day that will not open is replaced by the phone's (and logged), so one bad day never
        blocks every later sync."""
        self._ringed()
        state_path = self._state_path(uid)
        now = self._now()
        seen = {
            "steps": any(d.steps is not None for d in days),
            "heart": any(d.heart is not None for d in days),
            "sleep": any(bool(d.sleep) for d in days),
        }
        dated = [d.date for d in days if d.steps is not None or d.heart is not None or d.sleep]

        async def fn(tx: DocTx) -> None:
            old = [(d, await tx.get(self._day_path(uid, d.date))) for d in days]
            state = await tx.get(state_path) or {}
            for d, doc in old:
                typed = None
                if doc is not None:
                    try:
                        typed = self._open(uid, d.date, doc).typed
                    except WatchUnavailable:
                        log.error("a stored watch day will not open: replaced by the phone's")
                stored = StoredDay(steps=d.steps, heart=d.heart, sleep=d.sleep, typed=typed)
                tx.set(self._day_path(uid, d.date), self._seal(uid, d.date, stored))
            tx.set(state_path, self._synced(uid, state, seen, dated, now))

        await self._tx(fn)
        log.info("watch days kept", extra={"days": len(days)})
        return len(days)

    @staticmethod
    def _synced(
        uid: str, old: Doc, seen: Mapping[str, bool], dated: Sequence[date], at: datetime
    ) -> Doc:
        raw = old.get("kinds")
        was: dict[str, Any] = raw if isinstance(raw, dict) else {}
        kinds = {k: was.get(k) is True or bool(seen.get(k)) for k in KINDS}
        newest = max(
            [*dated, *([d] if (d := _day_of(old.get("last_data_day"))) else [])], default=None
        )
        return {
            "uid": uid,
            "last_sync": at.isoformat(),
            "first_sync": old.get("first_sync") or at.isoformat(),
            "last_data_day": newest.isoformat() if newest else None,
            "kinds": kinds,
            "first_refused": None,  # a good sync ends a run of refused ones
            "refused": 0,
            "stale_told": None,  # a sync ends the silence: the next one is told again
        }

    async def set_typed(self, uid: str, d: date, night: Session) -> None:
        self._ringed()
        path = self._day_path(uid, d)

        async def fn(tx: DocTx) -> None:
            doc = await tx.get(path)
            base = self._open(uid, d, doc) if doc is not None else StoredDay()
            tx.set(path, self._seal(uid, d, base.model_copy(update={"typed": night})))

        await self._tx(fn)

    # ---- state ------------------------------------------------------------------------------
    async def state(self, uid: str) -> WatchState:
        doc = await self._get(self._state_path(uid))
        if doc is None:
            return WatchState()
        raw = doc.get("kinds")
        kinds: dict[str, Any] = raw if isinstance(raw, dict) else {}
        count = doc.get("refused")
        return WatchState(
            last_sync=_when(doc.get("last_sync")),
            kinds={k: kinds.get(k) is True for k in KINDS},
            stale_told=_when(doc.get("stale_told")),
            first_sync=_when(doc.get("first_sync")),
            last_data_day=_day_of(doc.get("last_data_day")),
            first_refused=_when(doc.get("first_refused")),
            refused=count if isinstance(count, int) and not isinstance(count, bool) else 0,
        )

    async def note_refused(self, uid: str) -> None:
        """A sync that was refused is counted (never what it held); it never raises."""
        path, now = self._state_path(uid), self._now()

        async def fn(tx: DocTx) -> None:
            doc = await tx.get(path) or {"uid": uid}
            count = doc.get("refused")
            n = count if isinstance(count, int) and not isinstance(count, bool) else 0
            first = doc.get("first_refused") or now.isoformat()
            tx.set(path, {**doc, "first_refused": first, "refused": n + 1})

        try:
            await self._tx(fn)
        except (WatchUnavailable, ValueError) as exc:
            log.warning("a refused sync was not counted", extra={"error": type(exc).__name__})

    async def mark_told(self, uid: str, silence: datetime) -> None:
        """He was told about the silence that counts from `silence`; only that field changes."""
        path = self._state_path(uid)

        async def fn(tx: DocTx) -> None:
            doc = await tx.get(path)
            if doc is not None:
                tx.set(path, {**doc, "stale_told": silence.isoformat()})

        await self._tx(fn)

    # ---- housekeeping and privacy ----------------------------------------------------------------
    async def _ids(self, uid: str) -> list[tuple[str, str]]:
        """(document id, its date) of every kept day."""
        try:
            rows = await self._docs.query(
                Query(f"{self._prefix}watch_days", where=("uid", _uid(uid)))
            )
        except Exception as exc:  # noqa: BLE001 - the store: plain words
            log.warning("watch days unlisted", extra={"error": type(exc).__name__})
            raise WatchUnavailable() from None
        return [(doc_id, str(doc.get("date", ""))) for doc_id, doc in rows]

    async def count(self, uid: str) -> int:
        return len(await self._ids(uid))

    async def dates(self, uid: str) -> list[date]:
        out = []
        for _, d in await self._ids(uid):
            try:
                out.append(date.fromisoformat(d))
            except ValueError:
                continue
        return sorted(out)

    async def sweep(self, uid: str, *, keep_from: date) -> int:
        old = [doc_id for doc_id, d in await self._ids(uid) if d < keep_from.isoformat()]
        old = old[:SWEEP_MAX]
        if old:
            await self._write([Delete(f"{self._prefix}watch_days/{i}") for i in old])
        return len(old)

    async def delete_all(self, uid: str) -> int:
        ids = [doc_id for doc_id, _ in await self._ids(uid)]
        ops: list[Set | Delete] = [Delete(f"{self._prefix}watch_days/{i}") for i in ids]
        ops.append(Delete(self._state_path(uid)))
        await self._write(ops)
        return len(ids)

    async def export(self, uid: str) -> list[dict[str, Any]]:
        out = []
        for d in await self.dates(uid):
            got = await self.day(uid, d)
            if got is not None:
                out.append({"date": d.isoformat(), **got.model_dump(mode="json")})
        return out


__all__ = ["KINDS", "PURPOSE", "WatchOff", "WatchState", "WatchStore", "WatchUnavailable"]
