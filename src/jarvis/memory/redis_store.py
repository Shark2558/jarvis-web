# src/jarvis/memory/redis_store.py
"""Redis-backed SessionStore. Sessions are JSON blobs with an idle TTL; a per-user sorted
set indexes sessions by last activity for listing.

Keys:
  jarvis:session:{id}        -> JSON (SETEX ttl)
  jarvis:user:{user_id}:sessions -> ZSET score=updated_at epoch, member=session id
"""

from __future__ import annotations

import json

import redis.asyncio as aioredis

from jarvis.core.models import Session, SessionSummary
from jarvis.logging import get_logger
from jarvis.memory.base import SessionStore, summarize

log = get_logger(__name__)


class RedisSessionStore(SessionStore):
    def __init__(self, url: str, ttl_s: int = 24 * 3600, prefix: str = "jarvis") -> None:
        self._r = aioredis.from_url(url, decode_responses=True)
        self._ttl = ttl_s
        self._p = prefix

    def _k_session(self, sid: str) -> str:
        return f"{self._p}:session:{sid}"

    def _k_user(self, uid: str) -> str:
        return f"{self._p}:user:{uid}:sessions"

    async def get(self, session_id: str) -> Session | None:
        raw = await self._r.get(self._k_session(session_id))
        if raw is None:
            return None
        try:
            return Session.model_validate_json(raw)
        except ValueError:
            log.error("corrupt session blob; dropping", extra={"session_id": session_id})
            await self._r.delete(self._k_session(session_id))
            return None

    async def save(self, session: Session) -> None:
        pipe = self._r.pipeline(transaction=True)
        pipe.set(self._k_session(session.id), session.model_dump_json(), ex=self._ttl)
        pipe.zadd(self._k_user(session.user_id), {session.id: session.updated_at.timestamp()})
        pipe.expire(self._k_user(session.user_id), self._ttl)
        await pipe.execute()

    async def _unindex(self, user_id: str, session_id: str) -> None:
        await self._r.zrem(self._k_user(user_id), session_id)

    async def delete(self, session_id: str) -> bool:
        s = await self.get(session_id)
        if s is None:
            return False
        pipe = self._r.pipeline(transaction=True)
        pipe.delete(self._k_session(session_id))
        pipe.zrem(self._k_user(s.user_id), session_id)
        await pipe.execute()
        return True

    async def list_for_user(self, user_id: str, limit: int = 50) -> list[SessionSummary]:
        ids: list[str] = await self._r.zrevrange(self._k_user(user_id), 0, limit - 1)
        out: list[SessionSummary] = []
        stale: list[str] = []
        for sid in ids:
            s = await self.get(sid)
            if s is None:
                stale.append(sid)  # expired blob, prune index lazily
                continue
            out.append(summarize(s))
        if stale:
            await self._r.zrem(self._k_user(user_id), *stale)
        return out

    async def ping(self) -> bool:
        try:
            return bool(await self._r.ping())
        except Exception as exc:  # noqa: BLE001
            log.error("redis ping failed", extra={"error": str(exc)})
            return False

    async def close(self) -> None:
        await self._r.aclose()


__all__ = ["RedisSessionStore", "json"]
