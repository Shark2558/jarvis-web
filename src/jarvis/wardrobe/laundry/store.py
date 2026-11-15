# src/jarvis/wardrobe/laundry/store.py
"""R13 Part B's documents (docs/plans/r13-wardrobe.md "Data model", D11), sealed with the
`wardrobe` key; every one carries `updated_at` (R14's drill samples on it).

    {prefix}wardrobe_laundry/{uid}        {v, kid, blob, updated_at}  open loads (<= 50) and
        outside batches (<= 20); closed ones 90 days. AAD `wardrobe/laundry/{uid}/v1`
    {prefix}wardrobe_review/{uid}         {v, kid, blob, updated_at}  the review queue (<= 100
        open: pending deposits, holds, conflicts, stale checks); resolved 30 days.
        AAD `wardrobe/review/{uid}/v1`
    {prefix}wardrobe_told/{uid}_{key}     {uid, part, updated_at}  once-only claims, B's keys
        start `laundry_` (C's `styling_`); no seal: the key holds ids and a day, never his words

Reads go through a getter (`tx.get` inside A's commit, `docs.get` outside); writes are storage
ops handed to A's commit (`Commit.extra`), never written through `tx`. A document that can't be
read or opened is `LaundryUnavailable` and is never overwritten; without a key nothing is kept
(never in clear). `Change` is what a flow wants written; `LaundryData` is B's `WardrobeData`.
"""

from __future__ import annotations

import json
import re
import secrets
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from jarvis.keyring import Keyring
from jarvis.logging import get_logger
from jarvis.storage.docs import Create, Delete, DocExists, Docs, Query, Set
from jarvis.undo.store import owner_ok
from jarvis.wardrobe.laundry.texts import OFF, UNREADABLE
from jarvis.wardrobe.model import Category, Event, PieceId, PlaceId
from jarvis.wardrobe.states import State

log = get_logger(__name__)

VERSION = 1
PURPOSE = "wardrobe"
PART_PREFIX = "laundry_"  # ports.TOLD_KEY_PREFIX["laundry"]
LOAD_ID = r"^ld_[0-9a-f]{8}$"
BATCH_ID = r"^bt_[0-9a-f]{8}$"
ENTRY_ID = r"^rv_[0-9a-f]{10}$"
_KEY = re.compile(r"^laundry_[A-Za-z0-9_-]{1,100}$")
EntryKind = Literal["hold", "conflict", "pending_deposit", "stale", "rescan", "place"]
Outcome = Literal["these", "none", "moved", "dismiss"]
Origin = Literal["typed", "voice", "outside"]
Getter = Callable[[str], Awaitable[dict[str, Any] | None]]


class LaundryUnavailable(RuntimeError):
    """Laundry can't be read or saved right now, or is off (plain words)."""


