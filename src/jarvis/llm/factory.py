# src/jarvis/llm/factory.py
"""Providers built from the settings, in one place (R14 D9): both the legacy single-provider
router (`router.build_provider`) and the brain registry (`brains.BrainRegistry.from_settings`)
build Claude here, so `cache_history` reaches every Claude brain the app makes. Keys come only
from `SecretStr` settings and are never logged."""

from __future__ import annotations

from jarvis.config import Settings
from jarvis.llm.anthropic_provider import AnthropicProvider


def anthropic_provider(s: Settings) -> AnthropicProvider:
    if s.anthropic_api_key is None:
        raise RuntimeError("JARVIS_ANTHROPIC_API_KEY is not set")
    return AnthropicProvider(
        s.anthropic_api_key.get_secret_value(),
        timeout_s=s.llm_timeout_s,
        max_retries=s.llm_max_retries,
        cache_history=s.cache_history,
    )


__all__ = ["anthropic_provider"]
