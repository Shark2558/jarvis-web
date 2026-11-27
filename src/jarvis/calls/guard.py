# src/jarvis/calls/guard.py
"""The in-call reply guard (R18 A2; docs/plans/r18-calls.md 4.6 and 8; Layer 4 guardrails).

Runs in code on EVERY line JARVIS is about to say in a call, after the brain and before the voice,
and on every key sequence before it is played. A refusal never speaks the refused text: the engine
says the fixed "I will check with <first name> and call back" line instead.

Refused:
- a digit string of 4 or more digits (OTP-, card-, bank-account-, Aadhaar-shaped) unless that
  exact value is on the card, or the other person said it earlier in this call and it is at most
  11 digits long (a booking number or a call-back number repeated back to confirm; they already
  know it). 12 digits and longer (Aadhaar, card, account) are never repeated back.
  Digits are read in any script (Unicode decimal digits), and number words in English, romanised
  Hindi and the main Indian scripts are read as digits ("four eight two nine", "चार आठ"). Groups
  separated by spaces, hyphens or dots join into one string ("98765 43210" is one number); a
  colon or slash separates (10:30, 28/11).
- PAN-shaped (ABCDE1234F) and IFSC-shaped (SBIN0001234) strings, e-mail or UPI handles and web
  links, unless that exact value is on the card.
- agreeing to pay: "<someone> will / can / shall pay | transfer | deposit | send the money", or an
  agreement word with a payment word in the same sentence with no negation in it.
- an empty line.

The number words are best effort; digits are the primary signal and the brain is told to write
every number as digits. Both the line in the call's language and the brain's English rendering of
it are checked. A verdict carries reason codes only, never the text (it is logged and audited).
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass, field

MIN_SECRET_DIGITS = 4  # 4-8 digits: an OTP or a PIN; longer: account, card, Aadhaar
MAX_ECHO_DIGITS = 11  # a phone number with its leading 0: the longest value heard that is echoed
MAX_DTMF_KEYS = 20

Reason = str  # "digits" | "pan" | "ifsc" | "handle" | "link" | "payment" | "empty" | "keys"


@dataclass(frozen=True)
class Verdict:
    ok: bool
    reasons: tuple[Reason, ...] = ()


@dataclass(frozen=True, repr=False)
class GuardContext:
    """What a call may say: the card's values (`card_values`), the short values the other person
    said in this call (`heard_values`), and the owner's first name (for the payment rule)."""

    card: frozenset[str]
    heard: frozenset[str] = field(default_factory=frozenset)
    first_name: str = ""

    def __repr__(self) -> str:
        return f"GuardContext(card={len(self.card)}, heard={len(self.heard)})"


OK = Verdict(True)

# ---- number words ------------------------------------------------------------------------------

