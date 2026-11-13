# src/jarvis/vision/store.py
"""R7 D12, data model: the camera results he pressed Keep on (never a frame, never a picture).

    {prefix}vision_results/{uid}_{yyyymmdd}   uid, day, v, kid, n (how many), updated_at, and
                                              blob = AES-GCM(JSON {day, items}) under the
                                              keyring's `vision` key, AAD "vision_results/{uid}/v1"

An item is `{id: "vr_<12 hex>", kept_at, task, v, at, ms, device, ok, data, quality}`: a Result
(`jarvis.vision.results`) whose data fits its task's schema, as the schema writes it. Anything
else is dropped (`Dropped`) and nothing is written: a result is never repaired. A day keeps at most
`PER_DAY_MAX` items; days older than `keep_days` (the setting `vision_keep_days`, 90) are never
listed and the daily sweep deletes them. The day inside the blob must equal the document's (a
moved document is refused). No keyring: `VisionOff` and nothing is kept (never in clear). A
document that does not open raises `VisionUnavailable` and is never overwritten. Logs carry class
names and counts only.

Size (Firestore keeps a document under 1 MiB): one result is at most `ITEM_MAX` characters of JSON
(`TooBig`), and a day's sealed blob at most `BLOB_MAX` (`DayFull`, the same plain sentence as the
100-a-day cap). One day that does not open never hides, blocks or deletes the others.
"""

from __future__ import annotations

import json
import re
import secrets
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any

from jarvis.integrations.vault import VaultError
from jarvis.keyring import KEY_ID, Keyring
from jarvis.logging import get_logger
from jarvis.notify.quiet import local
from jarvis.storage.docs import Delete, Doc, Docs, DocTx, Query
from jarvis.storage.sessions import safe_id
from jarvis.vision.results import DATA, Result, parse_result

log = get_logger(__name__)

COLLECTION = "vision_results"
PURPOSE = "vision"
VERSION = 1
PER_DAY_MAX = 100
KEEP_DAYS = 90
RESULT_ID = re.compile(r"^vr_[0-9a-f]{12}$")
ITEM_MAX = 20_000  # characters of JSON in one kept result (20 codes of 2,000 are refused)
BLOB_MAX = 900_000  # characters of one day's sealed blob: under Firestore's 1 MiB document


class VisionOff(RuntimeError):
    def __init__(self) -> None:
        super().__init__(
            "Kept camera results are off, Sir: JARVIS has no token key to keep them sealed."
        )


class VisionUnavailable(RuntimeError):
    def __init__(self) -> None:
        super().__init__("Your kept camera results couldn't be read just now, Sir.")


class Dropped(ValueError):
    def __init__(self) -> None:
        super().__init__("That result doesn't fit its task, so it was dropped.")


class TooBig(Dropped):
    def __init__(self) -> None:
        ValueError.__init__(self, "That result is too big to keep, Sir.")


class DayFull(ValueError):
    def __init__(self) -> None:
        super().__init__("That day's results are full, Sir. Delete some first.")


@dataclass(frozen=True)
class Page:
    """A slice of the kept results, newest first: `total` readable results, `unreadable` days."""

    items: list[dict[str, Any]]
    total: int
    unreadable: int


def _uid(uid: str) -> str:
    if not isinstance(uid, str) or not safe_id(uid):
        raise ValueError("invalid user id")
    return uid


def item_of(result: Result, rid: str, kept_at: str) -> dict[str, Any]:
    """The stored form: the Result with its data re-written by its task's schema."""
    data = DATA[result.task].model_validate(result.data).model_dump(mode="json")
    item = {"id": rid, "kept_at": kept_at, **result.model_dump(mode="json"), "data": data}
    if len(json.dumps(item, ensure_ascii=False, separators=(",", ":"))) > ITEM_MAX:
        raise TooBig()
    return item


