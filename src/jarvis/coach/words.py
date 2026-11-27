# src/jarvis/coach/words.py
"""R8 I0 seam S21 (docs/plans/r8-vision.md 6.5, ADR-51): every coach's fixed words, and the
not-medical list the automated test scans them with (tests/test_r8_not_medical.py).

A coach says only fixed sentences: counts, times, a form tip from its own list, "Stop if anything
hurts", "Practice only, not medical advice". It never states a diagnosis, a medicine or a dose,
and never tells him what a number means for his health. The one exception is the blood-pressure
category (the owner's D7), which is shown only as the published table's own name with its source
(`jarvis.coach.bp.category_line`), so the category names are not in this module's lists.

`NOT_MEDICAL` are the words and stems a coach's words may never contain (lower case, matched as
plain substrings on word boundaries where the entry starts with a letter). Builders add their
coaches' word lists to `COACH_WORDS` (Python) or to a `const WORDS = Object.freeze([...])` list in
their console module; the test scans both, and every `view` the evals produce.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from types import MappingProxyType

STOP = "Stop if anything hurts."
PRACTICE = "Practice only, not medical advice."
SAFETY: tuple[str, ...] = (STOP, PRACTICE)
POSTURE_NUDGE = "Sit back and lift your head, Sir."
PAUSED_CAMERA = "The camera was stopped."
WHO_UNKNOWN = "Guest"  # an unknown person's results: "Guest 1", "Guest 2" ... (D6)

# the words the coaches I0 knows say (each builder adds its own list here or in its module)
COACH_WORDS: Mapping[str, tuple[str, ...]] = MappingProxyType(
    {
        "safety": SAFETY,
        "posture": (POSTURE_NUDGE, "Sit up straight for 10 seconds.", "Calibrated."),
        "camera": (PAUSED_CAMERA,),
    }
)

NOT_MEDICAL: tuple[str, ...] = (
    *("you have", "you may have", "you might have", "you suffer", "diagnos", "disease"),
    *("disorder", "condition is", "hypertension", "hypotension", "arrhythmi", "normal range"),
    *("abnormal", "healthy range", "risk of", "mg", "dose", "dosage", "take your", "tablet"),
    *("pill", "medicine", "medication", "prescri", "treat", "cure", "therapy for", "symptom"),
    *("injury is", "you are sick", "illness"),
)
_WORDISH = {w: re.compile(rf"(?<![a-z]){re.escape(w)}") for w in NOT_MEDICAL}


def medical_hits(text: str) -> list[str]:
    """The not-medical entries a text contains (empty: it may be said)."""
    low = str(text).lower()
    return [w for w, rx in _WORDISH.items() if rx.search(low)]


def scan(lines: Iterable[str]) -> list[tuple[str, list[str]]]:
    """Every line that says something a coach may not, with what it said."""
    return [(line, hits) for line in lines if (hits := medical_hits(line))]


__all__ = [
    "COACH_WORDS",
    "NOT_MEDICAL",
    "PAUSED_CAMERA",
    "POSTURE_NUDGE",
    "PRACTICE",
    "SAFETY",
    "STOP",
    "WHO_UNKNOWN",
    "medical_hits",
    "scan",
]
