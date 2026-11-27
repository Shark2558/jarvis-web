# src/jarvis/calls/speech/detect.py
"""Which language the other person speaks (R18 B; Layer 2) — the strategy across the options.

Plan 5.3, "automatic switching": use the hearing option's own language detection where it has
one, else try each language. A call card allows English + up to 3 Indian languages, so there are
at most 4 candidates, the call's current language first.

    google    NativeDetector: one request, the first candidate as `languageCode` and the others
              as `alternativeLanguageCodes`; Google answers in the language it detected
    sarvam    NativeDetector: `language_code=unknown`; Sarvam's detected language and its
              probability (paid: only when the owner turned Sarvam on)
    azure     TryEachDetector: Azure's short-audio REST API has no detection, so the utterance is
              heard in each candidate in turn and the most confident answer wins (each try holds
              F0's free seconds: at most 4 per utterance, and only when the engine asks)
    bhashini  TryEachDetector (no detection; no confidence either: the script check decides)
    laptop    TryEachDetector here; on the desk the laptop's own models detect (`heard_text`)

Every answer is checked against its language's script (`script_fits`): words that came back in
another script (Devanagari for Tamil audio asked as Tamil...) count for SCRIPT_MISMATCH of their
confidence. The engine then `decide`s: switch only to a language the card allows, and only at
CONFIDENT or more, from JARVIS's next sentence; a confident language the card does not allow is
"unsupported" (JARVIS says so politely in English and Hindi and offers a call back); anything
else stays. Engines call `detect` when a turn's confidence is low or its script disagrees, not
on every turn, which keeps the free allowances for hearing.
"""

from __future__ import annotations

import unicodedata
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

from jarvis.calls.ports import Hearing, LanguageDetector
from jarvis.calls.speech.catalogue import GOOGLE, SARVAM

CONFIDENT = 0.7  # the detector must be at least this sure to switch
SCRIPT_MISMATCH = 0.3
MAX_CANDIDATES = 4  # English + up to 3 Indian languages a call

_DEVANAGARI = frozenset({"DEVANAGARI"})
_SCRIPTS: dict[str, frozenset[str]] = {
    "en-IN": frozenset({"LATIN"}),
    "hi-IN": _DEVANAGARI,
    "mr-IN": _DEVANAGARI,
    "ne-IN": _DEVANAGARI,
    "kok-IN": _DEVANAGARI,
    "mai-IN": _DEVANAGARI,
    "brx-IN": _DEVANAGARI,
    "doi-IN": _DEVANAGARI,
    "sa-IN": _DEVANAGARI,
    "bn-IN": frozenset({"BENGALI"}),
    "as-IN": frozenset({"BENGALI"}),
    "mni-IN": frozenset({"BENGALI", "MEETEI"}),
    "pa-IN": frozenset({"GURMUKHI"}),
    "gu-IN": frozenset({"GUJARATI"}),
    "or-IN": frozenset({"ORIYA"}),
    "ta-IN": frozenset({"TAMIL"}),
    "te-IN": frozenset({"TELUGU"}),
    "kn-IN": frozenset({"KANNADA"}),
    "ml-IN": frozenset({"MALAYALAM"}),
    "ur-IN": frozenset({"ARABIC"}),
    "ks-IN": frozenset({"ARABIC", "DEVANAGARI"}),
    "sd-IN": frozenset({"ARABIC", "DEVANAGARI"}),
    "sat-IN": frozenset({"OL"}),
}


def _script(ch: str) -> str | None:
    if not (ch.isalpha() or unicodedata.category(ch).startswith("M")):  # letters, vowel signs
        return None
    name = unicodedata.name(ch, "")
    return name.split(" ", 1)[0] if name else None


def dominant_script(text: str) -> str | None:
    """The Unicode script most of `text`'s letters and vowel signs are in (None: none)."""
    counts = Counter(s for s in map(_script, text) if s)
    return counts.most_common(1)[0][0] if counts else None


def script_fits(text: str, lang: str) -> bool:
    """True when `text` is in `lang`'s script (or has no letters to judge, or the script of
    `lang` is not known)."""
    script = dominant_script(text)
    expected = _SCRIPTS.get(lang)
    return script is None or expected is None or script in expected


def _score(text: str, lang: str, confidence: float) -> float:
    return confidence if script_fits(text, lang) else confidence * SCRIPT_MISMATCH


class NativeDetector:
    """The option detects in one request (Google's alternatives, Sarvam's "unknown")."""

    def __init__(self, hearing: Hearing) -> None:
        self.hearing = hearing

    async def detect(self, pcm16k: bytes, candidates: Sequence[str]) -> tuple[str, float]:
        heard = await self.hearing.transcribe(pcm16k, list(candidates)[:MAX_CANDIDATES])
        return heard.lang, _score(heard.text, heard.lang, heard.confidence)


class TryEachDetector:
    """The utterance heard in each candidate in turn; the best (confidence × script) wins, the
    earlier candidate (the call's current language) on a tie."""

    def __init__(self, hearing: Hearing) -> None:
        self.hearing = hearing

    async def detect(self, pcm16k: bytes, candidates: Sequence[str]) -> tuple[str, float]:
        best: tuple[str, float] | None = None
        for lang in list(dict.fromkeys(candidates))[:MAX_CANDIDATES]:
            heard = await self.hearing.transcribe(pcm16k, [lang])
            score = _score(heard.text, lang, heard.confidence)
            if best is None or score > best[1]:
                best = (lang, score)
        if best is None:
            raise ValueError("no candidate language")
        return best


def detector_for(hearing: Hearing) -> LanguageDetector:
    if hearing.name in (GOOGLE, SARVAM):
        return NativeDetector(hearing)
    return TryEachDetector(hearing)


@dataclass(frozen=True)
class Decision:
    kind: Literal["stay", "switch", "unsupported"]
    lang: str


def decide(current: str, detected: str, confidence: float, allowed: Sequence[str]) -> Decision:
    """What the call does with one detection (see the module docstring)."""
    if detected == current or confidence < CONFIDENT:
        return Decision("stay", current)
    if detected in allowed:
        return Decision("switch", detected)
    return Decision("unsupported", detected)


__all__ = [
    "CONFIDENT",
    "MAX_CANDIDATES",
    "SCRIPT_MISMATCH",
    "Decision",
    "NativeDetector",
    "TryEachDetector",
    "decide",
    "detector_for",
    "dominant_script",
    "script_fits",
]
