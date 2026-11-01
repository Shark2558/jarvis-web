# src/jarvis/recall/text.py
"""Text helpers for memory: one-line cleaning, keyword cleaning, and the lexical tokens that
retrieval and duplicate detection share (lower-case, stop words out, light stemming)."""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable

from jarvis.recall.models import MAX_KEYWORD_CHARS, MAX_KEYWORDS
from jarvis.tools.card import one_line, strip_invisible

_WORD = re.compile(r"[^\W_]+(?:'[^\W_]+)?")
_CONTROL_KEEP_NL = re.compile(r"[\x00-\x09\x0b-\x1f\x7f-\x9f]")
STOP = frozenset(
    """a an and are as at be been being but by can could did do does doing for from had has have
    having he her hers him his how i i'm i've if in into is it it's its me might my myself no nor
    not of on or our ours please same she should so some such than that the their theirs them then
    there these they this those to too very was we were what when where which while who whom why
    will with would you your yours yourself owner owner's sir jarvis tell remind know
    called named name's about again also any just get got mine let's all""".split()
)


def clean_text(value: object, limit: int) -> str:
    """One visible line (controls, line breaks, bidi and zero-width characters gone), whitespace
    collapsed, cut to `limit` characters WITHOUT an ellipsis (a fact is stored as written)."""
    text = one_line(value, 10 * limit + 100)
    return text[:limit].rstrip()


def clean_block(value: object, limit: int) -> str:
    """A profile block: line breaks kept, other controls and invisible characters removed."""
    text = str(value or "").replace("\r\n", "\n").replace("\r", "\n")
    text = strip_invisible(_CONTROL_KEEP_NL.sub(" ", text))
    lines = [" ".join(ln.split()) for ln in text.split("\n")]
    return "\n".join(lines).strip()[: limit + 1]


def clean_keywords(raw: Iterable[object] | None) -> tuple[str, ...]:
    """≤ 8 distinct lower-case keywords of ≤ 30 characters (anything else dropped)."""
    out: list[str] = []
    for k in raw or ():
        if not isinstance(k, str):
            continue
        word = clean_text(k, 200).lower()
        if not word or len(word) > MAX_KEYWORD_CHARS or word in out:
            continue
        out.append(word)
        if len(out) == MAX_KEYWORDS:
            break
    return tuple(out)


def _stem(word: str) -> str:
    """A deliberately small stemmer: the same word forms meet (plural, -ing, -ed, -ly, final e)."""
    w = word.removesuffix("'s").removesuffix("'")
    if len(w) > 4 and w.endswith("ies"):
        w = w[:-3] + "y"
    elif len(w) > 4 and w.endswith(("sses", "xes", "ches", "shes")):
        w = w[:-2]
    elif len(w) > 3 and w.endswith("s") and not w.endswith(("ss", "us", "is")):
        w = w[:-1]
    for suffix in ("ing", "ed", "ly"):
        if len(w) > len(suffix) + 2 and w.endswith(suffix):
            w = w[: -len(suffix)]
            if len(w) > 2 and w[-1] == w[-2] and w[-1] not in "aeiouls":
                w = w[:-1]
            break
    if len(w) > 3 and w.endswith("e"):
        w = w[:-1]
    return w


def tokens(text: str) -> list[str]:
    """Content words of `text`, lower-cased and stemmed, in order (duplicates kept)."""
    folded = unicodedata.normalize("NFKC", str(text or "")).lower().replace("’", "'")
    out: list[str] = []
    for m in _WORD.finditer(folded):
        w = m.group(0)
        if w in STOP or w.removesuffix("'s") in STOP:
            continue
        s = _stem(w)
        if s and s not in STOP:
            out.append(s)
    return out


def norm_key(text: str) -> str:
    """Equality key for duplicates: case, punctuation and spacing ignored."""
    folded = unicodedata.normalize("NFKC", str(text or "")).lower()
    return " ".join(m.group(0) for m in _WORD.finditer(folded))


def overlap(a: str, b: str) -> float:
    """Jaccard overlap of content-word sets (0 … 1)."""
    ta, tb = set(tokens(a)), set(tokens(b))
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


__all__ = ["STOP", "clean_block", "clean_keywords", "clean_text", "norm_key", "overlap", "tokens"]
