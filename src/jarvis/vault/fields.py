# src/jarvis/vault/fields.py
"""Deterministic field extraction for vault PDFs (R2 D4). Pure: no I/O, no model.

`propose(text, type_hint)` reads the text of a PDF IN MEMORY (the caller never stores or logs it)
and returns a `Proposal`: dates next to a fixed label table per type (same line or the next, at
most 80 characters away), the last 4 characters of an ID number when exactly one candidate of the
type's pattern is found, and a type guess from fixed title phrases. Dates are day-first only, as
written in India; a two-digit year, an impossible date or two different candidates give nothing.
The proposal holds the fixed label and the parsed value, never raw text.
"""

from __future__ import annotations

import datetime as dt
import re

from jarvis.vault.models import TYPES, Proposal

WINDOW = 80
YEAR_MIN, YEAR_MAX = 1950, 2100
_MONTHS = {m: i for i, m in enumerate("jan feb mar apr may jun jul aug sep oct nov dec".split(), 1)}

_DATE_TOKEN = re.compile(
    r"(?<![\dA-Za-z])(?:"
    r"\d{1,4}[/.\-]\d{1,2}[/.\-]\d{1,4}"
    r"|\d{1,2}[ \-][A-Za-z]{3,9}[ \-,]+\d{2,4}"
    r")(?![\dA-Za-z])"
)
_NUMERIC = re.compile(r"(\d{1,4})[/.\-](\d{1,2})[/.\-](\d{1,4})")
_WORDY = re.compile(r"(\d{1,2})[ \-]([A-Za-z]{3,9})[ \-,]+(\d{2,4})")
_NEXT_LABEL = re.compile(
    r"(?i)\b(?:date\s+of|valid|issue[ds]?|expir\w*|policy|period|fitness|registration\s+validity)\b"
)


def _date(y: int, m: int, d: int) -> dt.date | None:
    if not YEAR_MIN <= y <= YEAR_MAX:
        return None
    try:
        return dt.date(y, m, d)
    except ValueError:
        return None


def parse_date(token: str) -> dt.date | None:
    """One written date, day-first (or ISO year-first). None for anything else."""
    m = _NUMERIC.fullmatch(token)
    if m is not None:
        a, b, c = m.groups()
        if len(a) == 4 and len(b) == 2 and len(c) == 2:  # ISO
            return _date(int(a), int(b), int(c))
        if len(c) == 4 and len(a) <= 2:
            return _date(int(c), int(b), int(a))  # DD/MM/YYYY: never month-first
        return None
    w = _WORDY.fullmatch(token)
    if w is not None:
        day, mon, year = w.groups()
        month = _MONTHS.get(mon[:3].lower())
        if month is None or len(year) != 4:
            return None
        return _date(int(year), month, int(day))
    return None


def _window(text: str, end: int) -> str:
    """What follows a label: its own line and the next, at most 80 characters, up to the next
    label (a label with no value must not borrow the next label's date)."""
    raw = text[end : end + WINDOW + 40]
    lines = raw.split("\n")
    raw = "\n".join(lines[:2])[:WINDOW]
    cut = _NEXT_LABEL.search(raw)
    return raw[: cut.start()] if cut else raw


def _first_date(window: str) -> dt.date | None:
    """The first date-looking token, strictly parsed: a malformed first token is no date."""
    m = _DATE_TOKEN.search(window)
    return None if m is None else parse_date(m.group(0))


def _label(words: str) -> re.Pattern[str]:
    return re.compile(words.replace(" ", r"\s+"), re.IGNORECASE)


# (display label, pattern). Groups are tried in order; within a group two different dates = nothing.
Group = tuple[tuple[str, re.Pattern[str]], ...]
GENERIC_EXPIRY: tuple[Group, ...] = (
    (
        ("Date of Expiry", _label("date of expiry")),
        ("Expiry Date", _label("expiry date")),
        ("Valid Till", _label("valid till")),
        ("Valid upto", _label("valid up\\s?to")),
    ),
)
EXPIRY: dict[str, tuple[Group, ...]] = {
    "passport": ((("Date of Expiry", _label("date of expiry")),),),
    "driving_licence": (
        (("Valid Till", _label("valid till")),),
        (("Validity (NT)", _label(r"validity\s*\(nt\)")),),
        (("Validity (TR)", _label(r"validity\s*\(tr\)")),),
    ),
    "vehicle_rc": (
        (("Registration Validity", _label("registration validity")),),
        (("Fitness Upto", _label("fitness up\\s?to")),),
    ),
    "puc": ((("Valid upto", _label("valid up\\s?to")),),),
}
for _t in ("vehicle_insurance", "health_insurance", "life_insurance", "other_insurance"):
    EXPIRY[_t] = (
        (("Policy Expiry", _label("policy expiry")),),
        (("Valid upto", _label("valid up\\s?to")),),
    )
ISSUE = (("Date of Issue", _label("date of issue")),)
PERIOD = re.compile(r"period\s+of\s+insurance", re.IGNORECASE)

_LAST4: dict[str, re.Pattern[str]] = {
    "pan": re.compile(r"\b[A-Z]{5}[0-9]{4}[A-Z]\b"),
    "passport": re.compile(r"\b[A-Z][0-9]{7}\b"),
    "driving_licence": re.compile(r"\b[A-Z]{2}[ \-]?[0-9]{2}[ \-]?[0-9]{4}[ \-]?[0-9]{7}\b"),
    "vehicle_rc": re.compile(r"\b[A-Z]{2}[ \-]?[0-9]{1,2}[ \-]?[A-Z]{1,3}[ \-]?[0-9]{4}\b"),
}
_AADHAAR = re.compile(r"(?<!\d)[0-9]{4}\s?[0-9]{4}\s?[0-9]{4}(?!\d)")

