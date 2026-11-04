# tests/test_fallback_breaker.py -- R1 C (D12): after a cloud miss answered by the laptop, the next
# 2 minutes go straight to the laptop; then one cloud try. A laptop that fails closes the breaker.
from __future__ import annotations

from typing import Any

from fallback_fakes import KW, TIERS, CloudProvider, FakeFallback
from jarvis.llm.fallback import BREAKER_S, Breaker

from jarvis.llm.base import LLMUnreachable
from jarvis.llm.router import ModelRouter, ModelTier


class Clock:
    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t


def test_breaker_opens_for_two_minutes_then_closes() -> None:
    clock = Clock()
    b = Breaker(clock=clock)
    assert BREAKER_S == 120 and not b.is_open()
    b.trip()
    assert b.is_open()
    clock.t += 119
    assert b.is_open()
    clock.t += 2
    assert not b.is_open()


def test_breaker_reset_closes_it_at_once() -> None:
    b = Breaker(clock=Clock())
    b.trip()
    b.reset()
    assert not b.is_open()


class Flaky(CloudProvider):
    """Unreachable while `down`, answering otherwise."""

    def __init__(self) -> None:
        super().__init__()
        self.down = True

    async def complete(self, **kw: Any):  # type: ignore[override]
        if self.down:
            self.models.append(kw["model"])
            raise LLMUnreachable("503")
        return await super().complete(**kw)


def _router(cloud: Flaky, fb: FakeFallback, clock: Clock) -> ModelRouter:
    return ModelRouter(cloud, TIERS, fallback=fb, clock=clock)


async def test_after_a_miss_the_next_two_minutes_skip_the_cloud() -> None:
    clock, cloud, fb = Clock(), Flaky(), FakeFallback()
    r = _router(cloud, fb, clock)
    first = await r.complete(tier=ModelTier.BALANCED, **KW)
    assert first.offline and len(cloud.models) == 1
    clock.t += 60
    second = await r.complete(tier=ModelTier.BALANCED, **KW)
    assert second.offline and len(cloud.models) == 1  # the cloud was not asked again
    assert len(fb.calls) == 2


async def test_after_two_minutes_one_cloud_try_and_a_recovery_closes_the_breaker() -> None:
    clock, cloud, fb = Clock(), Flaky(), FakeFallback()
    r = _router(cloud, fb, clock)
    await r.complete(tier=ModelTier.BALANCED, **KW)
    clock.t += BREAKER_S + 1
    cloud.down = False
    back = await r.complete(tier=ModelTier.BALANCED, **KW)
    assert back.text == "from cloud" and not back.offline
    again = await r.complete(tier=ModelTier.BALANCED, **KW)
    assert again.text == "from cloud"  # not stuck on the laptop
    assert fb.cloud_oks == 2


async def test_a_failed_cloud_probe_trips_the_breaker_again() -> None:
    clock, cloud, fb = Clock(), Flaky(), FakeFallback()
    r = _router(cloud, fb, clock)
    await r.complete(tier=ModelTier.BALANCED, **KW)
    clock.t += BREAKER_S + 1
    probe = await r.complete(tier=ModelTier.BALANCED, **KW)
    assert probe.offline and len(cloud.models) == 2
    await r.complete(tier=ModelTier.BALANCED, **KW)
    assert len(cloud.models) == 2  # open again


async def test_a_laptop_that_fails_while_the_breaker_is_open_gives_the_cloud_a_chance() -> None:
    clock, cloud, fb = Clock(), Flaky(), FakeFallback()
    r = _router(cloud, fb, clock)
    await r.complete(tier=ModelTier.BALANCED, **KW)
    fb.fail = True
    cloud.down = False
    c = await r.complete(tier=ModelTier.BALANCED, **KW)
    assert c.text == "from cloud"


async def test_a_laptop_miss_does_not_open_the_breaker() -> None:
    clock, cloud, fb = Clock(), Flaky(), FakeFallback(fail=True)
    r = _router(cloud, fb, clock)
    for _ in range(2):
        try:
            await r.complete(tier=ModelTier.BALANCED, **KW)
        except LLMUnreachable:
            pass
    assert len(cloud.models) == 2  # every call still tried the cloud first


async def test_stream_while_open_goes_to_the_laptop_first() -> None:
    clock, cloud, fb = Clock(), Flaky(), FakeFallback()
    r = _router(cloud, fb, clock)
    await r.complete(tier=ModelTier.BALANCED, **KW)
    got = [d async for d in r.stream(tier=ModelTier.BALANCED, **KW)]
    assert got == ["lap ", "top "] and len(cloud.models) == 1
