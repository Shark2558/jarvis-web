# src/jarvis/belongings/text.py
"""Words for "Where did I keep it?" (R2 D11). Pure, no I/O.

thing_key(name)        the key two names share when they mean one thing: NFKC, case-folded,
                       invisible characters out, a leading my / the / our / a / an dropped, simple
                       plurals stripped, a small synonym table (specs / spectacles / glasses,
                       licence / license / DL, key / keys). "My passport" and "Passport" match.
looks_like_storage(t)  does a sentence say where a physical thing is kept? Memory's learning drops
                       such a learned fact: the owner keeps those in Things (encrypted, no implicit
                       learning). Facts the owner tells or adds himself are never checked.
"""

from __future__ import annotations

import re
import unicodedata

from jarvis.tools.card import strip_invisible

_WORD = re.compile(r"[^\W_]+(?:'[^\W_]+)?")
_LEADING = frozenset({"my", "the", "our", "a", "an", "his", "her", "their"})
_SYNONYMS = {
    "spec": "glass",
    "spectacle": "glass",
    "eyeglass": "glass",
    "eyeglasse": "glass",
    "license": "licence",
}
_WHOLE = {"licence": "driving licence", "dl": "driving licence", "licence dl": "driving licence"}
_KEEP_S = ("ss", "us", "is")


def _singular(word: str) -> str:
    w = word.removesuffix("'s")
    if len(w) > 4 and w.endswith("ies"):
        return w[:-3] + "y"
    if len(w) > 4 and w.endswith(("sses", "xes", "ches", "shes")):
        return w[:-2]
    if len(w) > 3 and w.endswith("s") and not w.endswith(_KEEP_S):
        return w[:-1]
    return w


def thing_key(name: object) -> str:
    """The comparison key of a thing's name; '' when nothing is left."""
    if not isinstance(name, str):
        return ""
    folded = unicodedata.normalize("NFKC", strip_invisible(name)).casefold().replace("\u2019", "'")
    words = [m.group(0) for m in _WORD.finditer(folded)]
    while words and words[0] in _LEADING:
        words.pop(0)
    words = [_SYNONYMS.get(s, s) for s in (_singular(w) for w in words)]
    key = " ".join(words)
    return _WHOLE.get(key, key)


# ---- the storage detector ----------------------------------------------------------------------

_PLACE = (
    r"(?:drawer|cupboard|shelf|shelves|locker|safe|almirah|almirahs|file|folder|bag|box|case|"
    r"suitcase|wallet|cabinet|closet|wardrobe|rack|pocket|purse|briefcase|trunk|tin|jar|"
    r"envelope|desk|table|bank|vault|compartment|glove|room|bedroom|kitchen|hall|attic|garage|"
    r"office|house|home|car)"
)
_PREP = r"(?:in|inside|on|under|behind|beside|at|near|within)"
_DET = r"(?:the|a|an|his|her|their|my|our|one's)"
_VERB = r"(?:kept|keeps|keep|stored|stores|store|stashed|hidden|hides|put|puts|placed|places)"
_KEPT_AT = re.compile(
    rf"\b{_VERB}\b(?:\s+[\w'\u2019-]+){{0,6}}?\s+{_PREP}\s+(?:{_DET}\s+)?(?:[\w'\u2019-]+\s+){{0,3}}?{_PLACE}\b",
    re.IGNORECASE,
)
_IS_IN = re.compile(
    rf"\b(?:is|are)\s+(?:kept\s+)?{_PREP}\s+(?:{_DET}\s+)?(?:[\w'\u2019-]+\s+){{0,3}}?{_PLACE}\b",
    re.IGNORECASE,
)
_PEOPLE_PLACES = re.compile(r"\b(?:lives?|works?|studies|studying|stays?|born)\b", re.IGNORECASE)


def looks_like_storage(text: object) -> bool:
    """True when `text` says where a thing is kept ("Passport is kept in the blue file")."""
    if not isinstance(text, str) or not text.strip():
        return False
    t = unicodedata.normalize("NFKC", strip_invisible(text))
    if _PEOPLE_PLACES.search(t) and not _KEPT_AT.search(t):
        return False
    return bool(_KEPT_AT.search(t) or _IS_IN.search(t))


__all__ = ["looks_like_storage", "thing_key"]
