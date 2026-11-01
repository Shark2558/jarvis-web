# src/jarvis/recall/sensitive.py
"""The deterministic sensitive-data filter (slice 8 D9). Every write path — learned, tool, API,
import, profile — runs `sensitive_reason` and refuses what it flags; nothing here calls a model.

Flagged: card numbers (13–19 digits passing Luhn), Aadhaar (12 digits, 4-4-4 or bare, or the
word with digits), PAN (`AAAAA9999A`), IFSC / IBAN-like codes, bank account numbers (an account
word with 9–18 digits), passport / voter / licence numbers, passwords / passphrases / OTPs /
CVVs / PINs stated with a value, and access keys (sk-…, AKIA…, ghp_…). Postal PIN codes are not
secrets. The reason names the kind of data, never the value.

`special_category` is a second, coarser check applied to LEARNED facts only (the extraction
prompt already excludes these): health, religion, caste, politics, sexuality. A fact the owner
explicitly tells or adds is their choice; one a model inferred is dropped.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Callable

_CARD_RUN = re.compile(r"(?<![\w+])(?:\d[ .-]?){12,18}\d(?!\w)")
_AADHAAR = re.compile(r"(?<![\w+])[2-9]\d{3}([ .-]?)\d{4}\1\d{4}(?!\w)")
_AADHAAR_WORD = re.compile(r"(?i)\baadh?aa?r\b.*\d{4}")
_PAN = re.compile(r"(?<![A-Za-z0-9])[A-Za-z]{5}\d{4}[A-Za-z](?![A-Za-z0-9])")
_IFSC = re.compile(r"(?<![A-Za-z0-9])[A-Z]{4}0[A-Z0-9]{6}(?![A-Za-z0-9])")
_IFSC_WORD = re.compile(r"(?i)\bifsc\b.*(?<![A-Za-z0-9])[A-Za-z]{4}0[A-Za-z0-9]{6}(?![A-Za-z0-9])")
_IBAN = re.compile(r"(?<![A-Za-z0-9])[A-Z]{2}\d{2}(?: ?[A-Z0-9]){11,30}(?![A-Za-z0-9])")
_IBAN_WORD = re.compile(r"(?i)\biban\b")
_ACCOUNT_WORD = re.compile(r"(?i)(?:\baccount\b|\bacct\b|\ba/c\b|\bbank\b)")
_LONG_NUMBER = re.compile(r"(?<![\w+])\d(?:[ .-]?\d){8,17}(?!\w)")
_ID_WORD = re.compile(
    r"(?i)\b(?:passport|voter\s*id|epic\s*(?:no|number)|driving\s*licen[cs]e|dl\s*(?:no|number)"
    r"|licen[cs]e\s*(?:no|number))\b"
)
_ID_VALUE = re.compile(r"(?<![A-Za-z0-9])[A-Za-z]{0,4}\d{6,16}(?![A-Za-z0-9])")
_SECRET_WORD = (
    r"(?:password|passcode|passwd|passphrase|pwd|otp|one[- ]time\s+(?:password|code)|cvv|cvc"
    r"|security\s+code|api\s+key|secret\s+key|private\s+key|access\s+token|seed\s+phrase"
    r"|recovery\s+phrase)"
)
_SECRET_STATED = re.compile(rf"(?i)\b{_SECRET_WORD}\b\s*(?:is|was|=|:|-)\s*\S")
_SECRET_VALUE = re.compile(rf"(?i)\b{_SECRET_WORD}\b\s*(?:no\.?|number|code)?\s*[\w@#$%&*!-]*\d")
_PIN = re.compile(
    r"(?i)\b(?:upi\s+|atm\s+|debit\s+card\s+|card\s+|my\s+)?pin\b(?!\s*-?\s*codes?\b)"
    r"\s*(?:no\.?|number)?\s*(?:is|was|=|:|-)?\s*\d{4,6}(?!\d)"
)
_ACCESS_KEY = re.compile(
    r"(?:\bsk-[A-Za-z0-9_-]{16,}|\bAKIA[0-9A-Z]{16}\b|\bgh[pousr]_[A-Za-z0-9]{30,}"
    r"|\bxox[abprs]-[A-Za-z0-9-]{10,}|\bAIza[0-9A-Za-z_-]{30,})"
)
_SPECIAL = re.compile(
    r"(?i)\b(?:diagnos\w*|disease|illness|disorder|medication|medicine|prescri\w*|therap(?:y|ist)"
    r"|surgery|pregnan\w*|hiv|cancer|diabet\w*|depress\w*|anxiety|mental\s+health"
    r"|blood\s+pressure|religion|religious|caste|hindu|muslim|christian|sikh|jain|buddhist"
    r"|jewish|atheist|votes?|voted|voting|political|politics|sexual\w*|gay|lesbian|bisexual"
    r"|transgender|queer)\b"
)


def _luhn(digits: str) -> bool:
    total = 0
    for i, ch in enumerate(reversed(digits)):
        d = int(ch)
        if i % 2 == 1:
            d = d * 2 - 9 if d > 4 else d * 2
        total += d
    return total % 10 == 0


def _has_card(text: str) -> bool:
    for m in _CARD_RUN.finditer(text):
        digits = re.sub(r"\D", "", m.group(0))
        if 13 <= len(digits) <= 19 and _luhn(digits):
            return True
    return False


def _has_account(text: str) -> bool:
    if not _ACCOUNT_WORD.search(text):
        return False
    return any(9 <= len(re.sub(r"\D", "", m.group(0))) <= 18 for m in _LONG_NUMBER.finditer(text))


def _normal(text: str) -> str:
    """NFKC (fullwidth digits → ASCII); invisible format characters dropped (so "4111<ZWSP>1111"
    reads as one number); line breaks, tabs and other controls become spaces (a separator, so
    "a/c no<newline>5010…" still reads as an account word next to a number)."""
    folded = unicodedata.normalize("NFKC", str(text or ""))
    out = []
    for ch in folded:
        cat = unicodedata.category(ch)
        if cat in ("Cc", "Zl", "Zp"):
            out.append(" ")
        elif cat != "Cf":
            out.append(ch)
    return " ".join("".join(out).split())


_CHECKS: tuple[tuple[str, Callable[[str], bool]], ...] = (
    ("a card number", _has_card),
    ("an Aadhaar number", lambda t: bool(_AADHAAR.search(t) or _AADHAAR_WORD.search(t))),
    ("a PAN", lambda t: bool(_PAN.search(t))),
    ("a bank IFSC code", lambda t: bool(_IFSC.search(t) or _IFSC_WORD.search(t))),
    ("an IBAN", lambda t: bool(_IBAN.search(t) or _IBAN_WORD.search(t))),
    ("a bank account number", _has_account),
    ("an ID document number", lambda t: bool(_ID_WORD.search(t) and _ID_VALUE.search(t))),
    ("an access key", lambda t: bool(_ACCESS_KEY.search(t))),
    ("a password, OTP or security code", lambda t: bool(_SECRET_STATED.search(t))),
    ("a password, OTP or security code", lambda t: bool(_SECRET_VALUE.search(t))),
    ("a PIN", lambda t: bool(_PIN.search(t))),
)


def sensitive_reason(text: str) -> str | None:
    """What kind of private data `text` holds (never the value), or None."""
    t = _normal(text)
    for reason, check in _CHECKS:
        if check(t):
            return reason
    return None


def is_sensitive(text: str) -> bool:
    return sensitive_reason(text) is not None


def special_category(text: str) -> bool:
    """Health, religion, caste, politics or sexuality: learned facts with these are dropped."""
    return bool(_SPECIAL.search(_normal(text)))


__all__ = ["is_sensitive", "sensitive_reason", "special_category"]
