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
document and the same <= 3 s cache entry (`view`: one lookup for both). A later `set` starts a
fresh document: while a lock is on every owner session is held anyway, and its own lift writes a
later mark.
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
from jarvis.storage.docs import Docs, DocTx, Set

log = get_logger(__name__)

CACHE_S = 3.0
UNREADABLE = (
    "JARVIS can't tell whether a guest show is running, so the console is closed for a moment. "
    "Try again shortly."
)
AFTER = "sessions_valid_after"
_LOCK_KEYS = ("id", "bk", "since")
View = tuple[ShowLockState | None, float | None]  # (the lock, sessions valid after)


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
        state = ShowLockState(id=f"bl_{secrets.token_hex(6)}", bk=session_id, since=now.isoformat())
        await self._docs.write([Set(self._path(uid), state.model_dump())])
        self._cache[uid] = ((state, None), self._clock())
        return state

    async def lift(self, uid: str, lock_id: str, *, signed_out_before: float | None = None) -> bool:
        """Lift `uid`'s lock if it is `lock_id`; with `signed_out_before`, every owner's cookie
        sessions issued before it stop counting (in the same transaction)."""
        others = [o for o in self._owners if o != uid] if signed_out_before is not None else []

        async def work(tx: DocTx) -> bool:
            raw = await tx.get(self._path(uid))
            if raw is None or raw.get("id") != lock_id:
                return False
            held = [(o, await tx.get(self._path(o))) for o in others]
            if signed_out_before is None:
                tx.delete(self._path(uid))
                return True
            tx.set(self._path(uid), {AFTER: signed_out_before})
            for other, doc in held:
                tx.set(self._path(other), {**(doc or {}), AFTER: signed_out_before})
            return True

        lifted = await self._docs.transaction(work)
        for other in others:
            self._cache.pop(other, None)
        if lifted:
            self._cache[uid] = ((None, signed_out_before), self._clock())
        else:
            self._cache.pop(uid, None)  # read it again next time
        return lifted


__all__ = ["AFTER", "CACHE_S", "UNREADABLE", "DocShowLock"]
