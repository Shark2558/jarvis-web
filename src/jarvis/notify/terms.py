# src/jarvis/notify/terms.py
"""Emergency words (R3 D10 rule 3): English, Hindi, Malayalam and Odia, in native script and
common Latin spellings. Word-boundary, case-folded, NFC. A false positive rings, which is the
safe direction. Marks of Indic scripts count as word characters, so a boundary never falls in
the middle of a word or after a vowel sign."""

from __future__ import annotations

import re
import unicodedata

_WORD = r"[\w\u0900-\u0dff\u200c\u200d]"
_LATIN = (
    "fire",
    "aag",
    "help",
    "bachao",
    "bachaao",
    "ambulance",
    "accident",
    "hospital",
    "police",
    "thief",
    "chor",
    "gas leak",
    "smoke",
    "flood",
    "kallan",
    "rakshikkane",
)
_NATIVE = (
    "\u0906\u0917",  # aag (Hindi)
    "\u092c\u091a\u093e\u0913",  # bachao
    "\u091a\u094b\u0930",  # chor
    "\u0d24\u0d40",  # thee (Malayalam: fire)
    "\u0d30\u0d15\u0d4d\u0d37\u0d3f\u0d15\u0d4d\u0d15\u0d23\u0d47",  # rakshikkane
    "\u0d15\u0d33\u0d4d\u0d33\u0d7b",  # kallan (atomic chillu)
    "\u0d15\u0d33\u0d4d\u0d33\u0d28\u0d4d\u200d",  # kallan (legacy chillu)
    "\u0b28\u0b3f\u0b06\u0b01",  # nian (Odia: fire)
    "\u0b2c\u0b1e\u0b4d\u0b1a\u0b3e\u0b05",  # banchaa (Odia: save me)
    "\u0b1a\u0b4b\u0b30",  # chor (Odia)
)


def _compile() -> re.Pattern[str]:
    parts = []
    for term in (*_LATIN, *_NATIVE):
        norm = unicodedata.normalize("NFC", term).casefold()
        parts.append(r"\s+".join(re.escape(w) for w in norm.split()))
    return re.compile(rf"(?<!{_WORD})(?:{'|'.join(parts)})(?!{_WORD})")


_PATTERN = _compile()


def emergency(text: str | None) -> bool:
    """True when `text` holds an emergency word."""
    if not text:
        return False
    return _PATTERN.search(unicodedata.normalize("NFC", text).casefold()) is not None


__all__ = ["emergency"]
