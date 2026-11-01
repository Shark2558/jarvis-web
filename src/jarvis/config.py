# src/jarvis/config.py
"""Central configuration. Every tunable lives here and is overridable via env / .env.

Layer: cross-cutting (infrastructure).
"""

from __future__ import annotations

from enum import StrEnum
from functools import lru_cache
from typing import Annotated

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class LLMBackend(StrEnum):
    ANTHROPIC = "anthropic"
    GEMINI = "gemini"  # free-tier-capable alternative brain (chat only; see docs/plans slice 3)
    OPENAI_COMPAT = "custom"  # one OpenAI-compatible slot: Groq / OpenRouter / Ollama / LM Studio
    MOCK = "mock"  # deterministic provider for tests and offline dev


class SessionBackend(StrEnum):
    MEMORY = "memory"  # dev/tests: everything in-process
    REDIS = "redis"  # docker-compose: sessions in Redis, approvals/audit in-process
    FIRESTORE = "firestore"  # Cloud Run: sessions, approvals and audit persist (slice 5)


class AuthMode(StrEnum):
    TOKEN = "token"  # bearer token only (CLI, evals, dev)
    GOOGLE = "google"  # owner signs in with Google; bearer token still accepted for CLI


MIN_SESSION_SECRET_LEN = 32


