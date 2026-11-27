# src/jarvis/calls/speech/__init__.py
"""R18 B: a call's hearing and voice (Layers 2, 6 and 8), behind I0's ports.

Adapters (`Hearing`, `Voice` of `jarvis.calls.ports`), all REST over httpx (no vendor SDK), all
taking and returning 16 kHz mono PCM16 (`audio`):

- `google`    Google via `jarvis.voice` (its request, credentials and free allowance)
- `azure`     Microsoft Azure Speech free tier F0 (cannot bill; stops at its allowance)
- `bhashini`  Bhashini's ULCA pipeline (optional)
- `sarvam`    Sarvam (paid: off unless the owner turned it on)

Around them: `rest` (one deadline, retries only where nothing was billed, plain errors),
`errors` (all `ports.SpeechUnavailable`), `meter` (every ₹ through `jarvis.billing`), `detect`
(language detection and the switch decision), `catalogue` (languages and options), `lines` and
`translate` (the pre-made lines, translated and spoken once), `phoneline` (the 8 kHz G.711
simulation for the language check) and `build` (the options a deployment has).
"""

from jarvis.calls.speech.build import SpeechOptions, build_speech
from jarvis.calls.speech.catalogue import DEFAULT_CHECK, LANGUAGES, OPTION_ORDER, PAID_OPTIONS
from jarvis.calls.speech.detect import Decision, decide, detector_for
from jarvis.calls.speech.errors import (
    AllowanceUsedUp,
    NotOffered,
    OptionUnavailable,
    PaidOptionOff,
    SpeechBusy,
    SpeechError,
    SpeechRejected,
)
from jarvis.calls.speech.lines import LINES, LinesCache
from jarvis.calls.speech.meter import CALLS_LABEL, SpeechMeter
from jarvis.calls.speech.phoneline import phone_line
from jarvis.calls.speech.translate import BrainTranslator, Translation, TranslationRefused

__all__ = [
    "CALLS_LABEL",
    "DEFAULT_CHECK",
    "LANGUAGES",
    "LINES",
    "OPTION_ORDER",
    "PAID_OPTIONS",
    "AllowanceUsedUp",
    "BrainTranslator",
    "Decision",
    "LinesCache",
    "NotOffered",
    "OptionUnavailable",
    "PaidOptionOff",
    "SpeechBusy",
    "SpeechError",
    "SpeechMeter",
    "SpeechOptions",
    "SpeechRejected",
    "Translation",
    "TranslationRefused",
    "build_speech",
    "decide",
    "detector_for",
    "phone_line",
]
