# src/jarvis/series/store.py
"""Where followed plans are kept (R11.1 O2b; docs/plans/r11-1-observations.md D6; Layer 7).

    {prefix}series/{uid}            the owner's plans (`models.Book`), one document, changed only
                                    inside a transaction (`change`)
    {prefix}series_told/{uid}_{key} one document per check-in question, created in a transaction
                                    BEFORE the question is sent (`claim`), so it goes out once;
                                    swept after `TOLD_KEEP_DAYS`

Nothing here is sealed: a plan holds calendar event ids, times and short titles the owner already
keeps in Google Calendar (plan I0 seam 5). A document that can't be read as a `Book` raises
`PlansUnreadable` (plain words): nothing is guessed and nothing is overwritten.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from datetime import datetime, timedelta

from pydantic import ValidationError

from jarvis.logging import get_logger
from jarvis.series.models import Book
from jarvis.storage.docs import Delete, DocExists, Docs, DocTx, Query

log = get_logger(__name__)

TOLD_KEEP_DAYS = 60
_UID = re.compile(r"[A-Za-z0-9_.@-]{1,128}")
_KEY = re.compile(r"[a-f0-9]{8,64}")
UNREADABLE = "Your plans can't be read just now, Sir."


class PlansUnreadable(RuntimeError):
    """The stored plans could not be read; the message is plain words for the owner."""

    def __init__(self) -> None:
        super().__init__(UNREADABLE)


def _owner(uid: str) -> str:
    if not isinstance(uid, str) or not _UID.fullmatch(uid):
        raise ValueError("not a valid owner id")
    return uid


class SeriesStore:
    def __init__(self, docs: Docs, *, prefix: str = "jarvis_") -> None:
        self._docs = docs
        self._prefix = prefix

    def _path(self, uid: str) -> str:
        return f"{self._prefix}series/{_owner(uid)}"

    def _told(self, uid: str, key: str) -> str:
        if not _KEY.fullmatch(key):
            raise ValueError("not a valid check-in key")
        return f"{self._prefix}series_told/{_owner(uid)}_{key}"

    @staticmethod
    def _book(raw: dict[str, object] | None) -> Book:
        if raw is None:
            return Book()
        try:
            return Book.model_validate(raw)
        except ValidationError:
            log.error("the plans document does not read as plans; left untouched")
            raise PlansUnreadable() from None

    async def load(self, uid: str) -> Book:
        return self._book(await self._docs.get(self._path(uid)))

    async def change(self, uid: str, fn: Callable[[Book], Book]) -> Book:
        """Read, change and write the owner's plans in one transaction (`fn` may be retried and
        may raise to change nothing)."""
        path = self._path(uid)

        async def work(tx: DocTx) -> Book:
            book = fn(self._book(await tx.get(path)))
            tx.set(path, book.model_dump(mode="json"))
            return book

        return await self._docs.transaction(work)

    async def claim(self, uid: str, key: str, at: datetime) -> bool:
        """True exactly once per (owner, key): the caller then asks the question."""
        path = self._told(uid, key)

        async def work(tx: DocTx) -> bool:
            if await tx.get(path) is not None:
                return False
            tx.create(path, {"uid": uid, "at": at.isoformat()})
            return True

        try:
            return await self._docs.transaction(work)
        except DocExists:  # another instance asked in the same moment
            return False

    async def told(self, uid: str, key: str) -> bool:
        """Was this question already claimed (asked, or being asked)?"""
        return await self._docs.get(self._told(uid, key)) is not None

    async def release(self, uid: str, key: str) -> None:
        """Give a claim back: the question could not be sent, so a later run may try again."""
        await self._docs.write([Delete(self._told(uid, key))])

    async def _told_rows(self, uid: str) -> list[tuple[str, dict[str, object]]]:
        q = Query(f"{self._prefix}series_told", where=("uid", _owner(uid)))
        return await self._docs.query(q)

    async def sweep(self, uid: str, now: datetime) -> int:
        """Drop the owner's check-in claims older than `TOLD_KEEP_DAYS`."""
        before = (now - timedelta(days=TOLD_KEEP_DAYS)).isoformat()
        old = [doc_id for doc_id, d in await self._told_rows(uid) if str(d.get("at", "")) < before]
        if old:
            await self._docs.write([Delete(f"{self._prefix}series_told/{i}") for i in old])
        return len(old)

    async def delete(self, uid: str) -> int:
        """Everything kept about the owner's plans (never the calendar). Returns how many plans."""
        plans = len((await self.load(uid)).plans)
        told = [Delete(f"{self._prefix}series_told/{i}") for i, _ in await self._told_rows(uid)]
        await self._docs.write([Delete(self._path(uid)), *told])
        return plans


__all__ = ["TOLD_KEEP_DAYS", "UNREADABLE", "PlansUnreadable", "SeriesStore"]
