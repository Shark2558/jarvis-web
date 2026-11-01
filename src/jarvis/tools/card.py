# src/jarvis/tools/card.py
"""Approval-card text (Layer 4 → 1): what the owner reads before an irreversible step.

Any value placed on a card may come from someone else — a subject the model copied out of a
mail, an event title an outside organiser wrote — so each field is flattened to one visually
honest line: control characters and line/paragraph separators become spaces, bidi and zero-width
format characters are removed (they can make "exe.gpj" read as "jpg.exe"), whitespace collapses,
and the field is cut to a limit with an ellipsis.
"""

from __future__ import annotations

import re
from typing import Any

# C0, DEL, C1 (incl. U+0085 NEL), U+2028 LINE SEPARATOR, U+2029 PARAGRAPH SEPARATOR
_BREAKING = re.compile("[\x00-\x1f\x7f-\x9f\u2028\u2029]")
# bidi embeddings/overrides/isolates and marks, zero-width characters, invisible operators, BOM
_INVISIBLE = re.compile("[\u061c\u200b-\u200f\u202a-\u202e\u2060-\u2064\u2066-\u2069\ufeff]")
ELLIPSIS = "…"


def one_line(value: Any, limit: int) -> str:
    """`value` as one sanitised line of at most `limit` characters ('' for None)."""
    text = "" if value is None else str(value)
    text = _INVISIBLE.sub("", _BREAKING.sub(" ", text))
    text = " ".join(text.split())
    if len(text) <= limit:
        return text
    return text[: max(limit - 1, 0)].rstrip() + ELLIPSIS


def quoted(value: Any, limit: int) -> str:
    """One line in typographic quotes, so a title can't blend into the card's own words."""
    return f"“{one_line(value, limit)}”"


def has_line_breaking_chars(text: str) -> bool:
    """True when `text` holds a C0/C1 control or a Unicode line/paragraph separator: never
    allowed in a mail header value (header injection, or a header split by a lenient parser)."""
    return bool(_BREAKING.search(text))


def has_invisible_chars(text: str) -> bool:
    return bool(_INVISIBLE.search(text))


__all__ = ["ELLIPSIS", "has_invisible_chars", "has_line_breaking_chars", "one_line", "quoted"]
