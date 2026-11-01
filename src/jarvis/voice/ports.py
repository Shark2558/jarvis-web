# src/jarvis/voice/ports.py
"""Voice ports (slice 9; Layers 2 and 8): what a speech engine must do, what it returns, and the
errors every adapter maps its vendor's failures to. Vendor-neutral: Google today (D2, D3); a
voice the owner has the rights to (ElevenLabs, Piper, …) plugs in behind the same port (D1).

Error → HTTP (installed by jarvis.api.voice):
    VoiceUnavailable(reason)  503 {"error": "voice_unavailable", "reason": …}
    VoiceBusy                 429 {"error": "voice_busy"} + Retry-After (the vendor throttled)
    VoiceRejected             422 {"error": "input_rejected"} (the vendor refused voice / text)
    NothingToSay              422 {"error": "nothing_to_say"}
    BadAudio                  422 {"error": "bad_audio"}
    AudioTooLarge             413 {"error": "too_large"}
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol

Reason = Literal["api_disabled", "not_configured", "upstream_error", "timeout"]
REASONS: tuple[Reason, ...] = ("api_disabled", "not_configured", "upstream_error", "timeout")

_MESSAGES: dict[str, str] = {
    "api_disabled": (
        "Google's speech service is switched off for this project. Run the one-time Cloud Shell "
        "step (gcloud services enable texttospeech.googleapis.com speech.googleapis.com)."
    ),
    "not_configured": "Cloud voice is not set up on this server; the browser's voice is used.",
    "upstream_error": "Google's speech service could not answer just now. Try again shortly.",
    "timeout": "Google's speech service took too long to answer. Try again shortly.",
}


class VoiceError(RuntimeError):
    """Base for every voice failure; messages are owner-friendly and vendor-text free."""


class VoiceUnavailable(VoiceError):
    """The engine is off, down or too slow. `maybe_billed`: the request may have reached the
    vendor (sent, then a timeout or a broken connection, or an unreadable 2xx answer), so it may
    have been billed and the caller meters its estimate; False for a clean error answer or a
    request that never left (credentials, connect)."""

    def __init__(self, reason: Reason, *, maybe_billed: bool = False) -> None:
        self.reason: Reason = reason
        self.maybe_billed = maybe_billed
        super().__init__(_MESSAGES[reason])


class VoiceBusy(VoiceError):
    RETRY_AFTER_S = 10

    def __init__(self) -> None:
        super().__init__("Google's speech service is busy right now. Try again in a few seconds.")


class VoiceRejected(VoiceError):
    """The engine refused this voice or text (an invalid request, not an outage)."""


class NothingToSay(VoiceError):
    def __init__(self) -> None:
        super().__init__("There is nothing in that text to read aloud.")


class BadAudio(VoiceError):
    """Not 16 kHz mono 16-bit PCM WAV, or shorter / longer than allowed."""


class AudioTooLarge(VoiceError):
    def __init__(self, limit: int) -> None:
        super().__init__(f"Recordings are limited to {limit:,} bytes (about a minute).")


@dataclass(frozen=True)
class Transcript:
    text: str
    confidence: float | None
    billed_seconds: float | None  # what the engine says it billed (None: unknown)
    language: str | None


class TokenSource(Protocol):
    """Request headers proving who JARVIS is to the cloud (a bearer token, maybe a quota
    project). Raises VoiceUnavailable("not_configured") when no credentials exist."""

    async def headers(self) -> dict[str, str]: ...

    def invalidate(self) -> None: ...

    def close(self) -> None:
        """Release any connection the source keeps (called once at shutdown)."""
        ...

    @property
    def not_configured(self) -> bool:
        """True once credentials are known to be missing (cached)."""
        ...


class TTSProvider(Protocol):
    async def synthesize(self, text: str, *, voice: str, language: str, rate: float) -> bytes:
        """MP3 audio of `text` (already speakable) in `voice`."""
        ...

    async def voices(self, language: str) -> frozenset[str]:
        """The voice ids the engine offers for `language` (cached by the adapter)."""
        ...


class STTProvider(Protocol):
    async def recognize(
        self, pcm: bytes, *, sample_rate: int, language: str, phrases: tuple[str, ...]
    ) -> Transcript:
        """Text of 16-bit little-endian mono PCM."""
        ...


__all__ = [
    "REASONS",
    "AudioTooLarge",
    "BadAudio",
    "NothingToSay",
    "Reason",
    "STTProvider",
    "TTSProvider",
    "TokenSource",
    "Transcript",
    "VoiceBusy",
    "VoiceError",
    "VoiceRejected",
    "VoiceUnavailable",
]