class VisionStore:
    def __init__(
        self,
        docs: Docs,
        keyring: Keyring | None,
        *,
        prefix: str = "jarvis_",
        now: Callable[[], datetime],
        tz: str = "Asia/Kolkata",
        keep_days: int = KEEP_DAYS,
    ) -> None:
        self._docs = docs
        self._ring = keyring
        self._prefix = prefix
        self._now = now
        self._tz = tz
        self.keep_days = max(1, int(keep_days))

    @property
    def sealed(self) -> bool:
        return self._ring is not None

    # ---- paths, days, the seal ------------------------------------------------------------------
    def _today(self) -> date:
        return local(self._now(), self._tz).date()

    def _first_kept_day(self) -> str:
        return (self._today() - timedelta(days=self.keep_days - 1)).isoformat()

    def _path(self, uid: str, day: str) -> str:
        return f"{self._prefix}{COLLECTION}/{_uid(uid)}_{day.replace('-', '')}"

    def _cipher_ring(self) -> Keyring:
        if self._ring is None:
            raise VisionOff()
        return self._ring

    def _seal(self, uid: str, day: str, items: list[dict[str, Any]]) -> str:
        plain = json.dumps({"day": day, "items": items}, ensure_ascii=False, separators=(",", ":"))
        aad = f"{COLLECTION}/{uid}/v1"
        return self._cipher_ring().cipher(PURPOSE).encrypt(plain.encode(), aad=aad)

    def _open(self, uid: str, doc: Doc) -> list[dict[str, Any]]:
        try:
            raw = (
                self._cipher_ring()
                .cipher(PURPOSE)
                .decrypt(str(doc["blob"]), aad=f"{COLLECTION}/{uid}/v1")
            )
            data = json.loads(raw)
            items = data["items"] if isinstance(data, dict) else None
            if data.get("day") != doc.get("day") or not isinstance(items, list):
                raise ValueError("a vision day that moved or is not a list")
        except (KeyError, TypeError, ValueError, AttributeError, VaultError) as exc:
            log.error("a kept vision day did not open", extra={"error": type(exc).__name__})
            raise VisionUnavailable() from None
        return [i for i in items if isinstance(i, dict)]

    def _doc(self, uid: str, day: str, items: list[dict[str, Any]]) -> Doc:
        return {
            "uid": uid,
            "day": day,
            "v": VERSION,
            "kid": KEY_ID,
            "blob": self._seal(uid, day, items),
            "n": len(items),
            "updated_at": self._now().isoformat(),
        }

    async def _rows(self, uid: str) -> list[tuple[str, Doc]]:
        try:
            return await self._docs.query(
                Query(f"{self._prefix}{COLLECTION}", where=("uid", _uid(uid)))
            )
        except ValueError:
            raise
        except Exception as exc:  # noqa: BLE001 - the store: plain words, the class in the log
            log.warning("kept vision days unreadable", extra={"error": type(exc).__name__})
            raise VisionUnavailable() from None

    # ---- the public methods ---------------------------------------------------------------------
    async def keep(self, uid: str, raw: object) -> dict[str, Any]:
        """Keep one result he pressed Keep on; `Dropped` when it does not fit its schema."""
        _uid(uid)
        found = parse_result(raw)
        if found is None or not found.ok:
            raise Dropped()
        self._cipher_ring()
        day = self._today().isoformat()
        path = self._path(uid, day)
        item = item_of(found, "vr_" + secrets.token_hex(6), self._now().isoformat())

        async def work(tx: DocTx) -> dict[str, Any]:
            old = await tx.get(path)
            items = self._open(uid, old) if old else []
            if len(items) >= PER_DAY_MAX:
                raise DayFull()
            doc = self._doc(uid, day, [*items, item])
            if len(str(doc["blob"])) > BLOB_MAX:
                raise DayFull()
            tx.set(path, doc)
            return item

        return await self._docs.transaction(work)

    async def _readable(self, uid: str, days: int) -> tuple[list[dict[str, Any]], int]:
        """Newest-first results of the last `days` days, and how many days did not open."""
        self._cipher_ring()
        span = max(1, min(int(days), self.keep_days))
        first = (self._today() - timedelta(days=span - 1)).isoformat()
        found: list[tuple[str, str, int, dict[str, Any]]] = []
        unreadable = 0
        for _, doc in await self._rows(uid):
            day = str(doc.get("day", ""))
            if day < first:
                continue
            try:
                items = self._open(uid, doc)
            except VisionUnavailable:
                unreadable += 1
                continue
            found.extend((str(i.get("kept_at", "")), day, n, i) for n, i in enumerate(items))
        if unreadable and not found:
            raise VisionUnavailable()  # nothing opened at all: a wrong key, not one bad day
        found.sort(key=lambda f: f[:3], reverse=True)
        return [item for *_, item in found], unreadable

    async def list(self, uid: str, *, days: int = 7) -> list[dict[str, Any]]:
        """His kept results of the last `days` days (at most the keep), newest first. A day that
        does not open is left out (and logged), never the others."""
        return (await self._readable(uid, days))[0]

    async def page(self, uid: str, *, days: int = 7, limit: int = 50, offset: int = 0) -> Page:
        """One page of `list`, with the total and how many days could not be opened."""
        items, unreadable = await self._readable(uid, days)
        start = max(0, int(offset))
        return Page(items[start : start + max(1, int(limit))], len(items), unreadable)

    async def count(self, uid: str) -> int:
        """How many results are kept inside the keep (0 without a key)."""
        if not self.sealed:
            return 0
        first = self._first_kept_day()
        return sum(
            int(d.get("n", 0)) for _, d in await self._rows(uid) if str(d.get("day")) >= first
        )

    async def delete(self, uid: str, rid: str) -> bool:
        """One kept result; False when there is none with that id."""
        if not isinstance(rid, str) or not RESULT_ID.match(rid):
            return False
        for _, doc in await self._rows(uid):
            day = str(doc.get("day", ""))
            try:
                found = any(i.get("id") == rid for i in self._open(uid, doc))
            except VisionUnavailable:
                continue  # that day stays as it is; the others can still be deleted from
            if found:
                return await self._drop(uid, day, rid)
        return False

    async def _drop(self, uid: str, day: str, rid: str) -> bool:
        path = self._path(uid, day)

        async def work(tx: DocTx) -> bool:
            old = await tx.get(path)
            items = self._open(uid, old) if old else []
            left = [i for i in items if i.get("id") != rid]
            if len(left) == len(items):
                return False
            if left:
                tx.set(path, self._doc(uid, day, left))
            else:
                tx.delete(path)
            return True

        return await self._docs.transaction(work)

    async def delete_all(self, uid: str) -> int:
        """Every kept result of his (the privacy dashboard's delete): how many went."""
        rows = await self._rows(uid)
        if rows:
            await self._docs.write([Delete(f"{self._prefix}{COLLECTION}/{i}") for i, _ in rows])
        return sum(int(d.get("n", 0)) for _, d in rows)

    async def sweep(self, uid: str) -> int:
        """Delete his days past the keep (the daily job): how many days went."""
        first = self._first_kept_day()
        old = [i for i, d in await self._rows(uid) if str(d.get("day", "")) < first]
        if old:
            await self._docs.write([Delete(f"{self._prefix}{COLLECTION}/{i}") for i in old])
        return len(old)

    async def export(self, uid: str) -> dict[str, Any]:
        """Every kept result of the keep, unsealed for his own export (readable days only)."""
        if not self.sealed:
            return {"results": []}
        return {"results": await self.list(uid, days=self.keep_days)}


__all__ = [
    "COLLECTION",
    "KEEP_DAYS",
    "PER_DAY_MAX",
    "PURPOSE",
    "RESULT_ID",
    "BLOB_MAX",
    "ITEM_MAX",
    "DayFull",
    "Page",
    "TooBig",
    "Dropped",
    "VisionOff",
    "VisionStore",
    "VisionUnavailable",
    "item_of",
    "parse_result",
]
