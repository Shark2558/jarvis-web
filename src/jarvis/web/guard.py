# src/jarvis/web/guard.py
"""The private-query guard (slice 10 B): a search query leaves our control for good (Tavily keeps
query data and may pass it to other search-index providers — see the slice 10 plan), so a query
that holds an email address, a phone / account / ID number, or anything the memory sensitive filter
flags (card, Aadhaar, PAN, bank, ID numbers, passwords, keys) is refused before it is sent.
Deterministic, no model call; the reason names the kind of data, never the value.

Hardened after the slice 10 security review (H1). Every check reads the query as `_normal` gives
it: NFKC (full-width "＠" and "９" become "@" and "9"), invisible and control characters removed
(a zero-width space can't split a number), and every decimal digit of any script turned into an
ASCII digit (Devanagari "९८४५…", Malayalam "൯൮൪൫…"). Then:
  - any "@", "%40", "(at)" / "[at]" / "{at}", or "x at y dot z" is an email address;
  - a run of 8+ digits, whatever sits between them (spaces, dashes, dots, slashes, brackets) and
    whatever is glued in front ("tel9845012345"), is a phone / account / ID number — after the
    harmless shapes are set aside: calendar dates, year ranges, an ISBN;
  - single characters spaced out ("A B C D E 1 2 3 4 F") are also read joined up, so the
    sensitive filter sees the PAN.
Commas never join digit groups, so "1,40,00,00,000" stays an amount.
"""

from __future__ import annotations

import re
import unicodedata

from jarvis.recall.sensitive import sensitive_reason
from jarvis.tools.card import _is_invisible

_AT = re.compile(
    r"@|%40|[\(\[\{<]\s*at\s*[\)\]\}>]|\bat\s+[\w-]+\s+dot\b|[\(\[\{<]\s*dot\s*[\)\]\}>]",
    re.IGNORECASE,
)
# harmless digit shapes, set aside before the long-number check
_DATE = re.compile(
    r"\b(?:\d{4}[-/.]\d{1,2}[-/.]\d{1,2}|\d{1,2}[-/.]\d{1,2}[-/.](?:\d{4}|\d{2}))\b(?![-/.]\d)"
)
_YEARS = re.compile(r"\b(?:19|20)\d{2}\s*[-–/]\s*(?:(?:19|20)\d{2}|\d{2})\b(?![-/.]\d)")
_ISBN = re.compile(r"(?i)\bisbn(?:-1[03])?\s*:?\s*[\dXx][\d\s-]{8,16}[\dXx]\b")
_DIGIT_RUN = re.compile(r"\d(?:[\s\-./()_+·–—]{0,3}\d)*")
MIN_RUN_DIGITS = 8
_SPACED = re.compile(r"(?<![A-Za-z0-9])[A-Za-z0-9](?:[\s\-._/]{1,3}[A-Za-z0-9](?![A-Za-z0-9])){4,}")


def _normal(query: str) -> str:
    out: list[str] = []
    for ch in unicodedata.normalize("NFKC", query):
        cat = unicodedata.category(ch)
        if cat in ("Cc", "Zl", "Zp"):
            out.append(" ")
        elif cat == "Cn" or _is_invisible(ch):
            continue
        elif not ch.isascii() and (d := unicodedata.decimal(ch, None)) is not None:
            out.append(str(d))
        else:
            out.append(ch)
    return "".join(out)


def _long_number(text: str) -> bool:
    for shape in (_ISBN, _DATE, _YEARS):
        text = shape.sub(" x ", text)
    return any(
        sum(c.isdigit() for c in m.group(0)) >= MIN_RUN_DIGITS for m in _DIGIT_RUN.finditer(text)
    )


def _joined_up(text: str) -> str:
    """Spaced-out single characters ("A B C D E 1 2 3 4 F"), read joined up."""
    return " ".join(re.sub(r"[^A-Za-z0-9]", "", m.group(0)) for m in _SPACED.finditer(text))


def query_problem(query: str) -> str | None:
    """What private data `query` holds ("an email address", …), or None."""
    text = _normal(query)
    if _AT.search(text):
        return "an email address"
    if reason := sensitive_reason(f"{text} {_joined_up(text)}"):
        return reason
    if _long_number(text):
        return "a phone, account or ID number"
    return None


__all__ = ["MIN_RUN_DIGITS", "query_problem"]