_TYPE_PHRASES: tuple[tuple[re.Pattern[str], str], ...] = tuple(
    (re.compile(p, re.IGNORECASE), t)
    for p, t in (
        (r"pollution\s+under\s+control", "puc"),
        (r"driving\s+licen[cs]e", "driving_licence"),
        (r"certificate\s+of\s+registration", "vehicle_rc"),
        (r"permanent\s+account\s+number", "pan"),
        (r"\baadhaar\b", "aadhaar"),
        (r"election\s+commission", "voter_id"),
        (r"birth\s+certificate", "birth_certificate"),
        (r"health\s+insurance|mediclaim", "health_insurance"),
        (r"life\s+insurance", "life_insurance"),
        (r"motor\s+insurance|private\s+car|two\s+wheeler", "vehicle_insurance"),
        (r"\bpassport\b", "passport"),
    )
)

# ---- Verhoeff (Aadhaar) -----------------------------------------------------------------------
_D = (
    (0, 1, 2, 3, 4, 5, 6, 7, 8, 9),
    (1, 2, 3, 4, 0, 6, 7, 8, 9, 5),
    (2, 3, 4, 0, 1, 7, 8, 9, 5, 6),
    (3, 4, 0, 1, 2, 8, 9, 5, 6, 7),
    (4, 0, 1, 2, 3, 9, 5, 6, 7, 8),
    (5, 9, 8, 7, 6, 0, 4, 3, 2, 1),
    (6, 5, 9, 8, 7, 1, 0, 4, 3, 2),
    (7, 6, 5, 9, 8, 2, 1, 0, 4, 3),
    (8, 7, 6, 5, 9, 3, 2, 1, 0, 4),
    (9, 8, 7, 6, 5, 4, 3, 2, 1, 0),
)
_P = (
    (0, 1, 2, 3, 4, 5, 6, 7, 8, 9),
    (1, 5, 7, 6, 2, 8, 3, 0, 9, 4),
    (5, 8, 0, 3, 7, 9, 6, 1, 4, 2),
    (8, 9, 1, 6, 0, 4, 3, 5, 2, 7),
    (9, 4, 5, 3, 1, 2, 6, 8, 7, 0),
    (4, 2, 8, 6, 5, 7, 3, 9, 0, 1),
    (2, 7, 9, 3, 8, 0, 6, 4, 1, 5),
    (7, 0, 4, 6, 9, 1, 3, 2, 5, 8),
)


def verhoeff_ok(number: str) -> bool:
    if not number.isdigit():
        return False
    c = 0
    for i, ch in enumerate(reversed(number)):
        c = _D[c][_P[i % 8][int(ch)]]
    return c == 0


# ---- extraction ----------------------------------------------------------------------------------


def _dates_for(text: str, groups: tuple[Group, ...]) -> tuple[dt.date, str] | None:
    for group in groups:
        found: dict[dt.date, str] = {}
        for label, pattern in group:
            for m in pattern.finditer(text):
                d = _first_date(_window(text, m.end()))
                if d is not None:
                    found.setdefault(d, label)
        if len(found) > 1:
            return None
        if found:
            ((d, label),) = found.items()
            return d, label
    return None


def _period(text: str) -> tuple[dt.date, dt.date] | None:
    found: set[tuple[dt.date, dt.date]] = set()
    for m in PERIOD.finditer(text):
        tokens = _DATE_TOKEN.findall(text[m.end() : m.end() + WINDOW + 40])
        if len(tokens) >= 2:
            a, b = parse_date(tokens[0]), parse_date(tokens[1])
            if a is not None and b is not None and a < b:
                found.add((a, b))
    return next(iter(found)) if len(found) == 1 else None


def _last4(text: str, type_id: str) -> str | None:
    if type_id == "aadhaar":
        hits = {re.sub(r"\s", "", m.group(0)) for m in _AADHAAR.finditer(text)}
        hits = {h for h in hits if verhoeff_ok(h)}
    elif type_id in _LAST4:
        hits = {re.sub(r"[ \-]", "", m.group(0)) for m in _LAST4[type_id].finditer(text)}
    else:
        return None
    return next(iter(hits))[-4:] if len(hits) == 1 else None


def guess_type(text: str) -> str | None:
    for pattern, type_id in _TYPE_PHRASES:
        if pattern.search(text):
            return type_id
    return None


def propose(text: str, type_hint: str | None = None) -> Proposal:
    """What a PDF's text suggests. `type_hint` (the owner's choice) wins over the guess."""
    clean = "".join(ch if ch == "\n" or ch >= " " else " " for ch in str(text or ""))
    guessed = None if type_hint in TYPES else guess_type(clean)
    type_id = type_hint if type_hint in TYPES else guessed
    if type_id is None:
        return Proposal()
    expiry = _dates_for(clean, EXPIRY.get(type_id, GENERIC_EXPIRY))
    issue = _dates_for(clean, (ISSUE,))
    issued_on, issued_label = (issue[0], issue[1]) if issue else (None, None)
    expires_on, expires_label = (expiry[0], expiry[1]) if expiry else (None, None)
    if expiry is None and type_id in (
        "vehicle_insurance",
        "health_insurance",
        "life_insurance",
        "other_insurance",
    ):
        span = _period(clean)
        if span is not None:
            issued_on, issued_label = span[0], "Period of Insurance"
            expires_on, expires_label = span[1], "Period of Insurance"
    return Proposal(
        type=guessed,
        issued_on=issued_on,
        issued_label=issued_label,
        expires_on=expires_on,
        expires_label=expires_label,
        last4=_last4(clean, type_id),
    )


__all__ = ["guess_type", "parse_date", "propose", "verhoeff_ok"]
