# tests/test_people_composer.py
"""The one brain call for a dossier goes through the router at a tier, never a model id."""

from __future__ import annotations

from jarvis.llm.mock_provider import MockProvider
from jarvis.llm.router import ModelRouter, ModelTier
from jarvis.people.composer import router_composer

TIERS = {t: f"mock-{t.value}" for t in ModelTier}


async def test_composer_asks_the_fast_tier_once_and_returns_text() -> None:
    provider = MockProvider()
    provider.script("A short dossier.")
    compose = router_composer(ModelRouter(provider, TIERS))

    text = await compose("system words", "prompt words")

    assert text == "A short dossier."
    assert len(provider.calls) == 1
    call = provider.calls[0]
    assert call.model == "mock-fast"
    assert call.tools is None  # no tools: untrusted findings can't trigger any
    assert call.messages[0].text() == "prompt words"
    assert call.system == "system words"
