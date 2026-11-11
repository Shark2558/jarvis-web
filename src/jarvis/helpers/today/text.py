# src/jarvis/helpers/today/text.py
"""Part A's text checks (docs/plans/r11-free-helpers.md D7; R11 A security review HIGH-1, MEDIUM-1).
Pure, no I/O. Every bill field, the payee's name, the UPI note and the UPI ID use these.

- `has_number`: a card, account or consumer number in `text`. Invisible characters are dropped,
  the text is NFKC-normalised and every decimal digit of any script counts (fullwidth, Arabic-Indic,
  Devanagari ...). Digit groups are joined across ANY run of characters that are neither letters
  nor digits (spaces of every kind, `.` `-` `/` `_` `,` `:`, dashes, bars, bullets ...). A number is
  13 or more digits joined that way (every card length, Amex's 4-6-5 too), or more than
  `plain_max` digits in a row (4 in his text; a UPI ID allows 10, a mobile number).
- `payee_name`: a payee's name only in a safe set, so it can't imitate a UPI ID or the card's own
  words: Latin letters, spaces and `. , ' & -`, at most 40, with a letter. It is NFKC-normalised,
  accents are dropped and the Cyrillic and Greek letters that look Latin are mapped to Latin; any
  digit, `@`, bracket, control, bidi or invisible character is refused.
- `name_from_label`: a bill with no payee's name is paid in its label's name, kept to that set.
- `name_key`: how a bill's name is matched (spaces collapsed, case-folded).
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any

from jarvis.tools.card import strip_invisible

CARD_DIGITS = 13
PLAIN_MAX = 4
UPI_PLAIN_MAX = 10  # a mobile number's length: a UPI ID like 9800000000@bank is fine
PAYEE_MAX = 40
PAYEE_FALLBACK = "Payee"
NUMBER_REFUSAL = (
    "Keep card, account and consumer numbers out of your bills, Sir: the last 4 digits at most."
)
PAYEE_REFUSAL = (
    "A payee's name is Latin letters, spaces and . , ' & - only, Sir (no digits, no @), "
    "at most 40 characters."
)
_JOINED = re.compile(r"[0-9]+(?:[\W_]+[0-9]+)*")  # digit groups and what separates them
_NOT_DIGIT = re.compile(r"[^0-9]")
_SAFE_NAME = re.compile(r"[A-Za-z .,'&-]+")
_UNSAFE_CHAR = re.compile(r"[^A-Za-z .,'&-]")
_LETTER = re.compile(r"[A-Za-z]")
_LOOK_ALIKES: dict[str, tuple[str, ...]] = {
    "A": ("CYRILLIC CAPITAL LETTER A", "GREEK CAPITAL LETTER ALPHA"),
    "B": ("CYRILLIC CAPITAL LETTER VE", "GREEK CAPITAL LETTER BETA"),
    "C": ("CYRILLIC CAPITAL LETTER ES",),
    "E": ("CYRILLIC CAPITAL LETTER IE", "GREEK CAPITAL LETTER EPSILON"),
    "H": ("CYRILLIC CAPITAL LETTER EN", "GREEK CAPITAL LETTER ETA", "CYRILLIC CAPITAL LETTER SHHA"),
    "I": ("CYRILLIC CAPITAL LETTER BYELORUSSIAN-UKRAINIAN I", "GREEK CAPITAL LETTER IOTA"),
    "J": ("CYRILLIC CAPITAL LETTER JE",),
    "K": ("CYRILLIC CAPITAL LETTER KA", "GREEK CAPITAL LETTER KAPPA"),
    "M": ("CYRILLIC CAPITAL LETTER EM", "GREEK CAPITAL LETTER MU"),
    "N": ("GREEK CAPITAL LETTER NU",),
    "O": ("CYRILLIC CAPITAL LETTER O", "GREEK CAPITAL LETTER OMICRON"),
    "P": ("CYRILLIC CAPITAL LETTER ER", "GREEK CAPITAL LETTER RHO"),
    "S": ("CYRILLIC CAPITAL LETTER DZE",),
    "T": ("CYRILLIC CAPITAL LETTER TE", "GREEK CAPITAL LETTER TAU"),
    "W": ("CYRILLIC CAPITAL LETTER WE",),
    "X": ("CYRILLIC CAPITAL LETTER HA", "GREEK CAPITAL LETTER CHI"),
    "Y": ("CYRILLIC CAPITAL LETTER STRAIGHT U", "GREEK CAPITAL LETTER UPSILON"),
    "Z": ("GREEK CAPITAL LETTER ZETA",),
    "a": ("CYRILLIC SMALL LETTER A", "GREEK SMALL LETTER ALPHA"),
    "c": ("CYRILLIC SMALL LETTER ES",),
    "d": ("CYRILLIC SMALL LETTER KOMI DE",),
    "e": ("CYRILLIC SMALL LETTER IE",),
    "h": ("CYRILLIC SMALL LETTER SHHA",),
    "i": (
        "CYRILLIC SMALL LETTER BYELORUSSIAN-UKRAINIAN I",
        "GREEK SMALL LETTER IOTA",
        "LATIN SMALL LETTER DOTLESS I",
    ),
    "j": ("CYRILLIC SMALL LETTER JE",),
    "k": ("GREEK SMALL LETTER KAPPA",),
    "l": ("CYRILLIC SMALL LETTER PALOCHKA",),
    "o": ("CYRILLIC SMALL LETTER O", "GREEK SMALL LETTER OMICRON"),
    "p": ("CYRILLIC SMALL LETTER ER", "GREEK SMALL LETTER RHO"),
    "q": ("CYRILLIC SMALL LETTER QA",),
    "s": ("CYRILLIC SMALL LETTER DZE",),
    "u": ("GREEK SMALL LETTER UPSILON",),
    "v": ("GREEK SMALL LETTER NU",),
    "w": ("CYRILLIC SMALL LETTER WE",),
    "x": ("CYRILLIC SMALL LETTER HA", "GREEK SMALL LETTER CHI"),
    "y": ("CYRILLIC SMALL LETTER U",),
}
_TO_LATIN = str.maketrans(
    {unicodedata.lookup(n): latin for latin, names in _LOOK_ALIKES.items() for n in names}
)


class BillRefused(ValueError):
    """A bill value JARVIS won't keep or use; the message is plain words for the owner."""


