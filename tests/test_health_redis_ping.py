# tests/test_health_redis_ping.py -- the Redis probe's pinger builds its client lazily, with a named
# timeout, and can be closed.
from __future__ import annotations

import pytest

from jarvis.health import redis_ping


class FakeClient:
    def __init__(self) -> None:
        self.pings = 0
        self.closed = False

    async def ping(self) -> bool:
        self.pings += 1
        return True

    async def aclose(self) -> None:
        self.closed = True


@pytest.fixture
def made(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, dict]]:
    calls: list[tuple[str, dict]] = []
    client = FakeClient()

    def from_url(url: str, **kw: object) -> FakeClient:
        calls.append((url, dict(kw)))
        return client

    monkeypatch.setattr(redis_ping.aioredis, "from_url", from_url)
    return calls


async def test_no_client_is_built_until_the_first_ping(made: list) -> None:
    pinger = redis_ping.redis_pinger("redis://x")
    assert made == []
    await pinger()
    await pinger()
    assert len(made) == 1 and made[0][1]["socket_timeout"] == redis_ping.REDIS_TIMEOUT_S


async def test_close_closes_the_client_and_is_safe_before_use(made: list) -> None:
    pinger = redis_ping.redis_pinger("redis://x")
    await pinger.aclose()  # type: ignore[attr-defined]
    await pinger()
    await pinger.aclose()  # type: ignore[attr-defined]
    assert len(made) == 1
