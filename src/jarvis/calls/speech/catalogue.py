# src/jarvis/calls/speech/catalogue.py
"""The languages a call may use and the speech options that list them (R18 B; plan 5.2).

"Listed" is the provider's own language list (read 25 Nov 2026), never a promise: a language is
offered on a call card only after it passes the language check (plan 5.3, `jarvis.calls.langcheck`).
Codes are BCP-47 (`hi-IN`). The options, in the order the check prefers them (free first, the
laptop first; Sarvam only when the owner turned it on, with its ₹):

    laptop    the call desk's own models (AI4Bharat IndicConformer to hear, Indic Parler-TTS /
              Piper to speak; a Whisper-family model for English): ₹0, audio never leaves it
    google    Google Cloud Speech-to-Text v1 / Text-to-Speech (Chirp 3: HD), within JARVIS's
              shared free allowance, then priced (≈ ₹2.29 a minute, ≈ ₹2.86 per 1,000 chars)
    azure     Microsoft Azure Speech free tier F0: ₹0, cannot bill; stops at its allowance
    bhashini  the Government of India's Bhashini (ULCA pipeline): ₹0 at low volume; optional
    sarvam    Sarvam (Saaras to hear, Bulbul v3 to speak): paid, off unless enabled

Voices are stock voices (never a clone of anyone, JARVIS's rule D1): male, to match JARVIS's own.
FLEURS (google/fleurs, CC BY 4.0) has test clips for English and the 12 major Indian languages,
Nepali and Sindhi; the rest of the 22 scheduled languages have no FLEURS set (the check says so).
"""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType

Option = str
LAPTOP, GOOGLE, AZURE, BHASHINI, SARVAM = "laptop", "google", "azure", "bhashini", "sarvam"
OPTION_ORDER: tuple[Option, ...] = (LAPTOP, GOOGLE, AZURE, BHASHINI, SARVAM)
PAID_OPTIONS = frozenset({SARVAM})
FREE_OPTIONS = frozenset(OPTION_ORDER) - PAID_OPTIONS
ENGLISH = "en-IN"

_L, _G, _A, _B, _S = LAPTOP, GOOGLE, AZURE, BHASHINI, SARVAM


@dataclass(frozen=True)
class Language:
    code: str  # BCP-47
    name: str  # in English, for the owner's table
    short: str  # ISO 639 code (Bhashini's)
    hear: frozenset[Option]
    speak: frozenset[Option]
    fleurs: str | None = None  # the FLEURS config of its test clips
    azure_voice: str | None = None


def _lang(
    code: str,
    name: str,
    short: str,
    hear: str,
    speak: str,
    fleurs: str | None = None,
    azure_voice: str | None = None,
) -> Language:
    def opts(s: str) -> frozenset[Option]:
        return frozenset(o for o in OPTION_ORDER if o[0] in s)

    return Language(code, name, short, opts(hear), opts(speak), fleurs, azure_voice)


# (hear, speak) letters: l = laptop, g = Google, a = Azure, b = Bhashini, s = Sarvam (plan 5.2;
# Sarvam: its 10 Indian languages + English; Punjabi's laptop voice is unofficial)
_TABLE: tuple[Language, ...] = (
    _lang("en-IN", "English", "en", "lgas", "gas", "en_us", "en-IN-PrabhatNeural"),
    _lang("hi-IN", "Hindi", "hi", "lgabs", "lgabs", "hi_in", "hi-IN-MadhurNeural"),
    _lang("bn-IN", "Bengali", "bn", "lgabs", "lgabs", "bn_in", "bn-IN-BashkarNeural"),
    _lang("mr-IN", "Marathi", "mr", "lgabs", "lgabs", "mr_in", "mr-IN-ManoharNeural"),
    _lang("te-IN", "Telugu", "te", "lgabs", "lgabs", "te_in", "te-IN-MohanNeural"),
    _lang("ta-IN", "Tamil", "ta", "lgabs", "lgabs", "ta_in", "ta-IN-ValluvarNeural"),
    _lang("gu-IN", "Gujarati", "gu", "lgabs", "lgabs", "gu_in", "gu-IN-NiranjanNeural"),
    _lang("kn-IN", "Kannada", "kn", "lgabs", "lgabs", "kn_in", "kn-IN-GaganNeural"),
    _lang("ml-IN", "Malayalam", "ml", "lgabs", "lgabs", "ml_in", "ml-IN-MidhunNeural"),
    _lang("ur-IN", "Urdu", "ur", "lgab", "gab", "ur_pk", "ur-IN-SalmanNeural"),
    _lang("or-IN", "Odia", "or", "labs", "labs", "or_in", "or-IN-SukantNeural"),
    _lang("pa-IN", "Punjabi", "pa", "lgabs", "lgabs", "pa_in", "pa-IN-OjasNeural"),
    _lang("as-IN", "Assamese", "as", "lgab", "lab", "as_in", "as-IN-PriyomNeural"),
    _lang("ne-IN", "Nepali", "ne", "lb", "lb", "ne_np"),
    _lang("kok-IN", "Konkani", "kok", "lb", "lb"),
    _lang("mai-IN", "Maithili", "mai", "lb", "lb"),
    _lang("brx-IN", "Bodo", "brx", "lb", "lb"),
    _lang("doi-IN", "Dogri", "doi", "lb", "lb"),
    _lang("mni-IN", "Manipuri", "mni", "lb", "lb"),
    _lang("sat-IN", "Santali", "sat", "lb", "lb"),
    _lang("sa-IN", "Sanskrit", "sa", "lb", "lb"),
    _lang("ks-IN", "Kashmiri", "ks", "lb", "lb"),
    _lang("sd-IN", "Sindhi", "sd", "lb", "lb", "sd_in"),
)
LANGUAGES: MappingProxyType[str, Language] = MappingProxyType({x.code: x for x in _TABLE})
# English plus the 12 major Indian languages: what the check runs on by default (the owner adds
# any other language of the table)
DEFAULT_CHECK: tuple[str, ...] = tuple(x.code for x in _TABLE[:13])
GOOGLE_VOICE_STEM = "Algieba"  # Chirp 3: HD's stock voices exist in every language it speaks
SARVAM_SPEAKER = "shubh"  # Bulbul v3's default (male) voice


def language(code: str) -> Language:
    """The table's entry; KeyError (with the code) for a language JARVIS does not list."""
    try:
        return LANGUAGES[code]
    except KeyError:
        raise KeyError(f"unknown call language {code!r}") from None


def hears(option: Option, code: str) -> bool:
    entry = LANGUAGES.get(code)
    return entry is not None and option in entry.hear


def speaks(option: Option, code: str) -> bool:
    entry = LANGUAGES.get(code)
    return entry is not None and option in entry.speak


def google_voice(code: str, stem: str = GOOGLE_VOICE_STEM) -> str:
    return f"{code}-Chirp3-HD-{stem}"


__all__ = [
    "AZURE",
    "BHASHINI",
    "DEFAULT_CHECK",
    "ENGLISH",
    "FREE_OPTIONS",
    "GOOGLE",
    "GOOGLE_VOICE_STEM",
    "LANGUAGES",
    "LAPTOP",
    "OPTION_ORDER",
    "PAID_OPTIONS",
    "SARVAM",
    "SARVAM_SPEAKER",
    "Language",
    "Option",
    "google_voice",
    "hears",
    "language",
    "speaks",
]
