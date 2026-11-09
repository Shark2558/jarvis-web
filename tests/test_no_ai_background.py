# tests/test_no_ai_background.py
"""Background model users skip quietly while the AI is switched off (R4 py-M3): no provider call,
no exception, no cost."""

from __future__ import annotations

from jarvis.brief.summarize import Prepared as BriefPrepared
from jarvis.brief.summarize import Summarizer
from jarvis.llm.brains import BrainRegistry, BrainSpec
from jarvis.llm.mock_provider import MockProvider
from jarvis.llm.router import ModelTier
from jarvis.recall.extract import Extractor
from jarvis.recall.extract import Prepared as LearnPrepared

TIERS = {t: f"mock-{t.value}" for t in ModelTier}


def blocked_registry() -> tuple[BrainRegistry, MockProvider]:
    provider = MockProvider()
    brains = BrainRegistry(
        [BrainSpec(id="mock", label="Mock", provider=provider, tiers=TIERS)], default_id="mock"
    )
    brains.router_for("mock").bind_blocked(lambda: True)
    return brains, provider


async def test_the_brief_summary_is_skipped_when_the_ai_is_off() -> None:
    brains, provider = blocked_registry()

    block = await Summarizer(brains).run(
        BriefPrepared(brains.get("mock"), TIERS[ModelTier.FAST], "x")
    )

    assert block.lines == () and block.cost_usd == 0 and provider.calls == []


async def test_learning_is_skipped_when_the_ai_is_off() -> None:
    brains, provider = blocked_registry()

    out = await Extractor(brains).run(LearnPrepared(brains.get("mock"), TIERS[ModelTier.FAST], "x"))

    assert out.extraction is None and out.cost_usd == 0 and provider.calls == []
