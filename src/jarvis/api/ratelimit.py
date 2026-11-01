# src/jarvis/api/ratelimit.py
"""Per-client token bucket for /v1, /auth and /connect. In-memory: correct for a single
instance, which is all we run until the Postgres/Redis slice (then move the bucket to Redis)."""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from fastapi import Request, Response
from fastapi.responses import JSONResponse

LIMITED_PREFIXES = ("/v1", "/auth", "/connect")
MAX_TRACKED_CLIENTS = 10_000


@dataclass
class _Bucket:
    tokens: float
    updated: float


class RateLimiter:
    def __init__(self, per_minute: int, now: Callable[[], float] = time.monotonic) -> None:
        self.capacity = float(per_minute)
        self.refill_per_s = per_minute / 60.0
        self._now = now
        self._buckets: dict[str, _Bucket] = {}

    def _evict_stalest(self) -> None:
        """Drop the least-recently-seen quarter of buckets; a flood must not OOM us, and
        clearing everything would reset legitimate clients' budgets."""
        victims = sorted(self._buckets.items(), key=lambda kv: kv[1].updated)
        for key, _ in victims[: max(1, len(victims) // 4)]:
            del self._buckets[key]

    def allow(self, key: str) -> tuple[bool, float]:
        """Returns (allowed, seconds_until_next_token)."""
        now = self._now()
        b = self._buckets.get(key)
        if b is None:
            if len(self._buckets) >= MAX_TRACKED_CLIENTS:
                self._evict_stalest()
            b = _Bucket(tokens=self.capacity, updated=now)
            self._buckets[key] = b
        b.tokens = min(self.capacity, b.tokens + (now - b.updated) * self.refill_per_s)
        b.updated = now
        if b.tokens >= 1.0:
            b.tokens -= 1.0
            return True, 0.0
        return False, (1.0 - b.tokens) / self.refill_per_s


def client_key(request: Request) -> str:
    # Behind Render (and most PaaS) the proxy *appends* the real client IP as the LAST hop of
    # X-Forwarded-For; earlier entries are attacker-controlled. Never key on the first entry.
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.rsplit(",", 1)[-1].strip()
    return request.client.host if request.client else "unknown"


def make_middleware(
    limiter: RateLimiter,
) -> Callable[[Request, Callable[[Request], Awaitable[Response]]], Awaitable[Response]]:
    async def middleware(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        if not request.url.path.startswith(LIMITED_PREFIXES):
            return await call_next(request)
        allowed, wait = limiter.allow(client_key(request))
        if not allowed:
            return JSONResponse(
                status_code=429,
                content={"error": "rate_limited", "detail": "too many requests"},
                headers={"Retry-After": str(max(1, int(wait + 0.999)))},
            )
        return await call_next(request)

    return middleware
