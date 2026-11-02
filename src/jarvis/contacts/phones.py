# src/jarvis/contacts/phones.py
"""Phone numbers as E.164 (slice 12 D5/D6). Pure: no I/O, stdlib only (imported by the reply
model through `jarvis.whatsapp.draft`, so it must not pull in `jarvis.tools`).

The owner is in India, so a number written without a country code is read as Indian:
10 digits starting 2-9 (mobile 6-9, landline STD code + subscriber), the same after a trunk 0,
or 91 + a 10-digit mobile written without "+". Anything else must carry its country code
("+44 …" or "0044 …"). Only ASCII digits and the usual separators (space, - . ( )) are read: a
letter, an extension, a second "+" or an invisible character makes it no number at all.

`typed_numbers` is the phone twin of `tools.addresses.typed_addresses`: the numbers written in a
text (the owner's own words), normalised exactly like a recipient, so "98765 43210" in a message
matches "+919876543210" in a draft. Linear in the text and bounded (`MAX_TYPED`).
"""

from __future__ import annotations

import re

E164 = re.compile(r"\+[1-9][0-9]{6,14}")
INDIA = "91"
MAX_TYPED = 50
_SEPARATORS = re.compile(r"[ \-.()]")
_ALLOWED = re.compile(r"\+?[0-9 \-.()]+")
# A run that might be a number: digits with separators between them, at most 24 characters
# (the bound keeps every match short; a longer run is never one number).
_RUN = re.compile(r"(?<![0-9+])\+?[0-9][0-9 \-.()]{5,22}[0-9](?![0-9])")
_LONGEST_RUN = 40  # a run of number characters longer than this is skipped, never split


def is_e164(value: object) -> bool:
    return isinstance(value, str) and bool(E164.fullmatch(value))


def _indian(digits: str) -> str | None:
    if len(digits) == 10 and digits[0] in "23456789":
        return "+" + INDIA + digits
    if len(digits) == 11 and digits[0] == "0" and digits[1] in "23456789":
        return "+" + INDIA + digits[1:]
    if len(digits) == 12 and digits.startswith(INDIA) and digits[2] in "6789":
        return "+" + digits
    return None


def to_e164(raw: object) -> str:
    """`raw` as E.164 ('+919876543210'), or ValueError in plain words."""
    text = raw.strip() if isinstance(raw, str) else ""
    if not text or not text.isascii() or not _ALLOWED.fullmatch(text):
        raise ValueError("not a phone number (digits, with the country code if not Indian)")
    if text.count("+") > 1 or ("+" in text and not text.startswith("+")):
        raise ValueError("not a phone number: a + may only start it")
    digits = _SEPARATORS.sub("", text.lstrip("+"))
    international = text.startswith("+")
    if not international and digits.startswith("00"):
        international, digits = True, digits[2:]
    if international:
        if digits.startswith(INDIA + "0") and len(digits) == 13:
            digits = INDIA + digits[3:]  # "+91 0 98765 43210": the trunk 0 does not belong
        out = "+" + digits
    else:
        found = _indian(digits)
        if found is None:
            raise ValueError(
                "not a number JARVIS can use: give it with its country code, e.g. +44 20 7946 0958"
            )
        out = found
    if not E164.fullmatch(out):
        raise ValueError("not a phone number (an international number has 7 to 15 digits)")
    return out


def wa_digits(number: str) -> str:
    """The digits of an E.164 number, as a wa.me link wants them (no "+", no separators)."""
    if not is_e164(number):
        raise ValueError("not an E.164 number")
    return number[1:]


def _split(run: str) -> list[str]:
    """Numbers in a run that is not one number as a whole: read word by word, left to right,
    a pair of words before a single word, each word used once — so two numbers written side by
    side ('98765 43210 99999 88888') are both read, and never the middle pair."""
    words, out, i = run.split(), [], 0
    while i < len(words):
        pair = _try(f"{words[i]} {words[i + 1]}") if i + 1 < len(words) else None
        if pair is not None:
            out.append(pair)
            i += 2
            continue
        one = _try(words[i])
        if one is not None:
            out.append(one)
        i += 1
    return out


def typed_numbers(text: str) -> frozenset[str]:
    """The phone numbers written in `text` as E.164 (see the module docstring)."""
    found: set[str] = set()
    for m in _RUN.finditer(text or ""):
        run = m.group(0)
        if len(run) > _LONGEST_RUN:
            continue
        whole = _try(run)
        for got in [whole] if whole is not None else _split(run):
            if len(found) >= MAX_TYPED:
                return frozenset(found)
            found.add(got)
    return frozenset(found)


def _try(candidate: str) -> str | None:
    try:
        return to_e164(candidate)
    except ValueError:
        return None


__all__ = ["E164", "MAX_TYPED", "is_e164", "to_e164", "typed_numbers", "wa_digits"]
