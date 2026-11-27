# src/jarvis/config_calls.py
"""R18's settings (docs/plans/r18-calls.md; BUILD-BRIEF.md "Decisions fixed"), a base class of
`jarvis.config.Settings`: every key is read like any other (`JARVIS_<NAME>`, .env) and reached as
`settings.<name>`. They live in this module so config.py stays under its size guard (the 800-line
soft ceiling). Pydantic and the standard library only.

Speech keys are optional and secret (`SecretStr`, never logged): without one, that option is not
offered. Sarvam is paid and needs its key AND `sarvam_enabled` (the owner's YES). The caps and the
retention are the deployment's defaults for the owner's call settings (`jarvis.calls.settings`).
"""

from __future__ import annotations

from pydantic import BaseModel, Field, SecretStr


class CallsConfig(BaseModel):
    # R18 calls' speech options (docs/plans/r18-calls.md 5.1, 6; read 25 Nov 2026). Azure's free
    # tier F0 stops at its allowance and CANNOT bill: ₹0 is its true price, not a guess. Sarvam is
    # paid and off unless the owner turns it on. Bhashini publishes no price for this use, so it has
    # none (None): a price JARVIS does not know is never counted as ₹0 (`jarvis.calls.prices`).
    voice_price_azure_f0_inr_per_hour: float = Field(
        default=0.0, ge=0, le=0, description="₹ an hour of hearing, Azure F0: it cannot bill"
    )
    voice_price_azure_f0_inr_per_m_chars: float = Field(
        default=0.0, ge=0, le=0, description="₹ per 1 M voice characters, Azure F0: it cannot bill"
    )
    voice_azure_f0_stt_free_seconds: int = Field(
        default=18_000, ge=0, le=18_000, description="Azure F0 hearing a month (5 hours)"
    )
    voice_azure_f0_tts_free_chars: int = Field(
        default=500_000, ge=0, le=500_000, description="Azure F0 voice characters a month"
    )
    voice_price_sarvam_inr_per_hour: float = Field(
        default=30.0, gt=0, le=10_000, description="₹ an hour of hearing, Sarvam (paid)"
    )
    voice_price_sarvam_inr_per_10k_chars: float = Field(
        default=30.0, gt=0, le=10_000, description="₹ per 10,000 characters of voice, Sarvam (paid)"
    )
    voice_price_bhashini_inr_per_minute: float | None = Field(
        default=None, ge=0, le=1_000, description="₹ a minute, Bhashini; unset: unknown, never ₹0"
    )

    # --- R18 calls from the laptop (docs/plans/r18-calls.md). Speech keys are optional: without
    # one that option is simply not offered. Sarvam needs its key AND `sarvam_enabled`.
    calls_enabled: bool = Field(default=True, description="R18 calls (each call after his tap)")
    azure_speech_key: SecretStr | None = Field(
        default=None, description="Azure Speech free tier F0 key (Secret Manager); unset: no Azure"
    )
    azure_speech_region: str = Field(
        default="centralindia", pattern=r"^[a-z0-9]{3,30}$", description="The F0 resource's region"
    )
    sarvam_api_key: SecretStr | None = Field(default=None, description="Sarvam (paid) API key")
    sarvam_enabled: bool = Field(
        default=False, description="Paid Sarvam speech: only with the owner's YES (and the key)"
    )
    bhashini_user_id: str | None = Field(default=None, max_length=80, description="Bhashini ULCA")
    bhashini_api_key: SecretStr | None = Field(default=None, description="Bhashini ULCA API key")
    calls_retention_days: int = Field(
        default=30, ge=1, le=30, description="Days a call's audio, transcript and summary are kept"
    )
    calls_month_cap_inr: int = Field(
        default=200, ge=0, le=3_000, description="₹ a month for calls (the owner may lower it)"
    )
    calls_call_cap_inr: int = Field(default=20, ge=1, le=200, description="₹ one call at most")
    calls_max_minutes: int = Field(default=6, ge=1, le=30, description="Minutes one call at most")