class _Rec(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class Load(_Rec):
    id: str = Field(pattern=LOAD_ID)
    started_at: datetime
    pieces: tuple[PieceId, ...] = Field(min_length=1, max_length=50)  # confirmed ids only
    back: tuple[PieceId, ...] = ()  # returned, in order
    closed_at: datetime | None = None


class Batch(_Rec):
    id: str = Field(pattern=BATCH_ID)
    shop: str = Field(min_length=1, max_length=40)  # his label (no number, no address)
    bag: str = Field(default="", max_length=24)
    origin: Origin = "typed"  # the shop's label: typed, spoken, or from a round with outside words
    pieces: tuple[PieceId, ...] = Field(min_length=1, max_length=50)
    back: tuple[PieceId, ...] = ()
    due: date | None = None
    sent_at: datetime
    short: bool = False  # came back in part ("short delivery")
    closed_at: datetime | None = None


class LaundryDoc(_Rec):
    loads: tuple[Load, ...] = ()
    batches: tuple[Batch, ...] = ()


class Entry(_Rec):
    """One review entry. `pieces`: the pieces THIS entry holds (or asks about, for a blind
    period); `candidates`: the pieces it names (a pending deposit's plausible ones); `events`: the
    event ids it covers (the fold's needs for them are already answered here)."""

    id: str = Field(pattern=ENTRY_ID)
    kind: EntryKind
    reason: str = Field(default="", max_length=24)  # a fixed word, never his text
    pieces: tuple[PieceId, ...] = Field(default=(), max_length=200)
    candidates: tuple[PieceId, ...] = Field(default=(), max_length=200)
    events: tuple[str, ...] = Field(default=(), max_length=200)
    count: int = Field(default=0, ge=0, le=20)  # a pending deposit: how many he couldn't show
    step: str | None = Field(default=None, max_length=12)  # an ambiguous move's step
    category: Category | None = None
    place: PlaceId | None = None
    load: str | None = Field(default=None, max_length=24)
    back_to: State | None = None
    since: datetime | None = None  # a blind period's start, as he stated it
    opened_at: datetime
    closed_at: datetime | None = None
    outcome: Outcome | None = None


class ReviewDoc(_Rec):
    entries: tuple[Entry, ...] = ()


def new_entry_id() -> str:
    return f"rv_{secrets.token_hex(5)}"


@dataclass(frozen=True)
class Change:
    """What a flow wants written in A's commit: events, B's new documents (None: unchanged),
    review entries to add (on top of `review`, or of the current queue), and the words and ids
    its answer names. `already`: nothing to do (a second report of the same thing)."""

    events: tuple[Event, ...] = ()
    laundry: LaundryDoc | None = None
    review: ReviewDoc | None = None
    entries: tuple[Entry, ...] = ()
    words: str = ""
    pieces: tuple[str, ...] = ()
    entry: str | None = None
    load: str | None = None
    batch: str | None = None
    already: bool = False


class LaundryStore:
    def __init__(self, docs: Docs | None, keyring: Keyring | None, *, prefix: str) -> None:
        self.docs, self._ring, self._p = docs, keyring, prefix

    @property
    def available(self) -> bool:
        return self.docs is not None and self._ring is not None

    def _need(self) -> tuple[Docs, Keyring]:
        if self.docs is None or self._ring is None:
            raise LaundryUnavailable(OFF)
        return self.docs, self._ring

    @staticmethod
    def _uid(uid: str) -> str:
        if not owner_ok(uid):
            raise ValueError("bad owner id")
        return uid

    def laundry_path(self, uid: str) -> str:
        return f"{self._p}wardrobe_laundry/{self._uid(uid)}"

    def review_path(self, uid: str) -> str:
        return f"{self._p}wardrobe_review/{self._uid(uid)}"

    def told_path(self, uid: str, key: str) -> str:
        if not _KEY.match(key):
            raise ValueError("a laundry claim's key starts with laundry_")
        return f"{self._p}wardrobe_told/{self._uid(uid)}_{key}"

    # ---- sealing -------------------------------------------------------------------------------
    def _seal(self, aad: str, body: BaseModel, now: datetime) -> dict[str, Any]:
        _, ring = self._need()
        plain = json.dumps(body.model_dump(mode="json"), ensure_ascii=False).encode()
        blob = ring.cipher(PURPOSE).encrypt(plain, aad=aad)
        return {"v": VERSION, "kid": ring.kid, "blob": blob, "updated_at": now.isoformat()}

    def _open(self, aad: str, doc: dict[str, Any] | None) -> dict[str, Any] | None:
        _, ring = self._need()
        if doc is None:
            return None
        blob = doc.get("blob")
        if doc.get("v") != VERSION or not isinstance(blob, str):
            raise ValueError("envelope")
        raw = json.loads(ring.cipher(PURPOSE).decrypt(blob, aad=aad))
        if not isinstance(raw, dict):
            raise ValueError("body")
        return raw

    async def _read(self, get: Getter, path: str, aad: str) -> dict[str, Any] | None:
        self._need()
        try:
            return self._open(aad, await get(path))
        except Exception as exc:  # noqa: BLE001 - storage or data trouble: read nothing, write nothing
            log.warning("laundry unreadable", extra={"reason": type(exc).__name__})
            raise LaundryUnavailable(UNREADABLE) from None

    async def read_laundry(self, get: Getter, uid: str) -> LaundryDoc:
        raw = await self._read(get, self.laundry_path(uid), f"wardrobe/laundry/{uid}/v1")
        return LaundryDoc.model_validate(raw) if raw else LaundryDoc()

    async def read_review(self, get: Getter, uid: str) -> ReviewDoc:
        raw = await self._read(get, self.review_path(uid), f"wardrobe/review/{uid}/v1")
        return ReviewDoc.model_validate(raw) if raw else ReviewDoc()

    def laundry_op(self, uid: str, doc: LaundryDoc, now: datetime) -> Set:
        body = self._seal(f"wardrobe/laundry/{uid}/v1", doc, now)
        return Set(self.laundry_path(uid), body)

    def review_op(self, uid: str, doc: ReviewDoc, now: datetime) -> Set:
        return Set(self.review_path(uid), self._seal(f"wardrobe/review/{uid}/v1", doc, now))

    async def write(self, ops: list[Set | Create | Delete]) -> None:
        docs, _ = self._need()
        await docs.write(ops)

    # ---- once-only claims (`wardrobe_told`) ----------------------------------------------------
    async def claim(self, uid: str, key: str, now: datetime) -> bool:
        docs, _ = self._need()
        body = {"uid": uid, "part": "laundry", "updated_at": now.isoformat()}
        try:
            await docs.write([Create(self.told_path(uid, key), body)])
        except DocExists:
            return False
        return True

    async def release(self, uid: str, key: str) -> None:
        docs, _ = self._need()
        await docs.write([Delete(self.told_path(uid, key))])

    async def claims(self, uid: str) -> list[tuple[str, datetime]]:
        """B's claims for him: (path, when written)."""
        docs, _ = self._need()
        rows = await docs.query(Query(f"{self._p}wardrobe_told", where=("uid", uid)))
        out: list[tuple[str, datetime]] = []
        for doc_id, body in rows:
            if body.get("part") == "laundry" and isinstance(body.get("updated_at"), str):
                path = f"{self._p}wardrobe_told/{doc_id}"
                out.append((path, datetime.fromisoformat(body["updated_at"])))
        return out


class LaundryData:
    """B's data for D's Privacy rows (D20): counts, a plain export, delete everything of B's."""

    name = "laundry"

    def __init__(self, store: LaundryStore) -> None:
        self._s = store

    async def _docs(self, uid: str) -> tuple[LaundryDoc, ReviewDoc]:
        docs = self._s.docs
        if not self._s.available or docs is None:
            return LaundryDoc(), ReviewDoc()
        return await self._s.read_laundry(docs.get, uid), await self._s.read_review(docs.get, uid)

    async def count(self, uid: str) -> int:
        laundry, review = await self._docs(uid)
        return (
            sum(1 for x in laundry.loads if x.closed_at is None)
            + sum(1 for b in laundry.batches if b.closed_at is None)
            + sum(1 for e in review.entries if e.closed_at is None)
        )

    async def export(self, uid: str) -> dict[str, Any]:
        laundry, review = await self._docs(uid)
        return {
            "loads": [x.model_dump(mode="json") for x in laundry.loads],
            "batches": [b.model_dump(mode="json") for b in laundry.batches],
            "review": [e.model_dump(mode="json") for e in review.entries],
        }

    async def delete(self, uid: str) -> int:
        if not self._s.available or self._s.docs is None:
            return 0
        docs = self._s.docs
        paths = [self._s.laundry_path(uid), self._s.review_path(uid)]
        paths = [p for p in paths if await docs.get(p) is not None]
        paths += [p for p, _ in await self._s.claims(uid)]
        if paths:
            await docs.write([Delete(p) for p in paths])
        return len(paths)


__all__ = [
    "BATCH_ID",
    "ENTRY_ID",
    "LOAD_ID",
    "Batch",
    "Change",
    "Entry",
    "EntryKind",
    "Getter",
    "LaundryData",
    "LaundryDoc",
    "LaundryStore",
    "LaundryUnavailable",
    "Load",
    "Origin",
    "Outcome",
    "ReviewDoc",
    "new_entry_id",
]