_UNITS: dict[str, str] = {
    # English
    "zero": "0", "one": "1", "two": "2", "three": "3", "four": "4", "five": "5", "six": "6",
    "seven": "7", "eight": "8", "nine": "9",
    # romanised Hindi
    "shunya": "0", "shoonya": "0", "sunya": "0", "ek": "1", "do": "2", "teen": "3", "char": "4",
    "chaar": "4", "paanch": "5", "panch": "5", "chhe": "6", "chhah": "6", "chah": "6", "saat": "7",
    "aath": "8", "nau": "9",
    # Hindi and Marathi (Devanagari)
    "शून्य": "0", "एक": "1", "दो": "2", "दोन": "2", "तीन": "3", "चार": "4", "पांच": "5",
    "पाँच": "5", "पाच": "5", "छह": "6", "छः": "6", "छे": "6", "सहा": "6", "सात": "7", "आठ": "8",
    "नौ": "9", "नऊ": "9",
    # Bengali
    "শূন্য": "0", "এক": "1", "দুই": "2", "তিন": "3", "চার": "4", "পাঁচ": "5", "ছয়": "6",
    "সাত": "7", "আট": "8", "নয়": "9",
    # Gujarati
    "શૂન્ય": "0", "એક": "1", "બે": "2", "ત્રણ": "3", "ચાર": "4", "પાંચ": "5", "છ": "6",
    "સાત": "7", "આઠ": "8", "નવ": "9",
    # Malayalam
    "പൂജ്യം": "0", "ഒന്ന്": "1", "ഒന്നു": "1", "രണ്ട്": "2", "രണ്ടു": "2", "മൂന്ന്": "3",
    "മൂന്നു": "3", "നാല്": "4", "നാലു": "4", "അഞ്ച്": "5", "അഞ്ചു": "5", "ആറ്": "6", "ആറു": "6",
    "ഏഴ്": "7", "ഏഴു": "7", "എട്ട്": "8", "എട്ടു": "8", "ഒമ്പത്": "9", "ഒൻപത്": "9",
    # Tamil
    "பூஜ்யம்": "0", "சுழியம்": "0", "ஒன்று": "1", "இரண்டு": "2", "மூன்று": "3", "நான்கு": "4",
    "ஐந்து": "5", "ஆறு": "6", "ஏழு": "7", "எட்டு": "8", "ஒன்பது": "9",
    # Telugu
    "సున్నా": "0", "ఒకటి": "1", "రెండు": "2", "మూడు": "3", "నాలుగు": "4", "ఐదు": "5",
    "ఆరు": "6", "ఏడు": "7", "ఎనిమిది": "8", "తొమ్మిది": "9",
    # Kannada
    "ಸೊನ್ನೆ": "0", "ಒಂದು": "1", "ಎರಡು": "2", "ಮೂರು": "3", "ನಾಲ್ಕು": "4", "ಐದು": "5",
    "ಆರು": "6", "ಏಳು": "7", "ಎಂಟು": "8", "ಒಂಬತ್ತು": "9",
}  # fmt: skip
_TEENS: dict[str, str] = {
    "ten": "10", "eleven": "11", "twelve": "12", "thirteen": "13", "fourteen": "14",
    "fifteen": "15", "sixteen": "16", "seventeen": "17", "eighteen": "18", "nineteen": "19",
}  # fmt: skip
_TENS: dict[str, str] = {
    "twenty": "2", "thirty": "3", "forty": "4", "fourty": "4", "fifty": "5", "sixty": "6",
    "seventy": "7", "eighty": "8", "ninety": "9",
}  # fmt: skip
_ZEROS: dict[str, str] = {"hundred": "00", "thousand": "000", "lakh": "00000", "lac": "00000"}
_TIMES: dict[str, int] = {"double": 2, "triple": 3}
_UNITS_N = {unicodedata.normalize("NFC", k): v for k, v in _UNITS.items()}

# ---- tokens ------------------------------------------------------------------------------------

# A word: letters, or any character of the Indian scripts (U+0900..U+0DFF, their vowel signs
# included) except the danda and double danda; ZWJ/ZWNJ stay inside a word.
_WORD = r"(?:[^\W\d_]|[ऀ-ॣ०-෿‌‍])+(?:'(?:[^\W\d_])+)?"
_TOKEN = re.compile(rf"\s+|\d+|{_WORD}|.", re.UNICODE)
_SOFT_ALWAYS = frozenset({"-"})
_SOFT_BETWEEN_DIGITS = frozenset({".", ","})


def _normalise(text: str) -> str:
    """NFKC, every decimal digit of any script as ASCII, curly apostrophes straight."""
    out: list[str] = []
    for ch in unicodedata.normalize("NFKC", str(text or "")):
        value = unicodedata.decimal(ch, None)
        out.append(str(value) if value is not None and not ch.isascii() else ch)
    return unicodedata.normalize("NFC", "".join(out).replace("’", "'"))


@dataclass
class _Run:
    groups: list[str] = field(default_factory=list)
    tens: str | None = None  # a pending "forty" waiting for its unit
    times: int = 1  # "double nine"

    def add(self, piece: str) -> None:
        if self.tens is not None and len(piece) == 1:
            piece, self.tens = self.tens + piece, None  # "forty" + "eight"
        self.flush()
        self.groups.append(piece * self.times if len(piece) == 1 else piece)
        self.times = 1

    def tens_word(self, digit: str) -> None:
        self.flush()
        self.tens = digit

    def zeros(self, zeros: str) -> None:
        self.flush()
        if self.groups:
            self.groups[-1] = self.groups[-1] + zeros

    def flush(self) -> None:
        if self.tens is not None:
            self.groups.append(self.tens + "0")
            self.tens = None

    @property
    def digits(self) -> str:
        return "".join(self.groups)


