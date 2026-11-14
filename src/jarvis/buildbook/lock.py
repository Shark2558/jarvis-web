# src/jarvis/buildbook/lock.py
"""The guest lock's store (R6 D10; `ports.ShowLock`). `{prefix}book_lock/{uid}` = {id, bk, since}:
set when a guest session opens, lifted only after a `book_resume` passkey check bound to its id.

`api/book_lock.py::ShowLockMiddleware` reads it on every cookie request of an owner, so reads are
cached per instance for at most `CACHE_S` (3 s): at most one store read per owner per 3 s on each
Cloud Run instance, and another instance sees a new lock within 3 s. A read that fails, or a
document that isn't a lock, raises `LockUnreadable` (the middleware answers 503) and is NOT
cached: never "unlocked" when we can't tell. `set` and `lift` update this instance's cache at once.

Sessions valid after (integrated review SEC-4): a Resume or the emergency unlock lifts with
`signed_out_before=<cookie clock>`; the same document then keeps `{sessions_valid_after}` (for the
owner AND every other owner, whose consoles the lock held too, beside any lock of theirs), and the
middleware clears every cookie session issued before it. It is read WITH the lock, in the same
document and the same <= 3 s cache entry (`view`: one lookup for both). R14 D13 (2): a later
`set` keeps that mark beside the new lock (before R14 it started a fresh document, so a show
opened after "Sign out everywhere" brought the ended sessions back once it was lifted), a lift
without a mark keeps it, and a mark never moves back.
"""

from __future__ import annotations

import secrets
import time
from collections.abc import Callable, Sequence
from datetime import datetime
from typing import Any

from pydantic import ValidationError

from jarvis.buildbook.model import ShowLockState
from jarvis.buildbook.ports import LockUnreadable
from jarvis.logging import get_logger
from jarvis.storage.docs import Docs, DocTx

log = get_logger(__name__)

CACHE_S = 3.0
UNREADABLE = (
    "JARVIS can't tell whether a guest show is running, so the console is closed for a moment. "
    "Try again shortly."
)
AFTER = "sessions_valid_after"
_LOCK_KEYS = ("id", "bk", "since")
View = tuple[ShowLockState | None, float | None]  # (the lock, sessions valid after)


def _mark_of(doc: dict[str, Any] | None) -> float | None:
    """Another owner's mark, read leniently: one that isn't a time is replaced by the new mark (as
    before R14), so it never blocks this owner's Resume."""
    after = (doc or {}).get(AFTER)
    return None if isinstance(after, bool) or not isinstance(after, int | float) else float(after)


def _later(mark: float | None, new: float | None) -> float | None:
    """A "sessions valid after" mark only ever moves forward."""
    if mark is None or new is None:
        return new if mark is None else mark
    return max(mark, new)


