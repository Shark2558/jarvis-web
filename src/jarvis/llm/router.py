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
        if s.llm_backend is LLMBackend.GEMINI:
            tiers = {
                ModelTier.FAST: s.gemini_model_fast,
                ModelTier.BALANCED: s.gemini_model_balanced,
                ModelTier.STRONG: s.gemini_model_strong,
            }
        else:
            tiers = {
                ModelTier.FAST: s.model_fast,
                ModelTier.BALANCED: s.model_balanced,
                ModelTier.STRONG: s.model_strong,
            }
        return cls(provider, tiers)

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
    raise ValueError(f"unknown llm backend: {s.llm_backend}")