def ascii_digits(text: str) -> str:
    """Every decimal digit, in any script, as its ASCII digit (fullwidth ４, Arabic-Indic ٤: 4)."""
    if text.isascii():
        return text
    return "".join(
        str(d) if (d := unicodedata.decimal(ch, None)) is not None else ch for ch in text
    )


def has_number(text: str, *, plain_max: int = PLAIN_MAX) -> bool:
    """A card, account or consumer number in `text` (a date, a year or a time is fine)."""
    flat = ascii_digits(unicodedata.normalize("NFKC", strip_invisible(text)))
    if re.search(f"[0-9]{{{plain_max + 1},}}", flat):
        return True
    return any(len(_NOT_DIGIT.sub("", m[0])) >= CARD_DIGITS for m in _JOINED.finditer(flat))


def _latin(text: str) -> str:
    """NFKC, accents dropped, the Cyrillic and Greek look-alikes as the Latin letters they mimic."""
    split = unicodedata.normalize("NFKD", unicodedata.normalize("NFKC", text))
    return "".join(ch for ch in split if unicodedata.category(ch) != "Mn").translate(_TO_LATIN)


def payee_name(value: Any) -> str:
    """His payee's name in the safe set ("" for none), or BillRefused in plain words."""
    if value is None:
        return ""
    if not isinstance(value, str):
        raise BillRefused("The payee's name must be text.")
    flat = " ".join(value.split())
    if not flat:
        return ""
    if has_number(flat):
        raise BillRefused(NUMBER_REFUSAL)
    name = _latin(flat)
    if len(name) > PAYEE_MAX or not _SAFE_NAME.fullmatch(name) or not _LETTER.search(name):
        raise BillRefused(PAYEE_REFUSAL)
    return name


def name_from_label(label: str) -> str:
    """The name a bill with no payee's name is paid in: its label kept to the safe set."""
    kept = " ".join(_UNSAFE_CHAR.sub(" ", _latin(label)).split())[:PAYEE_MAX].strip()
    return kept if _LETTER.search(kept) else PAYEE_FALLBACK


def name_key(text: str) -> str:
    """A bill's name as it is matched: spaces collapsed, case-folded."""
    return " ".join(text.split()).casefold()


__all__ = [
    "CARD_DIGITS",
    "NUMBER_REFUSAL",
    "PAYEE_MAX",
    "PAYEE_REFUSAL",
    "UPI_PLAIN_MAX",
    "BillRefused",
    "ascii_digits",
    "has_number",
    "name_from_label",
    "name_key",
    "payee_name",
]