class DocShowLock:
    def __init__(
        self,
        docs: Docs,
        *,
        prefix: str = "jarvis_",
        cache_s: float = CACHE_S,
        clock: Callable[[], float] = time.monotonic,
        owners: Sequence[str] = (),
    ) -> None:
        if not 0 <= cache_s <= CACHE_S:
            raise ValueError("the lock is cached for at most 3 seconds")
        self._docs, self._coll = docs, f"{prefix}book_lock"
        self._cache_s, self._clock = cache_s, clock
        self._owners = tuple(dict.fromkeys(owners))
        self._cache: dict[str, tuple[View, float]] = {}

    def _path(self, uid: str) -> str:
        return f"{self._coll}/{uid}"

    @staticmethod
    def _parse(raw: dict[str, Any] | None) -> View:
        if raw is None:
            return None, None
        after = raw.get(AFTER)
        if after is not None and (isinstance(after, bool) or not isinstance(after, int | float)):
            raise LockUnreadable(UNREADABLE)
        mark = None if after is None else float(after)
        if "id" not in raw:
            if set(raw) - {AFTER}:
                raise LockUnreadable(UNREADABLE)
            return None, mark
        try:
            return ShowLockState.model_validate({k: raw.get(k) for k in _LOCK_KEYS}), mark
        except ValidationError:
            raise LockUnreadable(UNREADABLE) from None

    async def _view(self, uid: str) -> View:
        hit = self._cache.get(uid)
        if hit is not None and self._clock() - hit[1] < self._cache_s:
            return hit[0]
        return await self._read(uid)

    async def _read(self, uid: str) -> View:
        try:
            raw = await self._docs.get(self._path(uid))
        except Exception as exc:  # noqa: BLE001 - unknown is locked-and-unknown, never unlocked
            log.error("guest lock unreadable", extra={"error": type(exc).__name__})
            raise LockUnreadable(UNREADABLE) from None
        view = self._parse(raw)
        self._cache[uid] = (view, self._clock())
        return view

    async def get(self, uid: str) -> ShowLockState | None:
        return (await self._view(uid))[0]

    async def view(self, uid: str) -> View:
        """(the lock, sessions valid after) from ONE cache entry or read: the middleware compares
        the mark from the same view it takes the lock from (security re-review #5)."""
        return await self._view(uid)

    async def fresh_view(self, uid: str) -> View:
        """`view` without the cache (the presenting browser's own session says a guest is on)."""
        return await self._read(uid)

    async def valid_after(self, uid: str) -> float | None:
        """When this owner's cookie sessions start counting again (None: no mark)."""
        return (await self._view(uid))[1]

    async def refresh(self, uid: str) -> ShowLockState | None:
        """`get` without the cache (the presenting browser's own session says a guest is on)."""
        return (await self._read(uid))[0]

    async def set(self, uid: str, session_id: str, *, now: datetime) -> ShowLockState:
        """A new lock, in the same transaction as the read of the document's mark, which it keeps
        (R14 D13 (2)): a show opened after "Sign out everywhere" or a Resume never brings the
        sessions that mark ended back. A document it can't read sets nothing (it raises)."""
        state = ShowLockState(id=f"bl_{secrets.token_hex(6)}", bk=session_id, since=now.isoformat())

        async def work(tx: DocTx) -> float | None:
            _, mark = self._parse(await tx.get(self._path(uid)))
            doc = state.model_dump()
            tx.set(self._path(uid), doc if mark is None else {**doc, AFTER: mark})
            return mark

        mark = await self._docs.transaction(work)
        self._cache[uid] = ((state, mark), self._clock())
        return state

    async def lift(self, uid: str, lock_id: str, *, signed_out_before: float | None = None) -> bool:
        """Lift `uid`'s lock if it is `lock_id`; with `signed_out_before`, every owner's cookie
        sessions issued before it stop counting (in the same transaction). An earlier mark stays
        and never moves back (R14 D13 (2)): without `signed_out_before` the lock goes and the
        mark is kept; with it, the later of the two counts. This owner's own document must parse:
        a malformed one raises `LockUnreadable` here as on every read (never read leniently, which
        would drop his own mark); only another owner's mark is lenient (`_mark_of`)."""
        others = [o for o in self._owners if o != uid] if signed_out_before is not None else []

        async def work(tx: DocTx) -> tuple[bool, float | None]:
            raw = await tx.get(self._path(uid))
            if raw is None or raw.get("id") != lock_id:
                return False, None
            held = [(o, await tx.get(self._path(o))) for o in others]
            mark = _later(self._parse(raw)[1], signed_out_before)
            if mark is None:
                tx.delete(self._path(uid))
            else:
                tx.set(self._path(uid), {AFTER: mark})
            for other, doc in held:
                theirs = _later(_mark_of(doc), signed_out_before)
                tx.set(self._path(other), {**(doc or {}), AFTER: theirs})
            return True, mark

        lifted, mark = await self._docs.transaction(work)
        for other in others:
            self._cache.pop(other, None)
        if lifted:
            self._cache[uid] = ((None, mark), self._clock())
        else:
            self._cache.pop(uid, None)  # read it again next time
        return lifted

    async def end_sessions(self, uid: str, *, before: float) -> None:
        """R7 D21 "Sign out everywhere": every cookie session of `uid` issued before `before`
        stops counting (the same mark as a Resume's, kept beside any lock in the same document;
        a mark never moves back). This instance sees it at once, the others within `CACHE_S`."""

        async def work(tx: DocTx) -> View:
            raw = await tx.get(self._path(uid)) or {}
            lock, mark = self._parse(raw)
            after = before if mark is None else max(mark, before)
            tx.set(self._path(uid), {**raw, AFTER: after})
            return lock, after

        self._cache[uid] = (await self._docs.transaction(work), self._clock())


__all__ = ["AFTER", "CACHE_S", "UNREADABLE", "DocShowLock"]
