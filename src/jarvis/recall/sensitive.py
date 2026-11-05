# src/jarvis/recall/sensitive.py
"""The deterministic sensitive-data filter (slice 8 D9). Every write path — learned, tool, API,
import, profile — runs `sensitive_reason` and refuses what it flags; nothing here calls a model.

Flagged: card numbers (13–19 digits passing Luhn), Aadhaar (12 digits, 4-4-4 or bare, or the
word with digits), PAN (`AAAAA9999A`), IFSC / IBAN-like codes, bank account numbers (an account
word with 9–18 digits), passport / voter / licence numbers, passwords / passphrases / OTPs /
CVVs / PINs stated with a value ("is", "are", ":", "for X is"), and access keys (sk-…, AKIA…,
ghp_…, JWTs). Digit groups may be split by any separators; combining marks, variation
selectors, zero-width characters and Cyrillic / Greek look-alike letters do not hide anything.
Postal PIN codes are not secrets. The reason names the kind of data, never the value.

`special_category` is a second, coarser check applied to LEARNED facts only (the extraction
prompt already excludes these): health, religion, caste, politics, sexuality. A fact the owner
explicitly tells or adds is their choice; one a model inferred is dropped.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Callable

SEP = r"[\W_]{0,3}"  # any separator between digit groups: " ", "-", "/", ",", "_", "–", …
_NOT_A_VALUE = r"(?!(?:in|on|at|stored|kept|saved|managed|written|under|inside|with|the\s+same)\b)"
_VERB = r"(?:is|are|was|were|=|:|-)"
_CARD_RUN = re.compile(rf"(?<![\w+])\d(?:{SEP}\d){{12,18}}(?!\w)")
_AADHAAR = re.compile(rf"(?<![\w+])[2-9]\d{{3}}{SEP}\d{{4}}{SEP}\d{{4}}(?!\w)")
_AADHAAR_WORD = re.compile(r"(?i)\baadh?aa?r\b.{0,120}\d{4}")
_PAN = re.compile(r"(?<![A-Za-z0-9])[A-Za-z]{5}\d{4}[A-Za-z](?![A-Za-z0-9])")
_PAN_SPACED = re.compile(rf"(?<![A-Za-z0-9])[A-Z]{{5}}{SEP}\d{{4}}{SEP}[A-Z](?![A-Za-z0-9])")
_PAN_WORD = re.compile(
    rf"(?i)\bpan\b.{{0,120}}(?<![A-Za-z0-9])[A-Za-z]{{5}}{SEP}\d{{4}}{SEP}[A-Za-z](?![A-Za-z0-9])"
)
_IFSC = re.compile(r"(?<![A-Za-z0-9])[A-Z]{4}0[A-Z0-9]{6}(?![A-Za-z0-9])")
_IFSC_WORD = re.compile(
    r"(?i)\bifsc\b.{0,120}(?<![A-Za-z0-9])[A-Za-z]{4}0[A-Za-z0-9]{6}(?![A-Za-z0-9])"
)
_IBAN = re.compile(r"(?<![A-Za-z0-9])[A-Z]{2}\d{2}(?: ?[A-Z0-9]){11,30}(?![A-Za-z0-9])")
_IBAN_WORD = re.compile(r"(?i)\biban\b")
_ACCOUNT_WORD = re.compile(
    r"(?i)(?:\baccount\b|\bacct\b|\bacc\b|\bac\.?\s*(?:no|number|num)\b|\ba/c\b|\bbank\b"
    r"|\bsavings\b)"
)
_LONG_NUMBER = re.compile(rf"(?<![\w+])\d(?:{SEP}\d){{8,17}}(?!\w)")
_ID_WORD = re.compile(
    r"(?i)\b(?:passport|voter\s*id|epic\s*(?:no|number)|driving\s*licen[cs]e|dl\s*(?:no|number)"
    r"|licen[cs]e\s*(?:no|number))\b"
)
_ID_VALUE = re.compile(r"(?<![A-Za-z0-9])[A-Za-z]{0,4}\d{6,16}(?![A-Za-z0-9])")
_SECRET_WORD = (
    r"(?:passwords?|passcodes?|passwd|passphrases?|pwd|pw|otps?|one[- ]time\s+(?:password|code)s?"
    r"|cvv|cvc|security\s+codes?|api\s+keys?|secret\s+keys?|private\s+keys?|access\s+tokens?"
    r"|seed\s+phrases?|recovery\s+phrases?|wi-?fi\s+key)"
)
_SECRET_STATED = re.compile(rf"(?i)\b{_SECRET_WORD}\b\s*{_VERB}\s*{_NOT_A_VALUE}\S")
_SECRET_FOR = re.compile(
    rf"(?i)\b{_SECRET_WORD}\s+(?:for|of|to|on)\s+[^.;!?]{{1,60}}?\s{_VERB}\s*{_NOT_A_VALUE}\S"
)
_SECRET_VALUE = re.compile(rf"(?i)\b{_SECRET_WORD}\b\s*(?:no\.?|number|code)?\s*[\w@#$%&*!-]*\d")
_PASS_COLON = re.compile(r"(?i)\bpass\s*[:=]\s*\S")
_PIN = re.compile(
    r"(?i)\b(?:upi\s+|atm\s+|debit\s+card\s+|card\s+|my\s+)?pin\b(?!\s*-?\s*codes?\b)"
    r"\s*(?:no\.?|number)?\s*(?:is|was|=|:|-)?\s*\d{4,6}(?!\d)"
)
_PIN_FOR = re.compile(
    r"(?i)\bpin\s+(?:for|of|to|on)\s+[^.;!?]{1,40}?\s*(?:is|was|=|:|-)?\s*\d{4,6}(?!\d)"
)
_ACCESS_KEY = re.compile(
    r"(?:\bsk-[A-Za-z0-9_-]{16,}|(?i:\bAKIA[0-9A-Z]{16}\b)|\bgh[pousr]_[A-Za-z0-9]{30,}"
    r"|\bxox[abprs]-[A-Za-z0-9-]{10,}|(?i:\bAIza)[0-9A-Za-z_-]{30,}"
    r"|\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}|(?i:\bbearer\s+)[A-Za-z0-9._~+/-]{20,})"
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


# Cyrillic and Greek letters that look like Latin ones ("РАN", "pаssword"): read as Latin.
_CONFUSABLES = str.maketrans(
    "АВСЕНІЈКМОРЅТХУҮԚԜӀасеіјорѕхуԁһԛԝӏΑΒΕΖΗΙΚΜΝΟΡΤΥΧονικρχαυϲϳ",
    "ABCEHIJKMOPSTXYYQWIaceijopsxydhqwlABEZHIKMNOPTYXovikpxaucj",
)


def _normal(text: str) -> str:
    """The text as the patterns read it: NFKD (fullwidth digits → ASCII, accents split off);
    combining marks, variation selectors and invisible format characters dropped (so
    "4111<ZWSP>1111" or "4111\u0301" reads as one number); look-alike Cyrillic / Greek letters
    folded to Latin; line breaks, tabs and other controls become spaces (a separator, so
    "a/c no<newline>5010…" still reads as an account word next to a number)."""
    out = []
    for ch in unicodedata.normalize("NFKD", str(text or "")):
        cat = unicodedata.category(ch)
        if cat in ("Cc", "Zl", "Zp", "Zs"):
            out.append(" ")
        elif cat not in ("Cf", "Mn", "Me", "Mc", "Co", "Cn"):
            out.append(ch)
    return " ".join("".join(out).translate(_CONFUSABLES).split())


def _any(*patterns: re.Pattern[str]) -> Callable[[str], bool]:
    return lambda t: any(p.search(t) for p in patterns)


_CHECKS: tuple[tuple[str, Callable[[str], bool]], ...] = (
    ("a card number", _has_card),
    ("an Aadhaar number", _any(_AADHAAR, _AADHAAR_WORD)),
    ("a PAN", _any(_PAN, _PAN_SPACED, _PAN_WORD)),
    ("a bank IFSC code", _any(_IFSC, _IFSC_WORD)),
    ("an IBAN", _any(_IBAN, _IBAN_WORD)),
    ("a bank account number", _has_account),
    ("an ID document number", lambda t: bool(_ID_WORD.search(t) and _ID_VALUE.search(t))),
    ("an access key", _any(_ACCESS_KEY)),
    (
        "a password, OTP or security code",
        _any(_SECRET_STATED, _SECRET_FOR, _SECRET_VALUE, _PASS_COLON),
    ),
    ("a PIN", _any(_PIN, _PIN_FOR)),
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


# ---- text that will be READ ALOUD (R1 D16) ----------------------------------------------------
# JARVIS never classifies its way to safety here: what it SPEAKS from mail is MASKED
# (`jarvis.tools.spoken.mask_for_speech`). This function is the extra layer on top: a whole mail
# that looks like a code or a bank message is not read at all. A wrongly withheld mail costs one
# "open it on screen"; a code or a balance read to a room costs more. Input is capped, every
# pattern is linear or bounded, and nothing here calls a model.
SPOKEN_MAX_CHARS = 1_000
_DIGIT_TO_LETTER = str.maketrans("01345", "oleas")  # 0->o 1->l 3->e 4->a 5->s
_ONE_AS_I = str.maketrans("1", "i")
_TOKEN = re.compile(r"[A-Za-z0-9]+")
_SPACED = re.compile(r"(?<![A-Za-z0-9])[A-Za-z0-9](?:[ .\-_][A-Za-z0-9]){2,9}(?![A-Za-z0-9])")
# ONE definition of "digits that belong together" for everything that is spoken: 1 to 3 characters
# that are neither letters nor digits (space, dash, dot, middle dot, pipe, star, underscore ...)
# between digit groups are a joiner. `tools.spoken` masks with the same run pattern.
JOINER = r"[\W_]{1,3}"
DIGIT_RUN = re.compile(rf"\d(?:{JOINER}\d|\d)*")
_DIGIT_GAP = re.compile(rf"(?<=\d){JOINER}(?=\d)")
_RUN = re.compile(r"\d+")
# Spelled-out digits (English, Hindi, Malayalam in Latin letters): 3 or more in a row are a code.
_ENGLISH = "zero one two three four five six seven eight nine".split()
_HINDI = "shunya shoonya ek do teen char chaar paanch panch chhe chhah saat aath nau".split()
_MALAYALAM = "poojyam onnu randu moonnu naalu anchu aaru ezhu ettu ombathu".split()
DIGIT_WORDS: dict[str, str] = {
    **{w: str(i) for i, w in enumerate(_ENGLISH)},
    **dict(zip(_HINDI, "00123445566789", strict=True)),
    **{w: str(i) for i, w in enumerate(_MALAYALAM)},
}
_DW = "|".join(sorted(DIGIT_WORDS, key=len, reverse=True))
DIGIT_WORD_RUN = re.compile(rf"\b(?:{_DW})\b(?:[\s,.\-]{{1,3}}(?:{_DW})\b){{2,}}", re.IGNORECASE)
_SPOKEN_SECRET_WORD = re.compile(
    r"\b(?:otps?|one[- ]?time|log[- ]?in|sign[- ]?in|verif\w{0,12}|pins?|passwords?|passcodes?"
    r"|cvv|cvc|code|auth\w{0,12}|secret)\b",
    re.IGNORECASE,
)
_SPOKEN_ALWAYS = re.compile(
    r"\b(?:otps?|one[- ]?time\s{0,3}(?:password|code|pin)|passcode|cvv|cvc"
    r"|bal|balance|avl|txns?|transactions?|spent|debited|credited|statement|a/c|acct|emi"
    r"|account\s{0,3}(?:no|number|ending|balance|statement)|card\s{0,3}(?:ending|no|number)|khate|khata|jama"
    r"|upi|vpa|ifsc|neft|imps|rtgs|secret\s{0,3}(?:number|code|pin|key)"
    r"|(?:login|log[- ]?in|sign[- ]?in|reset|verification)\s{0,3}link"
    r"|(?:debit|credit)\s{0,3}hua)\b",
    re.IGNORECASE,
)
_CARD_X = re.compile(r"\bcard\s{0,3}[x*]{1,8}\s{0,2}\d", re.IGNORECASE)
_UPI_HANDLE = re.compile(r"[\w.\-]{2,30}@[a-z]{2,20}\b(?!\.\w)", re.IGNORECASE)
_INDIC_WORDS = (
    "ओटीपी", "कोड", "बैलेंस", "खाता", "खाते", "पासवर्ड", "पिन", "जमा", "रुपये",  # Hindi
    "ഒടിപി", "കോഡ്", "ബാലൻസ്", "അക്കൗണ്ട്", "പാസ്\u200dവേഡ്", "പിൻ",  # Malayalam
)  # fmt: skip


def speech_normal(text: object, cap: int = SPOKEN_MAX_CHARS) -> str:
    """The text as a listener's risk sees it: capped, NFKC (fullwidth to ASCII), every script's
    decimal digits turned into 0-9, zero-width and format characters dropped, whitespace and
    controls as one space, look-alike Cyrillic / Greek letters as Latin."""
    out = []
    for ch in unicodedata.normalize("NFKC", str(text or "")[:cap]):
        cat = unicodedata.category(ch)
        if cat == "Nd":
            out.append(str(unicodedata.decimal(ch, 0)))
        elif cat in ("Cf", "Co", "Cn"):
            continue
        elif cat in ("Cc", "Zl", "Zp", "Zs"):
            out.append(" ")
        else:
            out.append(ch)
    return " ".join("".join(out).translate(_CONFUSABLES).split())


def _fold_letters(t: str, table: dict[int, int]) -> str:
    """0TP -> oTP: in a token that has letters in it, digits that look like letters become them."""
    return _TOKEN.sub(
        lambda m: (
            m.group(0).translate(table) if any(c.isalpha() for c in m.group(0)) else m.group(0)
        ),
        t,
    )


def _word_views(t: str) -> list[str]:
    """The text, with spaced / dotted letters closed up (O T P, O.T.P) and look-alike digits
    read as letters, in the two common ways (1 as l, 1 as i)."""
    closed = _SPACED.sub(lambda m: re.sub(r"[ .\-_]", "", m.group(0)), t)
    return [t, closed, _fold_letters(closed, _DIGIT_TO_LETTER), _fold_letters(closed, _ONE_AS_I)]


def join_digits(text: str) -> str:
    """`text` with every joiner between digit groups removed: "12|34 - 56" -> "123456"."""
    return _DIGIT_GAP.sub("", text)


def _digits_of_words(run: re.Match[str]) -> str:
    return "".join(DIGIT_WORDS[w.lower()] for w in re.findall(r"[A-Za-z]+", run.group(0)))


def spoken_sensitive(text: object) -> bool:
    """True when `text` must not be read aloud at all: an OTP / code / login / PIN / password /
    secret word beside a number, a money, balance, EMI, card, account or UPI word or handle, the
    same in Hindi or Malayalam, a "login link", a 6 or 8 digit code (digits may be spaced, dotted
    or split), 12+ digits, or anything the write-path filter would refuse. Letters may be spaced
    (O T P), dotted (O.T.P), fullwidth, or digits standing for letters (0TP)."""
    t = speech_normal(text)
    if not t:
        return False
    t = DIGIT_WORD_RUN.sub(lambda m: f" {_digits_of_words(m)} ", t)
    joined = join_digits(t)
    runs = [len(r) for r in _RUN.findall(joined)]
    if any(n in (6, 8) or n >= 12 for n in runs):
        return True
    views = _word_views(t)
    if any(_SPOKEN_ALWAYS.search(v) for v in views) or _UPI_HANDLE.search(t) or _CARD_X.search(t):
        return True
    if any(w in t for w in _INDIC_WORDS):
        return True
    if sum(runs) >= 4 and any(_SPOKEN_SECRET_WORD.search(v) for v in views):
        return True
    return sensitive_reason(joined) is not None


__all__ = [
    "DIGIT_RUN",
    "DIGIT_WORD_RUN",
    "is_sensitive",
    "join_digits",
    "sensitive_reason",
    "special_category",
    "speech_normal",
    "spoken_sensitive",
]
