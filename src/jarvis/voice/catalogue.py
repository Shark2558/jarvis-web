# src/jarvis/voice/catalogue.py
"""The voices JARVIS offers (slice 9 §4) and what speech costs (D2, D3, D9).

No voice is a clone of anyone (D1): these are stock Google voices the owner picks from, with a
preview. The default comes first. Prices and free allowances are settings (Google's list prices,
verified 2026-11-01); usage is metered under the keys below in the monthly usage record.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from jarvis.config import Settings

VoiceType = Literal["chirp3-hd", "studio"]
VOICE_LANGUAGE = "en-GB"
RATE_MIN, RATE_MAX, RATE_DEFAULT = 0.8, 1.25, 1.0
# Server-fixed, original preview line (§3); never a film quote.
SAMPLE_LINE = (
    "Good evening, {honorific}. Systems are running smoothly — which, I'm told, is my job."
)


@dataclass(frozen=True)
class Voice:
    id: str  # Google's voice name
    label: str
    style: str
    type: VoiceType
    language: str = VOICE_LANGUAGE


VOICES: tuple[Voice, ...] = (
    Voice("en-GB-Chirp3-HD-Algieba", "Algieba", "smooth", "chirp3-hd"),
    Voice("en-GB-Chirp3-HD-Sadaltager", "Sadaltager", "knowledgeable", "chirp3-hd"),
    Voice("en-GB-Chirp3-HD-Charon", "Charon", "informative, deeper", "chirp3-hd"),
    Voice("en-GB-Chirp3-HD-Iapetus", "Iapetus", "clear", "chirp3-hd"),
    Voice("en-GB-Chirp3-HD-Schedar", "Schedar", "even", "chirp3-hd"),
    Voice("en-GB-Studio-B", "Studio B", "formal, crisp", "studio"),
)
DEFAULT_VOICE = VOICES[0].id
_BY_ID = {v.id: v for v in VOICES}
TYPES: tuple[VoiceType, ...] = ("chirp3-hd", "studio")
TTS_KEYS: dict[VoiceType, str] = {"chirp3-hd": "tts_chirp3-hd", "studio": "tts_studio"}
STT_KEY = "stt_seconds"
METER_LABEL = "voice"


def find_voice(voice_id: str) -> Voice | None:
    return _BY_ID.get(voice_id)


@dataclass(frozen=True)
class Price:
    key: str  # the monthly usage counter
    usd_per_unit: float  # one character (TTS) / one second (STT)
    free_units: float  # per month


@dataclass(frozen=True)
class PriceList:
    chirp3_hd: Price
    studio: Price
    stt: Price

    @classmethod
    def from_settings(cls, s: Settings) -> PriceList:
        free = float(s.voice_tts_free_chars)
        return cls(
            chirp3_hd=Price(TTS_KEYS["chirp3-hd"], s.voice_price_chirp3_hd_usd_per_m / 1e6, free),
            studio=Price(TTS_KEYS["studio"], s.voice_price_studio_usd_per_m / 1e6, free),
            stt=Price(STT_KEY, s.voice_price_stt_usd_per_min / 60, float(s.voice_stt_free_seconds)),
        )

    def tts(self, vtype: VoiceType) -> Price:
        return self.chirp3_hd if vtype == "chirp3-hd" else self.studio


__all__ = [
    "DEFAULT_VOICE",
    "METER_LABEL",
    "RATE_DEFAULT",
    "RATE_MAX",
    "RATE_MIN",
    "SAMPLE_LINE",
    "STT_KEY",
    "TTS_KEYS",
    "TYPES",
    "VOICES",
    "VOICE_LANGUAGE",
    "Price",
    "PriceList",
    "Voice",
    "VoiceType",
    "find_voice",
]
