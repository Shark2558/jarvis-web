# src/jarvis/memory/base.py
"""SessionStore: short-term memory persistence (Layer 7, 'Cache Layer').

One session == one conversation. The rolling window sent to the LLM is computed by
`jarvis.core.window`, not here — the store keeps the full transcript for audit/replay.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from jarvis.core.models import Session, SessionSummary


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
    )
