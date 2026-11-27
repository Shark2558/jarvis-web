# src/jarvis/calls/cards.py
"""Call cards (R18 A1; docs/plans/r18-calls.md section 4 step 1, sections 7 and 8; Layer 5,
Communication skill): which numbers JARVIS may call.

`check_number` reads what the owner typed (or the fast tier proposed) as an Indian number in
E.164, or refuses it in plain words with a stable `code`:

- `emergency`: 100, 101, 102, 108, 112, 1091, 1098, 181 and the other national helplines. JARVIS
  never calls them; the owner calls them himself.
- `premium`: premium-rate 1900 numbers.
- `international`: any country code but +91 (TRAI's personal-use limits; plan 7.4).
- `short_code`: any other short code or special service (fewer than 10 digits, or a 10-11 digit
  number in the 1xxx service ranges such as the 140 telemarketing series). The one exception is
  toll-free 1800 numbers (customer care and helpline menus), which are allowed.
- `invalid`: not a phone number at all.

Only ASCII digits and the usual separators (space, - . ( )) are read; a letter, a second "+" or
an invisible character makes it no number. `masked` is the only form a number takes in a log.
"""

from __future__ import annotations

import re
from typing import Literal

RefusedCode = Literal["emergency", "premium", "international", "short_code", "invalid"]

INDIA = "91"
# National emergency and helpline short codes (police, fire, ambulance, the single emergency
# number, women, children, the cyber-crime line, disaster, railway, elders, ...). Any other
# short code is refused as `short_code`; these get the clearer "emergency" words.
EMERGENCY_CODES = frozenset(
    {
        "100", "101", "102", "103", "104", "108", "112", "139", "181", "1070", "1077",
        "1078", "1091", "1097", "1098", "1930", "14567", "155260",
    }
)  # fmt: skip
TOLL_FREE = re.compile(r"1800[0-9]{7}")
PREMIUM_PREFIX = "1900"
NATIONAL = re.compile(r"[2-9][0-9]{9}")
_ALLOWED = re.compile(r"\(?\+?[0-9 \-.()]+")
_SEPARATORS = re.compile(r"[ \-.()]")

MSG_EMERGENCY = (
    "JARVIS never calls emergency or helpline numbers. Please call it yourself straight away."
)
MSG_PREMIUM = "JARVIS doesn't call premium-rate (1900) numbers."
MSG_INTERNATIONAL = "JARVIS calls only Indian numbers (+91); it doesn't call other countries."
MSG_SHORT = "JARVIS doesn't call short codes or special service numbers."
MSG_INVALID = "That isn't a phone number JARVIS can use: give the 10-digit number."


class NumberRefused(ValueError):
    """A number JARVIS may not call; `str()` is plain words for the owner, `code` is stable."""

    def __init__(self, code: RefusedCode, message: str) -> None:
        super().__init__(message)
        self.code: RefusedCode = code


def _digits(raw: object) -> tuple[str, bool]:
    """(digits, written with an international prefix) or NumberRefused("invalid")."""
    text = raw.strip() if isinstance(raw, str) else ""
    if not text or not text.isascii() or not _ALLOWED.fullmatch(text):
        raise NumberRefused("invalid", MSG_INVALID)
    if text.count("+") > 1 or ("+" in text and not text.lstrip("(").startswith("+")):
        raise NumberRefused("invalid", MSG_INVALID)
    digits = _SEPARATORS.sub("", text).lstrip("+")
    if not digits.isdigit():
        raise NumberRefused("invalid", MSG_INVALID)
    if "+" in text:
        return digits, True
    if digits.startswith("00"):
        return digits[2:], True
    return digits, False


def _national(raw: object) -> str:
    """The number without +91 / 91 / the trunk 0, or NumberRefused("international")."""
    digits, international = _digits(raw)
    if international:
        if not digits.startswith(INDIA):
            raise NumberRefused("international", MSG_INTERNATIONAL)
        digits = digits[len(INDIA) :]
    elif len(digits) == 12 and digits.startswith(INDIA) and digits[2] in "6789":
        digits = digits[len(INDIA) :]  # "91 90000 00001": the code written without "+"
    if digits.startswith("0"):
        digits = digits[1:]  # one trunk 0 ("0471 ...", "+91 0 90000 ...")
    if not digits:
        raise NumberRefused("invalid", MSG_INVALID)
    return digits


def check_number(raw: object) -> str:
    """`raw` as an Indian E.164 number JARVIS may call, or NumberRefused (plain words + code)."""
    national = _national(raw)
    if national in EMERGENCY_CODES:
        raise NumberRefused("emergency", MSG_EMERGENCY)
    if national.startswith(PREMIUM_PREFIX):
        raise NumberRefused("premium", MSG_PREMIUM)
    if TOLL_FREE.fullmatch(national):
        return "+" + INDIA + national
    if national.startswith("1") or len(national) < len("9000000001"):
        raise NumberRefused("short_code", MSG_SHORT)
    if not NATIONAL.fullmatch(national):
        raise NumberRefused("invalid", MSG_INVALID)
    return "+" + INDIA + national


def masked(e164: str) -> str:
    """The only form a number takes in a log or the audit: "+91 …0001"."""
    if not isinstance(e164, str) or not re.fullmatch(r"\+91[0-9]{10,11}", e164):
        return "…"
    return f"+91 …{e164[-4:]}"


__all__ = [
    "EMERGENCY_CODES",
    "NumberRefused",
    "RefusedCode",
    "check_number",
    "masked",
]
