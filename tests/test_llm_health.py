# tests/test_llm_health.py -- R4 D-B1: the router reports the brain's health from what it already
# saw (the last real completion and the breaker). Reading it is free: no provider call, no tokens.
from __future__ import annotations

import pytest
from fallback_fakes import KW, TIERS, CloudProvider, FakeFallback

from jarvis.llm.base import LLMAuthError, LLMError, LLMTransientError, LLMUnreachable
from jarvis.llm.router import BrainHealth, ModelRouter, ModelTier


def router(cloud: CloudProvider, fb: FakeFallback | None = None) -> ModelRouter:
    return ModelRouter(cloud, TIERS, fallback=fb)


def test_a_new_router_has_seen_nothing_yet() -> None:
    assert router(CloudProvider()).health() == BrainHealth(state="unknown", on_laptop=False)


async def test_a_cloud_answer_is_ok() -> None:
    r = router(CloudProvider())
    await r.complete(tier=ModelTier.FAST, **KW)
    assert r.health().state == "ok"


@pytest.mark.parametrize(
    ("err", "state"),
    [
        (LLMAuthError("401"), "refused"),
        (LLMUnreachable("503"), "unreachable"),
        (LLMTransientError("429"), "busy"),
        (LLMError("odd"), "odd"),
    ],
)
async def test_the_last_failure_is_remembered(err: Exception, state: str) -> None:
    r = router(CloudProvider(err, err, err))
    with pytest.raises(LLMError):
        await r.complete(tier=ModelTier.FAST, **KW)
    assert r.health().state == state


async def test_a_laptop_answer_after_a_cloud_miss_says_so() -> None:
    r = router(CloudProvider(LLMUnreachable("503")), FakeFallback())
    await r.complete(tier=ModelTier.FAST, **KW)
    assert r.health() == BrainHealth(state="unreachable", on_laptop=True)


async def test_the_cloud_coming_back_clears_the_failure() -> None:
    r = router(CloudProvider(LLMAuthError("401")))
    with pytest.raises(LLMAuthError):
        await r.complete(tier=ModelTier.FAST, **KW)
    await r.complete(tier=ModelTier.FAST, **KW)
    assert r.health() == BrainHealth(state="ok", on_laptop=False)


async def test_a_failed_stream_is_remembered_and_a_good_one_clears_it() -> None:
    cloud = CloudProvider(LLMAuthError("401"))
    r = router(cloud)
    with pytest.raises(LLMAuthError):
        _ = [d async for d in r.stream(tier=ModelTier.FAST, **KW)]
    assert r.health().state == "refused"
    _ = [d async for d in r.stream(tier=ModelTier.FAST, **KW)]
    assert r.health().state == "ok"


async def test_reading_the_health_never_calls_the_provider() -> None:
    cloud = CloudProvider(LLMUnreachable("x"))
    r = router(cloud)
    for _ in range(3):
        r.health()
    assert cloud.models == []
