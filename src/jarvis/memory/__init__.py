# src/jarvis/memory/__init__.py
from jarvis.config import SessionBackend, Settings
from jarvis.memory.base import SessionNotFound, SessionStore
from jarvis.memory.inmemory import InMemorySessionStore


def build_session_store(s: Settings) -> SessionStore:
    if s.session_backend is SessionBackend.MEMORY:
        return InMemorySessionStore(ttl_s=s.session_ttl_s)
    if s.session_backend is SessionBackend.REDIS:
        from jarvis.memory.redis_store import RedisSessionStore  # lazy: optional dependency

        return RedisSessionStore(s.redis_url, ttl_s=s.session_ttl_s)
    if s.session_backend is SessionBackend.FIRESTORE:
        from jarvis.storage import build_storage  # lazy: avoids an import cycle

        return build_storage(s).sessions
    raise ValueError(f"unknown session backend: {s.session_backend}")


__all__ = ["InMemorySessionStore", "SessionNotFound", "SessionStore", "build_session_store"]
