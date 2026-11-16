# src/jarvis/memory/inmemory.py
"""Process-local SessionStore. Dev and tests only — state dies with the process."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from jarvis.core.models import Session, SessionSummary
from jarvis.memory.base import SessionStore, summarize


class InMemorySessionStore(SessionStore):
    def __init__(
        self, ttl_s: int = 24 * 3600, *, now: Callable[[], datetime] | None = None
    ) -> None:
        """`now`: the clock that decides expiry (tests with a fixed date pass theirs; default:
        the real time)."""
        self._now = now or (lambda: datetime.now(UTC))
        self._data: dict[str, Session] = {}
        self._ttl = timedelta(seconds=ttl_s)
        self._lock = asyncio.Lock()

    def _expired(self, s: Session) -> bool:
        return self._now() - s.updated_at > self._ttl

    async def get(self, session_id: str) -> Session | None:
        async with self._lock:
            s = self._data.get(session_id)
            if s is None:
                return None
            if self._expired(s):
                del self._data[session_id]
                return None
            # return a copy so callers can't mutate stored state without save()
            return s.model_copy(deep=True)

    async def save(self, session: Session) -> None:
        async with self._lock:
            self._data[session.id] = session.model_copy(deep=True)

    async def delete(self, session_id: str) -> bool:
        async with self._lock:
            return self._data.pop(session_id, None) is not None

    async def list_for_user(self, user_id: str, limit: int = 50) -> list[SessionSummary]:
        async with self._lock:
            live = [s for s in self._data.values() if s.user_id == user_id and not self._expired(s)]
        live.sort(key=lambda s: s.updated_at, reverse=True)
        return [summarize(s) for s in live[:limit]]