def _is_private_host(host: str) -> bool:
    """Loopback, RFC1918/ULA, link-local, or a bare/local name — plain http is tolerable there."""
    import ipaddress

    h = host.lower()
    if h in ("localhost", "host.docker.internal") or h.endswith((".local", ".internal", ".ts.net")):
        return True
    try:
        ip = ipaddress.ip_address(h)
    except ValueError:
        return "." not in h  # single-label hostname on a LAN / compose network
    return ip.is_private or ip.is_loopback or ip.is_link_local


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
    owner_emails: Annotated[list[str], NoDecode] = Field(
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
            stripped = v.strip()
            if stripped.startswith("["):  # tolerate the JSON form too
                import json

                items = [str(x) for x in json.loads(stripped)]
            else:
                items = stripped.split(",")
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

    # --- Gemini (optional free brain). Free-tier prompts are used by Google to improve its
    # products, so this backend is chat-only (no tools) and the console shows a warning.
    gemini_api_key: SecretStr | None = None
    gemini_model_fast: str = "gemini-3.5-flash-lite"
    gemini_model_balanced: str = "gemini-3.8-flash"
    gemini_model_strong: str = "gemini-3.8-flash"  # no free "strong" model exists
    gemini_paid_tier: bool = Field(
        default=False,
        description="True only if the key's project has billing (Google then does NOT train on it)",
    )
    # --- OpenAI-compatible slot (optional): Groq, OpenRouter, Ollama, LM Studio, vLLM, …
    # One slot; it appears in the console as its own brain ("custom") next to Claude/Gemini.
    openai_compat_base_url: str | None = Field(
        default=None, description="e.g. https://api.groq.com/openai/v1 or http://host:11434/v1"
    )
    openai_compat_api_key: SecretStr | None = Field(
        default=None, description="Optional — local servers (Ollama, LM Studio) have none"
    )
    openai_compat_label: str = Field(default="Custom", description="Name shown in the console")
    openai_compat_model_balanced: str | None = Field(
        default=None, description="Model id for everyday chat (required when the slot is used)"
    )
    openai_compat_model_fast: str | None = None  # default: balanced
    openai_compat_model_strong: str | None = None  # default: balanced
    openai_compat_trains_on_content: bool = Field(
        default=True,
        description="Private by default: assume the vendor may train on prompts unless the owner "
        "knows otherwise. A training brain never receives tools / private data.",
    )
    effort: str | None = Field(
        default="low",
        description="Reasoning effort for chat turns: low | medium | high | None (model default). "
        "Low keeps latency and cost down for conversational turns; the planner (Phase 2) "
        "raises it per task.",
    )
    llm_timeout_s: float = Field(
        default=20.0,
        description="Per-request LLM timeout. Short on purpose: a stuck model should cost seconds "
        "before degrading to the next tier, not a minute (live incident 2026-11-01).",
    )
    llm_max_retries: int = 2

    # --- session memory (short-term, rolling window) ---
    session_backend: SessionBackend = SessionBackend.MEMORY
    redis_url: str = "redis://localhost:6379/0"
    session_ttl_s: int = Field(
        default=60 * 60 * 24, description="Idle TTL for a session (memory/redis backends only)"
    )
    firestore_project: str | None = Field(
        default=None, description="GCP project; default: the one the credentials belong to"
    )
    firestore_database: str = Field(default="(default)", description="Firestore database id")
    firestore_prefix: str = Field(
        default="jarvis_", pattern=r"^[a-z][a-z0-9_]{0,30}$", description="Collection prefix"
    )
    session_max_turns: int = Field(default=40, description="Rolling window: max turns kept")
    session_max_chars: int = Field(
        default=48_000,
        description="Rolling window: approx char budget sent to the LLM (~12k tokens)",
    )

    # --- tools ---
    tools_enabled: bool = True
    tool_max_rounds: int = Field(default=6, description="Max model↔tool rounds per turn")
    # --- Google Calendar + Gmail tools (slice 6). Need auth_mode=google (same OAuth client as
    # sign-in, more scopes, linked per owner from the console's Integrations panel).
    google_tools_enabled: bool = Field(
        default=True, description="Register the Google tools when auth_mode=google"
    )
    token_key: SecretStr | None = Field(
        default=None,
        description="Base64 of 32 random bytes: AES-256-GCM key for the Google token vault "
        "(Secret Manager `jarvis-token-key`). Required outside dev when Google tools are on.",
    )

    # --- persona ---
    user_honorific: str = Field(default="Sir", description="How JARVIS addresses the user")
    user_timezone: str = "Asia/Kolkata"

    def require_prod_invariants(self) -> None:
        """Fail fast on misconfiguration that is acceptable in dev but not beyond it."""
        if self.env != "dev" and self.api_token is None:
            raise RuntimeError("JARVIS_API_TOKEN must be set when JARVIS_ENV != dev")
        if self.llm_backend is LLMBackend.ANTHROPIC and self.anthropic_api_key is None:
            raise RuntimeError("JARVIS_ANTHROPIC_API_KEY is required for the anthropic backend")
        if self.llm_backend is LLMBackend.GEMINI and self.gemini_api_key is None:
            raise RuntimeError("JARVIS_GEMINI_API_KEY is required for the gemini backend")
        if self.llm_backend is LLMBackend.OPENAI_COMPAT and not self.openai_compat_configured:
            raise RuntimeError(
                "JARVIS_OPENAI_COMPAT_BASE_URL and JARVIS_OPENAI_COMPAT_MODEL_BALANCED are "
                "required for the openai_compat backend"
            )
        if self.auth_mode is AuthMode.GOOGLE:
            self._require_google_auth_config()
            if self.google_tools_enabled and self.token_key is None:
                raise RuntimeError(
                    "JARVIS_TOKEN_KEY is required when Google tools are enabled "
                    "(set JARVIS_GOOGLE_TOOLS_ENABLED=false to run without them)"
                )
        if self.token_key is not None:
            self.token_key_bytes()  # malformed key fails at start-up, not at first connect

    def token_key_bytes(self) -> bytes | None:
        if self.token_key is None:
            return None
        from jarvis.integrations.vault import VaultError, decode_key

        try:
            return decode_key(self.token_key.get_secret_value())
        except VaultError as exc:
            raise RuntimeError(f"JARVIS_TOKEN_KEY is invalid: {exc}") from exc

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

    @field_validator("openai_compat_base_url")
    @classmethod
    def _check_base_url(cls, v: str | None) -> str | None:
        """https required except for loopback / private hosts: a bearer key must never travel
        in cleartext to a remote server."""
        if v is None or not v.strip():
            return None
        from urllib.parse import urlsplit

        u = urlsplit(v.strip())
        if u.scheme not in ("http", "https") or not u.hostname:
            raise ValueError("JARVIS_OPENAI_COMPAT_BASE_URL must be an http(s) URL with a host")
        if u.scheme == "http" and not _is_private_host(u.hostname):
            raise ValueError(
                "JARVIS_OPENAI_COMPAT_BASE_URL uses http:// to a non-local host; use https:// "
                "(an API key would be sent in cleartext)"
            )
        return v.strip().rstrip("/")

    @property
    def openai_compat_configured(self) -> bool:
        return bool(self.openai_compat_base_url and self.openai_compat_model_balanced)

    @property
    def llm_trains_on_content(self) -> bool:
        """True when the DEFAULT brain's vendor may use prompts to improve its products."""
        if self.llm_backend is LLMBackend.GEMINI:
            return not self.gemini_paid_tier
        if self.llm_backend is LLMBackend.OPENAI_COMPAT:
            return self.openai_compat_trains_on_content
        return False

    @property
    def cookie_secure(self) -> bool:
        return self.env != "dev"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
