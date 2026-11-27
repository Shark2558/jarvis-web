# src/jarvis/config_voice.py
"""R5.2's settings (docs/plans/r5-2-voice.md 3.1, 3.3; I0 seams), a base class of
`jarvis.config.Settings` like R18's `config_calls.CallsConfig`: every key is read like any other
(`JARVIS_<NAME>`, .env) and reached as `settings.<name>`; config.py stays under its size guard.
Pydantic and the standard library only.

The laptop speech kit is reached only through the owner's Tailscale **https** name (row 392's rule:
http refused), with the kit's gate key as a `SecretStr` (never logged). The address must have the
offline brain's shape (`https://<machine>.<tailnet>.ts.net`, a Funnel port, no other path); that
every address the name resolves to is public is checked again before each call by the kit client
(`jarvis.offline.config.check_url` and `PinnedTransport`, V2). Without both keys the kit is not
offered and the console uses Google, then the browser, as today.
"""

from __future__ import annotations

import re
from urllib.parse import urlsplit

from pydantic import BaseModel, Field, SecretStr, field_validator

FUNNEL_PORTS = frozenset({443, 8443, 10000})  # = jarvis.offline.config.ALLOWED_PORTS
KIT_KEY_MIN_CHARS = 32  # = jarvis.localspeech.protocol.KEY_MIN_CHARS
_LABEL = r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?"
_HOST = re.compile(rf"^{_LABEL}\.{_LABEL}\.ts\.net$")
_SHAPE = (
    "JARVIS_LOCAL_SPEECH_URL must be the laptop's Tailscale Funnel address, like "
    "https://my-laptop.tail1234.ts.net:8443 (https, no IP address, no extra path)"
)


def kit_origin(raw: str) -> str:
    """`https://<machine>.<tailnet>.ts.net[:port]` (lower case, no path), or ValueError."""
    text = raw.strip()
    try:
        u = urlsplit(text)
        port = u.port
    except ValueError:
        raise ValueError(_SHAPE) from None
    host = (u.hostname or "").lower()
    if u.scheme.lower() != "https" or not _HOST.fullmatch(host) or not text.isascii():
        raise ValueError(_SHAPE)
    if u.username or u.password or u.query or u.fragment or u.path.rstrip("/") not in ("", "/v1"):
        raise ValueError(_SHAPE)
    if port is not None and port not in FUNNEL_PORTS:
        raise ValueError("Tailscale Funnel only uses port 443, 8443 or 10000")
    return f"https://{host}" + ("" if port in (None, 443) else f":{port}")


class LocalSpeechConfig(BaseModel):
    # --- R5.2 the laptop speech kit (row 383) and the voice profile (rows 81, 83, 84)
    local_speech_url: str | None = Field(
        default=None, description="The laptop speech kit's Tailscale https address; unset: no kit"
    )
    local_speech_key: SecretStr | None = Field(
        default=None, description="The kit's gate key (Secret Manager); unset: no kit"
    )
    local_speech_enabled: bool = Field(
        default=True, description="Off: the kit is never called, even when it is set up"
    )
    local_speech_timeout_s: float = Field(
        default=8.0, ge=1, le=60, description="Seconds one listen or speak may take on the kit"
    )
    local_speech_health_s: int = Field(
        default=30, ge=5, le=300, description="Seconds the kit's health is trusted before a recheck"
    )
    voice_profile_enabled: bool = Field(
        default=True, description="R5.2 the voice session, wake word and laptop speech routes"
    )
    voice_session_compare_minutes: int = Field(
        default=20, ge=0, le=30, description="Google minutes the session's comparison may use"
    )

    @field_validator("local_speech_url")
    @classmethod
    def _url(cls, v: str | None) -> str | None:
        if v is None or not v.strip():
            return None
        return kit_origin(v)

    @field_validator("local_speech_key")
    @classmethod
    def _key(cls, v: SecretStr | None) -> SecretStr | None:
        if v is not None and len(v.get_secret_value()) < KIT_KEY_MIN_CHARS:
            raise ValueError(f"the kit's key needs at least {KIT_KEY_MIN_CHARS} characters")
        return v

    @property
    def local_speech_configured(self) -> bool:
        return bool(self.local_speech_enabled and self.local_speech_url and self.local_speech_key)


__all__ = ["FUNNEL_PORTS", "KIT_KEY_MIN_CHARS", "LocalSpeechConfig", "kit_origin"]