def _runs(text: str) -> list[_Run]:
    tokens = [m.group(0) for m in _TOKEN.finditer(_normalise(text))]
    runs: list[_Run] = []
    current = _Run()

    def close() -> None:
        nonlocal current
        current.flush()
        if current.groups:
            runs.append(current)
        current = _Run()

    for i, tok in enumerate(tokens):
        word = tok.lower()
        nxt = tokens[i + 1] if i + 1 < len(tokens) else ""
        if tok.isdigit():
            current.add(tok)
        elif word in _UNITS_N:
            current.add(_UNITS_N[word])
        elif word in _TEENS:
            current.flush()
            current.add(_TEENS[word])
        elif word in _TENS:
            current.tens_word(_TENS[word])
        elif word in _ZEROS and (current.groups or current.tens):
            current.zeros(_ZEROS[word])
        elif word in _TIMES:
            current.flush()
            current.times = _TIMES[word]
        elif word == "oh" and (current.groups or current.tens):
            current.add("0")
        elif tok.isspace() or tok in _SOFT_ALWAYS:
            continue
        elif tok in _SOFT_BETWEEN_DIGITS and nxt.isdigit():
            continue
        else:
            close()
    close()
    return runs


def digit_runs(text: str) -> list[str]:
    """Every number in `text` as one digit string per run of joined groups (see the module)."""
    return [r.digits for r in _runs(text)]


def _canonical(run: str) -> str:
    """An Indian phone number with or without its country code or trunk 0 is the same value."""
    if len(run) == 12 and run.startswith("91"):
        return run[2:]
    if len(run) == 11 and run.startswith("0"):
        return run[1:]
    return run


# ---- other shapes ------------------------------------------------------------------------------

_PAN = re.compile(r"(?<![a-z0-9])[a-z]{5}\s?[0-9]{4}\s?[a-z](?![a-z0-9])", re.IGNORECASE)
_IFSC = re.compile(r"(?<![a-z0-9])[a-z]{4}0[a-z0-9]{6}(?![a-z0-9])", re.IGNORECASE)
_HANDLE = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)*", re.UNICODE)
_LINK = re.compile(
    r"\bhttps?://\S+|\bwww\.\S+|\b[\w-]+\.(?:com|in|net|org|co|io|me|ly|link|app)\b(?:/\S*)?",
    re.IGNORECASE,
)
_SHAPES: tuple[tuple[Reason, re.Pattern[str]], ...] = (
    ("pan", _PAN),
    ("ifsc", _IFSC),
    ("handle", _HANDLE),
    ("link", _LINK),
)


def _shape_key(kind: Reason, value: str) -> str:
    return f"{kind}:" + re.sub(r"\s+", "", value).lower().rstrip(".")


def _shapes(text: str) -> list[tuple[Reason, str]]:
    norm = _normalise(text)
    return [(kind, _shape_key(kind, m.group(0))) for kind, rx in _SHAPES for m in rx.finditer(norm)]


def card_values(texts: Iterable[str]) -> frozenset[str]:
    """Every value the card allows JARVIS to say: each number (whole and by its groups, with
    and without a country code) and each PAN / IFSC / handle / link written on it."""
    out: set[str] = set()
    for text in texts:
        for run in _runs(text):
            out.add(run.digits)
            out.add(_canonical(run.digits))
            out.update(run.groups)
        out.update(key for _, key in _shapes(text))
    return frozenset(out)


def heard_values(utterances: Iterable[str]) -> frozenset[str]:
    """The numbers the other person said that may be repeated back: at most 11 digits."""
    out: set[str] = set()
    for text in utterances:
        for run in _runs(text):
            if len(run.digits) <= MAX_ECHO_DIGITS:
                out.add(_canonical(run.digits))
                out.update(g for g in run.groups if len(g) <= MAX_ECHO_DIGITS)
    return frozenset(out)


# ---- payments ----------------------------------------------------------------------------------

