# src/jarvis/tools/card.py
"""Approval-card text (Layer 4 → 1): what the owner reads before an irreversible step.

Any value placed on a card may come from someone else — a subject the model copied out of a
mail, an event title an outside organiser wrote — so each field is flattened to one visually
honest line: control characters and line/paragraph separators become spaces, and every
character that renders as nothing (or changes how its neighbours render) is removed — chosen
by Unicode category, not a hand-picked list: format characters (Cf: bidi controls, zero-width
characters, soft hyphen, tag characters, …), private-use and surrogate code points, Hangul and
other fillers, and variation selectors. They can make "exe.gpj" read as "jpg.exe", or split a
link so a filter misses it. Whitespace collapses and the field is cut to a limit with an
ellipsis.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any

# C0, DEL, C1 (incl. U+0085 NEL), U+2028 LINE SEPARATOR, U+2029 PARAGRAPH SEPARATOR — exactly
# the categories Cc, Zl and Zp. Turned into spaces by `one_line`; never allowed in a header.
_BREAKING = re.compile("[\x00-\x1f\x7f-\x9f  ]")
# Removed outright: format, private use, surrogates (categories) …
_DROP_CATEGORIES = frozenset({"Cf", "Co", "Cs"})
# … and these, whose categories (Lo, Mn) also hold ordinary letters and accents.
_FILLERS = frozenset("­͏ᅟᅠ᠎ㅤﾠ")
_INVISIBLE_RANGES = (
    (0xFE00, 0xFE0F),  # variation selectors 1-16
    (0xE0000, 0xE007F),  # tag block
    (0xE0100, 0xE01EF),  # variation selectors 17-256
)
ELLIPSIS = "…"


def _is_invisible(ch: str) -> bool:
    if ch in _FILLERS or unicodedata.category(ch) in _DROP_CATEGORIES:
        return True
    code = ord(ch)
    return any(lo <= code <= hi for lo, hi in _INVISIBLE_RANGES)


def _strip_invisible(text: str) -> str:
    if text.isascii():  # fast path: nothing in ASCII is invisible (controls are "breaking")
        return text
    return "".join(ch for ch in text if not _is_invisible(ch))


def one_line(value: Any, limit: int) -> str:
    """`value` as one sanitised line of at most `limit` characters ('' for None)."""
    text = "" if value is None else str(value)
    text = _strip_invisible(_BREAKING.sub(" ", text))
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
    """True when `text` holds a character `one_line` would remove. Line breaks and tabs are not
    invisible (see `has_line_breaking_chars`), so a mail body may keep them."""
    return not text.isascii() and any(_is_invisible(ch) for ch in text)


def strip_invisible(text: str) -> str:
    """`text` without invisible characters; line breaks and all other text kept as they are."""
    return _strip_invisible(text)


__all__ = [
    "ELLIPSIS",
    "has_invisible_chars",
    "has_line_breaking_chars",
    "one_line",
    "quoted",
    "strip_invisible",
]
