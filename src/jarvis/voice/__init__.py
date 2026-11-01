# src/jarvis/voice/__init__.py
"""Voice (slice 9; Phase 1): speak to JARVIS, JARVIS speaks back.

Layer 2 (input processing: speech-to-text, the strict WAV reader), Layer 8 (response & output:
speakable text, text-to-speech) and Layer 7 (the owner's voice settings), behind vendor-neutral
ports. Google Cloud is the engine today (REST over httpx, credentials from ADC in `adc` — the
only module here that imports google-auth, loaded only when cloud voice is on). Costs are metered
in rupees in the existing monthly usage record, free up to Google's allowance.
"""

from jarvis.voice.catalogue import DEFAULT_VOICE, VOICES, PriceList, Voice, find_voice
from jarvis.voice.ports import (
    AudioTooLarge,
    BadAudio,
    NothingToSay,
    STTProvider,
    TokenSource,
    Transcript,
    TTSProvider,
    VoiceBusy,
    VoiceError,
    VoiceRejected,
    VoiceUnavailable,
)
from jarvis.voice.service import (
    SpeakRequest,
    TranscriptView,
    VoiceEngines,
    VoiceService,
    VoiceView,
    build_voice_service,
)
from jarvis.voice.settings import VoiceSettings, VoiceSettingsPatch, VoiceSettingsStore
from jarvis.voice.speakable import speakable
from jarvis.voice.wav import parse_wav

__all__ = [
    "DEFAULT_VOICE",
    "VOICES",
    "AudioTooLarge",
    "BadAudio",
    "NothingToSay",
    "PriceList",
    "STTProvider",
    "SpeakRequest",
    "TTSProvider",
    "TokenSource",
    "Transcript",
    "TranscriptView",
    "Voice",
    "VoiceBusy",
    "VoiceEngines",
    "VoiceError",
    "VoiceRejected",
    "VoiceService",
    "VoiceSettings",
    "VoiceSettingsPatch",
    "VoiceSettingsStore",
    "VoiceUnavailable",
    "VoiceView",
    "build_voice_service",
    "find_voice",
    "parse_wav",
    "speakable",
]
