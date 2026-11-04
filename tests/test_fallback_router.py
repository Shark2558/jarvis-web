# tests/test_fallback_router.py -- R1 C (D12): the ModelRouter hands a turn to the fallback brain
# only when the cloud is UNREACHABLE (connection error, timeout, 5xx); 429 / auth / 4xx never do.
# No tier degradation on unreachable (every tier is down); streams switch only before the first
# delta.
from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
from fallback_fakes import KW, MSGS, TIERS, CloudProvider, FakeFallback

from jarvis.llm.base import (
    LLMAuthError,
    LLMError,
    LLMTransientError,
    LLMUnreachable,
    StreamUsage,
    ToolSpec,
)
from jarvis.llm.fallback import FallbackFailed
from jarvis.llm.router import ModelRouter, ModelTier


def _router(cloud: CloudProvider, fb: FakeFallback | None) -> ModelRouter:
    return ModelRouter(cloud, TIERS, fallback=fb)


@pytest.mark.parametrize("err", [LLMUnreachable("503"), LLMUnreachable("timeout")])
async def test_unreachable_goes_straight_to_the_laptop_without_degrading(err: Exception) -> None:
    cloud, fb = CloudProvider(err), FakeFallback()
    c = await _router(cloud, fb).complete(tier=ModelTier.STRONG, **KW)
    assert c.offline is True and c.text == "from laptop"
    assert cloud.models == ["s"]  # one cloud try, no BALANCED / FAST retries
    assert fb.calls[0]["tier"] is ModelTier.STRONG


@pytest.mark.parametrize(
    "err", [LLMTransientError("429"), LLMAuthError("401"), LLMError("400 bad request")]
)
async def test_other_errors_never_fall_back(err: Exception) -> None:
    cloud, fb = CloudProvider(err, err, err), FakeFallback()
    with pytest.raises(LLMError):
        await _router(cloud, fb).complete(tier=ModelTier.STRONG, **KW)
    assert fb.calls == []
    if isinstance(err, LLMTransientError):  # 429 still degrades the tier, as before R1
        assert cloud.models == ["s", "b", "f"]
    else:
        assert cloud.models == ["s"]


async def test_429_degrades_to_a_cheaper_tier_and_stays_in_the_cloud() -> None:
    cloud, fb = CloudProvider(LLMTransientError("429")), FakeFallback()
    c = await _router(cloud, fb).complete(tier=ModelTier.STRONG, **KW)
    assert c.text == "from cloud" and not c.offline and fb.calls == []


async def test_without_a_fallback_unreachable_degrades_like_before() -> None:
    cloud = CloudProvider(LLMUnreachable("x"), LLMUnreachable("y"), LLMUnreachable("z"))
    with pytest.raises(LLMUnreachable):
        await _router(cloud, None).complete(tier=ModelTier.STRONG, **KW)
    assert cloud.models == ["s", "b", "f"]


async def test_a_fallback_that_is_not_ready_leaves_the_original_behaviour() -> None:
    cloud, fb = CloudProvider(LLMUnreachable("x")), FakeFallback(ready=False)
    c = await _router(cloud, fb).complete(tier=ModelTier.STRONG, **KW)
    assert c.text == "from cloud" and fb.calls == []  # degraded to BALANCED, then answered
    assert cloud.models == ["s", "b"]


async def test_laptop_down_too_raises_a_friendly_unreachable_error() -> None:
    cloud, fb = CloudProvider(LLMUnreachable("503 secret vendor text")), FakeFallback(fail=True)
    with pytest.raises(FallbackFailed) as ei:
        await _router(cloud, fb).complete(tier=ModelTier.BALANCED, **KW)
    assert isinstance(ei.value, LLMUnreachable)  # callers that catch the family still do
    assert "your laptop didn't answer" in str(ei.value)
    assert "secret" not in str(ei.value)
    assert isinstance(ei.value.__cause__, LLMUnreachable)  # the original cloud error is kept


async def test_tools_and_prompt_pieces_are_passed_to_the_fallback_unfiltered() -> None:
    cloud, fb = CloudProvider(LLMUnreachable("x")), FakeFallback()
    tool = ToolSpec(name="calendar_list_events", description="d", input_schema={})
    await _router(cloud, fb).complete(tier=ModelTier.FAST, system_dynamic="dyn", tools=[tool], **KW)
    got = fb.calls[0]
    assert got["tools"] == [tool] and got["system"] == "sys" and got["system_dynamic"] == "dyn"
    assert got["max_tokens"] == 50 and got["messages"] == MSGS


async def test_cloud_success_tells_the_fallback_the_cloud_is_back() -> None:
    cloud, fb = CloudProvider(), FakeFallback()
    await _router(cloud, fb).complete(tier=ModelTier.FAST, **KW)
    assert fb.cloud_oks == 1


# ---- streams ---------------------------------------------------------------------------------


async def _collect(it: AsyncIterator[str]) -> list[str]:
    return [d async for d in it]


async def test_stream_failing_before_the_first_delta_is_taken_over_by_the_laptop() -> None:
    cloud, fb = CloudProvider(LLMUnreachable("503")), FakeFallback()
    got = await _collect(_router(cloud, fb).stream(tier=ModelTier.BALANCED, **KW))
    assert got == ["lap ", "top "]
    assert len(fb.streams) == 1


async def test_stream_failing_after_a_delta_is_never_switched_mid_stream() -> None:
    cloud = CloudProvider(LLMUnreachable("dropped"))
    cloud.stream_fail_after = 1
    fb = FakeFallback()
    got: list[str] = []
    with pytest.raises(LLMUnreachable):
        async for d in _router(cloud, fb).stream(tier=ModelTier.BALANCED, **KW):
            got.append(d)
    assert got == ["a "] and fb.streams == []


async def test_stream_429_does_not_fall_back() -> None:
    cloud, fb = CloudProvider(LLMTransientError("429")), FakeFallback()
    with pytest.raises(LLMTransientError):
        await _collect(_router(cloud, fb).stream(tier=ModelTier.BALANCED, **KW))
    assert fb.streams == []


async def test_stream_laptop_down_too_is_the_friendly_error() -> None:
    cloud, fb = CloudProvider(LLMUnreachable("503")), FakeFallback(fail=True)
    with pytest.raises(FallbackFailed):
        await _collect(_router(cloud, fb).stream(tier=ModelTier.BALANCED, **KW))


async def test_stream_without_a_fallback_is_unchanged_and_passes_usage_through() -> None:
    cloud = CloudProvider()
    usage = StreamUsage()
    got = await _collect(_router(cloud, None).stream(tier=ModelTier.FAST, usage=usage, **KW))
    assert got == ["a ", "b "]


async def test_stream_success_tells_the_fallback_the_cloud_is_back() -> None:
    cloud, fb = CloudProvider(), FakeFallback()
    await _collect(_router(cloud, fb).stream(tier=ModelTier.FAST, **KW))
    assert fb.cloud_oks == 1


async def test_a_laptop_that_refuses_the_key_gives_the_key_message() -> None:
    from jarvis.llm.fallback import FALLBACK_REFUSED_TEXT

    cloud = CloudProvider(LLMUnreachable("503"))
    fb = FakeFallback(error=LLMAuthError("401"))
    with pytest.raises(FallbackFailed) as ei:
        await _router(cloud, fb).complete(tier=ModelTier.BALANCED, **KW)
    assert str(ei.value) == FALLBACK_REFUSED_TEXT
    assert "paste the new key" in str(ei.value) and "Offline mode" in str(ei.value)
