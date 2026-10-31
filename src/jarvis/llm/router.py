# src/jarvis/llm/router.py
"""ModelRouter: callers ask for a *tier*, the router picks the model and handles degradation.

Graceful degradation (architecture tenet): a transient failure on STRONG falls back to
BALANCED, BALANCED to FAST. FAST failing is terminal — the caller decides what to do.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from enum import StrEnum

from jarvis.config import LLMBackend, Settings
from jarvis.llm.anthropic_provider import AnthropicProvider
from jarvis.llm.base import (
    ChatMessage,
    Completion,
    Effort,
    LLMProvider,
    LLMTransientError,
    ToolSpec,
)
from jarvis.llm.gemini_provider import GeminiProvider
from jarvis.llm.mock_provider import MockProvider
from jarvis.logging import get_logger

log = get_logger(__name__)


class ModelTier(StrEnum):
    FAST = "fast"  # classification, routing, extraction — Haiku-class
    BALANCED = "balanced"  # everyday conversation — Sonnet-class
    STRONG = "strong"  # planning, multi-step reasoning — Opus-class


_DEGRADE_TO: dict[ModelTier, ModelTier | None] = {
    ModelTier.STRONG: ModelTier.BALANCED,
    ModelTier.BALANCED: ModelTier.FAST,
    ModelTier.FAST: None,
}


class ModelRouter:
    def __init__(self, provider: LLMProvider, tiers: dict[ModelTier, str]) -> None:
        self.provider = provider
        self._tiers = tiers

    @classmethod
    def from_settings(cls, s: Settings, provider: LLMProvider | None = None) -> ModelRouter:
        if provider is None:
            provider = build_provider(s)
        return cls(provider, tiers_for(s, s.llm_backend))

    def resolve(self, tier: ModelTier) -> str:
        return self._tiers[tier]

    async def complete(
        self,
        *,
        tier: ModelTier,
        system: str,
        system_dynamic: str | None = None,
        messages: list[ChatMessage],
        max_tokens: int,
        effort: Effort | None = None,
        tools: list[ToolSpec] | None = None,
        allow_degrade: bool = True,
    ) -> Completion:
        current: ModelTier | None = tier
        while current is not None:
            model = self.resolve(current)
            try:
                return await self.provider.complete(
                    system=system,
                    system_dynamic=system_dynamic,
                    messages=messages,
                    model=model,
                    max_tokens=max_tokens,
                    effort=effort,
                    tools=tools,
                )
            except LLMTransientError as exc:
                nxt = _DEGRADE_TO[current] if allow_degrade else None
                if nxt is None:
                    raise
                log.warning(
                    "tier degraded after transient error",
                    extra={"from": current.value, "to": nxt.value, "error": str(exc)[:200]},
                )
                current = nxt
        raise AssertionError("unreachable")

    def stream(
        self,
        *,
        tier: ModelTier,
        system: str,
        system_dynamic: str | None = None,
        messages: list[ChatMessage],
        max_tokens: int,
        effort: Effort | None = None,
    ) -> AsyncIterator[str]:
        # No mid-stream degradation: once tokens are flowing to a TTS engine we cannot restart.
        return self.provider.stream(
            system=system,
            system_dynamic=system_dynamic,
            messages=messages,
            model=self.resolve(tier),
            max_tokens=max_tokens,
            effort=effort,
        )


def build_provider(s: Settings) -> LLMProvider:
    if s.llm_backend is LLMBackend.MOCK:
        return MockProvider()
    if s.llm_backend is LLMBackend.ANTHROPIC:
        if s.anthropic_api_key is None:
            raise RuntimeError("JARVIS_ANTHROPIC_API_KEY is not set")
        return AnthropicProvider(
            s.anthropic_api_key.get_secret_value(),
            timeout_s=s.llm_timeout_s,
            max_retries=s.llm_max_retries,
        )
    if s.llm_backend is LLMBackend.GEMINI:
        if s.gemini_api_key is None:
            raise RuntimeError("JARVIS_GEMINI_API_KEY is not set")
        return GeminiProvider(s.gemini_api_key.get_secret_value(), timeout_s=s.llm_timeout_s)
    if s.llm_backend is LLMBackend.OPENAI_COMPAT:
        from jarvis.llm.openai_compat_provider import OpenAICompatProvider

        if not s.openai_compat_configured:
            raise RuntimeError("JARVIS_OPENAI_COMPAT_BASE_URL / _MODEL_BALANCED are not set")
        assert s.openai_compat_base_url is not None
        return OpenAICompatProvider(
            s.openai_compat_base_url,
            api_key=s.openai_compat_api_key.get_secret_value() if s.openai_compat_api_key else None,
            timeout_s=s.llm_timeout_s,
        )
    raise ValueError(f"unknown llm backend: {s.llm_backend}")


def tiers_for(s: Settings, backend: LLMBackend) -> dict[ModelTier, str]:
    """Tier → model id map for one backend. Skills ask for tiers, never model ids."""
    if backend is LLMBackend.GEMINI:
        return {
            ModelTier.FAST: s.gemini_model_fast,
            ModelTier.BALANCED: s.gemini_model_balanced,
            ModelTier.STRONG: s.gemini_model_strong,
        }
    if backend is LLMBackend.OPENAI_COMPAT:
        balanced = s.openai_compat_model_balanced or "default"
        return {
            ModelTier.FAST: s.openai_compat_model_fast or balanced,
            ModelTier.BALANCED: balanced,
            ModelTier.STRONG: s.openai_compat_model_strong or balanced,
        }
    return {
        ModelTier.FAST: s.model_fast,
        ModelTier.BALANCED: s.model_balanced,
        ModelTier.STRONG: s.model_strong,
    }
