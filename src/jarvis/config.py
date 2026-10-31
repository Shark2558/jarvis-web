# src/jarvis/config.py
"""Central configuration. Every tunable lives here and is overridable via env / .env.

Layer: cross-cutting (infrastructure).
"""

from __future__ import annotations

from enum import StrEnum
from functools import lru_cache

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class LLMBackend(StrEnum):
    ANTHROPIC = "anthropic"
    MOCK = "mock"  # deterministic provider for tests and offline dev


class SessionBackend(StrEnum):
    MEMORY = "memory"
    REDIS = "redis"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="JARVIS_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- identity / environment ---
    env: str = Field(default="dev", description="dev | staging | prod")
    log_level: str = "INFO"
    log_json: bool = Field(default=False, description="Emit JSON logs (recommended in prod)")

    # --- API ---
    api_token: SecretStr | None = Field(
        default=None,
        description="Bearer token required on every /v1 request. Mandatory when env != dev.",
    )
    max_input_chars: int = Field(default=16_000, description="Hard cap on a single user turn")

    # --- LLM ---
    llm_backend: LLMBackend = LLMBackend.ANTHROPIC
    anthropic_api_key: SecretStr | None = None
    # Model tiers. Skills ask for a *tier*, never a model id — that is what keeps the core
    # model-agnostic. Ids below are the Claude API ids as of Oct 2026.
    model_fast: str = Field(default="claude-haiku-5-5", description="Classification, routing")
    model_balanced: str = Field(default="claude-sonnet-5-5", description="Everyday chat")
    model_strong: str = Field(default="claude-opus-5-5", description="Planning, hard reasoning")
    default_tier: str = Field(default="balanced", description="fast | balanced | strong")
    max_output_tokens: int = 1024
    effort: str | None = Field(
        default="low",
        description="Reasoning effort for chat turns: low | medium | high | None (model default). "
        "Low keeps latency and cost down for conversational turns; the planner (Phase 2) "
        "raises it per task.",
    )
    llm_timeout_s: float = 60.0
    llm_max_retries: int = 2

    # --- session memory (short-term, rolling window) ---
    session_backend: SessionBackend = SessionBackend.MEMORY
    redis_url: str = "redis://localhost:6379/0"
    session_ttl_s: int = Field(default=60 * 60 * 24, description="Idle TTL for a session")
    session_max_turns: int = Field(default=40, description="Rolling window: max turns kept")
    session_max_chars: int = Field(
        default=48_000,
        description="Rolling window: approx char budget sent to the LLM (~12k tokens)",
    )

    # --- tools ---
    tools_enabled: bool = True
    tool_max_rounds: int = Field(default=6, description="Max model↔tool rounds per turn")

    # --- persona ---
    user_honorific: str = Field(default="Sir", description="How JARVIS addresses the user")
    user_timezone: str = "Asia/Kolkata"

    def require_prod_invariants(self) -> None:
        """Fail fast on misconfiguration that is acceptable in dev but not beyond it."""
        if self.env != "dev" and self.api_token is None:
            raise RuntimeError("JARVIS_API_TOKEN must be set when JARVIS_ENV != dev")
        if self.llm_backend is LLMBackend.ANTHROPIC and self.anthropic_api_key is None:
            raise RuntimeError("JARVIS_ANTHROPIC_API_KEY is required for the anthropic backend")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
