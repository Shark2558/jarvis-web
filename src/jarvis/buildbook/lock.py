# src/jarvis/buildbook/lock.py
"""The guest lock's store (R6 D10; `ports.ShowLock`). `{prefix}book_lock/{uid}` = {id, bk, since}:
set when a guest session opens, lifted only after a `book_resume` passkey check bound to its id.

`api/book_lock.py::ShowLockMiddleware` reads it on every cookie request of an owner, so reads are
cached per instance for at most `CACHE_S` (3 s): at most one store read per owner per 3 s on each
Cloud Run instance, and another instance sees a new lock within 3 s. A read that fails, or a
document that isn't a lock, raises `LockUnreadable` (the middleware answers 503) and is NOT
cached: never "unlocked" when we can't tell. `set` and `lift` update this instance's cache at once.
"""

from __future__ import annotations

import secrets
import time
from collections.abc import Callable
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


class DocShowLock:
    def __init__(
        self,
        docs: Docs,
        *,
        prefix: str = "jarvis_",
        cache_s: float = CACHE_S,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if not 0 <= cache_s <= CACHE_S:
            raise ValueError("the lock is cached for at most 3 seconds")
        self._docs, self._coll = docs, f"{prefix}book_lock"
        self._cache_s, self._clock = cache_s, clock
        self._cache: dict[str, tuple[ShowLockState | None, float]] = {}

    def _path(self, uid: str) -> str:
        return f"{self._coll}/{uid}"

    @staticmethod
    def _parse(raw: dict[str, Any] | None) -> ShowLockState | None:
        if raw is None:
            return None
        try:
            return ShowLockState.model_validate({k: raw.get(k) for k in ("id", "bk", "since")})
        except ValidationError:
            raise LockUnreadable(UNREADABLE) from None

    async def get(self, uid: str) -> ShowLockState | None:
        hit = self._cache.get(uid)
        if hit is not None and self._clock() - hit[1] < self._cache_s:
            return hit[0]
        return await self.refresh(uid)

    async def refresh(self, uid: str) -> ShowLockState | None:
        """`get` without the cache (the presenting browser's own session says a guest is on)."""
        try:
            raw = await self._docs.get(self._path(uid))
        except Exception as exc:  # noqa: BLE001 - unknown is locked-and-unknown, never unlocked
            log.error("guest lock unreadable", extra={"error": type(exc).__name__})
            raise LockUnreadable(UNREADABLE) from None
        state = self._parse(raw)
        self._cache[uid] = (state, self._clock())
        return state

    async def set(self, uid: str, session_id: str, *, now: datetime) -> ShowLockState:
        state = ShowLockState(id=f"bl_{secrets.token_hex(6)}", bk=session_id, since=now.isoformat())
        await self._docs.write([Set(self._path(uid), state.model_dump())])
        self._cache[uid] = (state, self._clock())
        return state

    async def lift(self, uid: str, lock_id: str) -> bool:
        async def work(tx: DocTx) -> bool:
            raw = await tx.get(self._path(uid))
            if raw is None or raw.get("id") != lock_id:
                return False
            tx.delete(self._path(uid))
            return True

        lifted = await self._docs.transaction(work)
        if lifted:
            self._cache[uid] = (None, self._clock())
        else:
            self._cache.pop(uid, None)  # read it again next time
        return lifted


__all__ = ["CACHE_S", "UNREADABLE", "DocShowLock"]
