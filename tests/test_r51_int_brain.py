# tests/test_r51_int_brain.py -- R5.1 integrated fixes (int-sec LOWs): out of credit does not block
# the free laptop brain; `no_credit` clears on the next good call; friendly_llm_error trusts only
# typed errors (never vendor text).
from __future__ import annotations

import pytest
from fallback_fakes import KW, TIERS, CloudProvider, FakeFallback

from jarvis.api.app import friendly_llm_error
from jarvis.llm.base import LLMDeclined, LLMError, LLMOutOfCredit, LLMTransientError
from jarvis.llm.router import BrainHealth, ModelRouter, ModelTier


async def test_out_of_credit_uses_the_laptop_when_it_is_set_up() -> None:
    cloud = CloudProvider(LLMOutOfCredit())
    laptop = FakeFallback()
    r = ModelRouter(cloud, TIERS, fallback=laptop)  # type: ignore[arg-type]
    got = await r.complete(tier=ModelTier.STRONG, **KW)
    assert got.text == "from laptop" and got.offline is True
    assert r.health().state == "no_credit"  # the cloud is still out of credit


async def test_out_of_credit_with_no_laptop_still_raises_it() -> None:
    r = ModelRouter(CloudProvider(LLMOutOfCredit()), TIERS)
    with pytest.raises(LLMOutOfCredit):
        await r.complete(tier=ModelTier.STRONG, **KW)


async def test_out_of_credit_with_a_laptop_that_is_not_ready_raises_it() -> None:
    r = ModelRouter(
        CloudProvider(LLMOutOfCredit()),
        TIERS,
        fallback=FakeFallback(ready=False),  # type: ignore[arg-type]
    )
    with pytest.raises(LLMOutOfCredit):
        await r.complete(tier=ModelTier.STRONG, **KW)


async def test_out_of_credit_with_a_failing_laptop_raises_the_credit_error() -> None:
    r = ModelRouter(
        CloudProvider(LLMOutOfCredit()),
        TIERS,
        fallback=FakeFallback(fail=True),  # type: ignore[arg-type]
    )
    with pytest.raises(LLMOutOfCredit):
        await r.complete(tier=ModelTier.STRONG, **KW)


async def test_out_of_credit_streams_from_the_laptop_too() -> None:
    cloud = CloudProvider(LLMOutOfCredit())
    r = ModelRouter(cloud, TIERS, fallback=FakeFallback())  # type: ignore[arg-type]
    out = "".join([d async for d in r.stream(tier=ModelTier.STRONG, **KW)])
    assert out == "lap top "


async def test_no_credit_clears_on_the_next_good_call() -> None:
    r = ModelRouter(CloudProvider(LLMOutOfCredit()), TIERS)
    with pytest.raises(LLMOutOfCredit):
        await r.complete(tier=ModelTier.STRONG, **KW)
    assert r.health() == BrainHealth(state="no_credit", on_laptop=False)
    await r.complete(tier=ModelTier.STRONG, **KW)  # the owner topped up
    assert r.health().state == "ok"


@pytest.mark.parametrize(
    "words", ["credit balance is too low", "billing problem", "quota exceeded", "blocked", "x"]
)
def test_friendly_error_never_reads_vendor_text(words: str) -> None:
    line = friendly_llm_error(LLMError(words))
    assert line == "The AI service could not answer. Please try again."
    assert words not in line


def test_friendly_error_for_typed_errors() -> None:
    assert "no credit" in friendly_llm_error(LLMOutOfCredit())
    assert "busy" in friendly_llm_error(LLMTransientError("quota"))
    assert "declined" in friendly_llm_error(LLMDeclined())
