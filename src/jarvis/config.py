# src/jarvis/config.py
"""Central configuration. Every tunable lives here and is overridable via env / .env.

Layer: cross-cutting (infrastructure).
"""

from __future__ import annotations

from enum import StrEnum
from functools import lru_cache

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class LLMBackend(StrEnum):
    ANTHROPIC = "anthropic"
    MOCK = "mock"  # deterministic provider for tests and offline dev


class SessionBackend(StrEnum):
    MEMORY = "memory"
    REDIS = "redis"


class AuthMode(StrEnum):
    TOKEN = "token"  # bearer token only (CLI, evals, dev)
    GOOGLE = "google"  # owner signs in with Google; bearer token still accepted for CLI


MIN_SESSION_SECRET_LEN = 32


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
    rate_limit_per_minute: int = Field(
        default=120, description="Per-client-IP request budget for /v1 and /auth (0 = off)"
    )

    # --- web sign-in (owner only) ---
    auth_mode: AuthMode = AuthMode.TOKEN
    google_client_id: str | None = None
    google_client_secret: SecretStr | None = None
    owner_emails: list[str] = Field(
        default_factory=list,
        description="Comma-separated. Only these Google accounts may sign in. Authorization "
        "boundary — Google merely authenticates.",
    )
    session_secret: SecretStr | None = Field(
        default=None, description="Signs the browser session cookie. ≥32 random chars."
    )
    public_base_url: str | None = Field(
        default=None, description="Where the app is reachable, e.g. https://jarvis.onrender.com"
    )
    session_cookie_max_age_s: int = 12 * 60 * 60

    @field_validator("owner_emails", mode="before")
    @classmethod
    def _split_emails(cls, v: object) -> list[str]:
        if isinstance(v, str):
            items = v.split(",")
        elif isinstance(v, list):
            items = [str(x) for x in v]
        else:
            return []
        return [e.strip().lower() for e in items if e.strip()]

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
        if self.auth_mode is AuthMode.GOOGLE:
            self._require_google_auth_config()

    def _require_google_auth_config(self) -> None:
        if not self.google_client_id or self.google_client_secret is None:
            raise RuntimeError(
                "JARVIS_GOOGLE_CLIENT_ID and JARVIS_GOOGLE_CLIENT_SECRET are required "
                "when JARVIS_AUTH_MODE=google"
            )
        if not self.public_base_url:
            raise RuntimeError("JARVIS_PUBLIC_BASE_URL is required when JARVIS_AUTH_MODE=google")
        if not self.owner_emails:
            raise RuntimeError("JARVIS_OWNER_EMAILS must list at least one owner account")
        secret = self.session_secret.get_secret_value() if self.session_secret else ""
        if len(secret) < MIN_SESSION_SECRET_LEN:
            raise RuntimeError(
                f"JARVIS_SESSION_SECRET must be at least {MIN_SESSION_SECRET_LEN} characters"
            )

    @property
    def cookie_secure(self) -> bool:
        return self.env != "dev"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