_MODAL = (
    r"(?:\s+(?:will|shall|can|could|would|is going to|are going to|am going to|agrees? to|"
    r"is happy to|are happy to|is ready to|are ready to)|'ll)"
)
_PAY_VERB = (
    r"(?:pay|transfer|deposit|send\s+(?:you\s+|it\s+)?(?:the\s+|a\s+)?"
    r"(?:money|amount|payment|advance|deposit|cash|fee|fees|rupees))"
)
_PAY_WORD = re.compile(
    r"\b(?:pay|paid|paying|payment|payments|transfer|deposit|advance|upi|gpay|paytm|phonepe)\b"
)
_AGREE_WORD = re.compile(
    r"\b(?:ok|okay|fine|agree|agreed|sure|yes|alright|deal|done|accepted|no problem)\b"
)
_NEGATION = re.compile(
    r"\b(?:no|not|never|cannot|can't|won't|don't|doesn't|unable|without|nothing)\b"
)
_PASSIVE = re.compile(r"\b(?:payment|amount|advance|money)\s+will\s+be\s+(?:made|paid|sent)\b")
_SENTENCE = re.compile(r"[.!?;।\n]+")


def _commits(sentence: str, first_name: str) -> bool:
    subjects = ["i", "we", "he", "she", "they", "sir", "madam"]
    name = re.escape(first_name.strip().lower()) if first_name.strip() else ""
    if name:
        subjects.append(name)
    rx = rf"\b(?:{'|'.join(subjects)}){_MODAL}\s+{_PAY_VERB}\b"
    return re.search(rx, sentence) is not None


def _agrees_to_pay(text: str, first_name: str) -> bool:
    for raw in _SENTENCE.split(_normalise(text).lower()):
        sentence = raw.strip()
        if not sentence:
            continue
        if _commits(sentence, first_name):
            return True
        if _NEGATION.search(sentence):
            continue
        if _PASSIVE.search(sentence):
            return True
        if _PAY_WORD.search(sentence) and _AGREE_WORD.search(sentence):
            return True
    return False


# ---- the checks --------------------------------------------------------------------------------


def _allowed_run(run: str, ctx: GuardContext) -> bool:
    if len(run) < MIN_SECRET_DIGITS:
        return True
    canon = _canonical(run)
    if run in ctx.card or canon in ctx.card:
        return True
    return len(run) <= MAX_ECHO_DIGITS and (run in ctx.heard or canon in ctx.heard)


def _reasons(text: str, ctx: GuardContext) -> list[Reason]:
    found: list[Reason] = []
    if any(not _allowed_run(r, ctx) for r in digit_runs(text)):
        found.append("digits")
    for kind, key in _shapes(text):
        if key not in ctx.card and kind not in found:
            found.append(kind)
    if _agrees_to_pay(text, ctx.first_name):
        found.append("payment")
    return found


def check_reply(say: str, english: str, ctx: GuardContext) -> Verdict:
    """May JARVIS say `say` (its English rendering `english`) in this call?"""
    if not str(say or "").strip():
        return Verdict(False, ("empty",))
    reasons: list[Reason] = []
    for text in (say, english):
        for reason in _reasons(text, ctx):
            if reason not in reasons:
                reasons.append(reason)
    return Verdict(not reasons, tuple(reasons))


_KEYS = re.compile(rf"[0-9*#]{{1,{MAX_DTMF_KEYS}}}")


def check_dtmf(keys: str, ctx: GuardContext) -> Verdict:
    """May JARVIS press `keys` (a phone menu)? Only 0-9, * and #; a number of 4 or more digits
    only when it is on the card (or was said by the other person, as for a reply)."""
    if not isinstance(keys, str) or _KEYS.fullmatch(keys) is None:
        return Verdict(False, ("keys",))
    for run in re.findall(r"[0-9]+", keys):
        if not _allowed_run(run, ctx):
            return Verdict(False, ("digits",))
    return OK


__all__ = [
    "MAX_DTMF_KEYS",
    "MAX_ECHO_DIGITS",
    "MIN_SECRET_DIGITS",
    "GuardContext",
    "Verdict",
    "card_values",
    "check_dtmf",
    "check_reply",
    "digit_runs",
    "heard_values",
]
