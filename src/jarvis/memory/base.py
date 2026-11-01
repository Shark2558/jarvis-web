# src/jarvis/memory/base.py
"""SessionStore: short-term memory persistence (Layer 7, 'Cache Layer').

One session == one conversation. The rolling window sent to the LLM is computed by
`jarvis.core.window`, not here — the store keeps the full transcript for audit/replay.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from jarvis.core.models import Session, SessionSummary, session_title

REASSIGN_BATCH = 200


class SessionNotFound(LookupError):
    pass


class SessionStore(ABC):
    @abstractmethod
    async def get(self, session_id: str) -> Session | None: ...

    @abstractmethod
    async def save(self, session: Session) -> None: ...

    @abstractmethod
    async def delete(self, session_id: str) -> bool: ...

    @abstractmethod
    async def list_for_user(self, user_id: str, limit: int = 50) -> list[SessionSummary]: ...

    async def get_or_raise(self, session_id: str) -> Session:
        s = await self.get(session_id)
        if s is None:
            raise SessionNotFound(session_id)
        return s

    async def reassign_user(self, old_user_id: str, new_user_id: str) -> int:
        """Move every session of `old_user_id` to `new_user_id`; returns how many moved.
        Each session is re-saved under the new owner (nothing is deleted first, so an
        interruption never loses a conversation). Idempotent: a second call moves 0."""
        moved = 0
        while True:
            batch = await self.list_for_user(old_user_id, limit=REASSIGN_BATCH)
            moved_now = 0
            for summary in batch:
                s = await self.get(summary.id)
                if s is None or s.user_id != old_user_id:
                    continue
                await self.save(s.model_copy(update={"user_id": new_user_id}))
                await self._unindex(old_user_id, s.id)
                moved_now += 1
            moved += moved_now
            if moved_now == 0 or len(batch) < REASSIGN_BATCH:
                return moved

    async def _unindex(self, user_id: str, session_id: str) -> None:
        """Hook for stores that keep a separate per-user index (Redis)."""
        return None

    async def ping(self) -> bool:
        return True

    async def close(self) -> None:
        return None


def summarize(s: Session) -> SessionSummary:
    return SessionSummary(
        id=s.id,
        user_id=s.user_id,
        created_at=s.created_at,
        updated_at=s.updated_at,
        turn_count=len(s.turns),
        total_cost_usd=s.total_cost_usd,
        title=session_title(s),
    )
