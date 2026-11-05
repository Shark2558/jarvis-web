# src/jarvis/health/redis_ping.py
"""The Redis ping the Redis probe uses: one PING on a small client of its own (no data touched).
The client is built on the first ping, not at wiring time, and `aclose()` releases it. Kept apart
so tests and a Redis-less deployment never import the client."""

from __future__ import annotations

import redis.asyncio as aioredis

REDIS_TIMEOUT_S = 2.0


class RedisPinger:
    def __init__(self, url: str) -> None:
        self._url = url
        self._client: aioredis.Redis | None = None

    async def __call__(self) -> object:
        if self._client is None:
            self._client = aioredis.from_url(
                self._url, socket_connect_timeout=REDIS_TIMEOUT_S, socket_timeout=REDIS_TIMEOUT_S
            )
        return await self._client.ping()

    async def aclose(self) -> None:
        client, self._client = self._client, None
        if client is not None:
            await client.aclose()


def redis_pinger(url: str) -> RedisPinger:
    return RedisPinger(url)


__all__ = ["REDIS_TIMEOUT_S", "RedisPinger", "redis_pinger"]
