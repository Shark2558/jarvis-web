# src/jarvis/health/redis_ping.py
"""The Redis ping the Redis probe uses: one PING on a small client of its own (no data touched).
Kept apart so tests and a Redis-less deployment never import the client."""

from __future__ import annotations

import redis.asyncio as aioredis

from jarvis.health.probes import Ping


def redis_pinger(url: str) -> Ping:
    client = aioredis.from_url(url, socket_connect_timeout=2, socket_timeout=2)

    async def ping() -> object:
        return await client.ping()

    return ping


__all__ = ["redis_pinger"]
