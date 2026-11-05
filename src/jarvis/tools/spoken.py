# src/jarvis/tools/spoken.py
"""Masking for anything JARVIS SPEAKS (or sends to a phone) from mail (R1 D16 review redesign).

A denylist of "sensitive" words can never win, so what reaches a speaker is MASKED instead of
classified: links become "a link", addresses (e-mail, UPI handle) "an address", money amounts
"an amount", and any number of four or more digits "a number" -- digits in any script, split by
1-3 non-letter characters (spaces, dots, dashes, pipes, stars ...), with zero-width characters
inside, fullwidth or not; runs of 3+ spelled-out digits (English, Hindi, Malayalam) are "a number",
number words beside a currency word are "an amount", street addresses and bare domains "a link".
Short numbers and clock times (10:30, 5 Nov) are kept; but when more than eight digits remain in
the text (a code read in two goes) every number is masked. `recall.sensitive.spoken_sensitive`
sits on top as a second layer that withholds a whole mail.

The console on the owner's own screen is NOT masked; `speaking_now()` says when to mask: a voice
turn, or a Telegram turn (the words go to a phone, to be read in public). The brief on screen keeps
its text (its Deliveries item is run through the withhold check first); nothing speaks the brief.
"""

from __future__ import annotations

import re

from jarvis.core.channel import on_telegram
from jarvis.recall.sensitive import DIGIT_RUN, DIGIT_WORD_RUN, speech_normal, spoken_sensitive
from jarvis.tools.taint import spoken_in_context

MASK_CAP = 20_000
LINK = "a link"
ADDRESS = "an address"
AMOUNT = "an amount"
NUMBER = "a number"
MAX_KEPT_DIGITS = 8
WITHHELD_LINE = "withheld - open it on screen"

_URL = re.compile(
    r"(?:https?://|www\.)\S{0,500}|\b[\w\-]{1,60}(?:\.[\w\-]{1,60}){1,5}/\S{0,500}", re.IGNORECASE
)
_ADDRESS = re.compile(r"[\w.+\-]{1,64}@[\w.\-]{1,100}")
_NUM = r"\d(?:[\d,. ]{0,18}\d)?"
_UNIT = r"(?:lakhs?|lacs?|crores?|cr|k|million|thousand)"
_AMOUNT = re.compile(
    rf"(?:₹|\brs\b\.?|\binr\b|रु\.?|\brupees?\b)\s{{0,2}}(?:{_NUM}(?:\s{{0,2}}{_UNIT}\b)?)?"
    rf"|{_NUM}\s{{0,2}}(?:rupees?\b|rs\b\.?|inr\b|{_UNIT}\b)"
    r"|\b(?:lakhs?|lacs?|crores?)\b|रुपये|रुपया",
    re.IGNORECASE,
)
# A clock time (10:30) is kept; any other digit run is measured with the shared joiner rule
# (`recall.sensitive.DIGIT_RUN`: 1-3 non-letter, non-digit characters between groups).
_RUN = re.compile(rf"(?<!\d)\d{{1,2}}:\d{{2}}(?![:\d])|{DIGIT_RUN.pattern}")
_CLOCK = re.compile(r"\d{1,2}:\d{2}")
_DIGITS = re.compile(r"\d+")
_CUR = r"(?:rupees?|rupaye|rupaya|rs\.?|inr|\u20b9|lakhs?|lacs?|crores?)"
_NUMW = (
    r"(?:zero|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|thirteen|fourteen"
    r"|fifteen|sixteen|seventeen|eighteen|nineteen|twenty|thirty|forty|fifty|sixty|seventy"
    r"|eighty|ninety|hundred|thousand|million|lakhs?|lacs?|crores?|hazaar|hazar|sau|ek|do|teen"
    r"|char|paanch|chhe|saat|aath|nau)"
)
# optional currency word before / after a run of number words; the run itself is matched once,
# left to right, so hostile input cannot make the scan quadratic
_WORD_AMOUNT = re.compile(
    rf"(?:\b(?P<pre>{_CUR})\s{{0,2}})?\b(?P<run>{_NUMW}(?:[\s\-]{{1,3}}(?:and\s{{1,3}})?{_NUMW})*)\b"
    rf"(?:\s{{0,2}}(?P<post>{_CUR}))?",
    re.IGNORECASE,
)
_BIG = re.compile(r"lakh|lac|crore", re.IGNORECASE)
_STREET = re.compile(
    r"\b(?:flat|house|door|plot|no)\b\.?\s{0,2}#?\s{0,2}\d[\w/\-]{0,6}[^.;\n]{0,50}"
    r"\b(?:road|rd|street|st|nagar|lane|marg|colony|layout|cross|main)\b\.?",
    re.IGNORECASE,
)
_TLDS = (
    "com|net|org|in|io|co|info|biz|app|dev|xyz|online|site|shop|store|tech|me|us|uk|edu|gov|ai"
    "|live|link|click|top|icu|test|club|vip|cc|ly|to"
)
_DOMAIN = re.compile(rf"\b(?:[a-z0-9][a-z0-9\-]{{0,60}}\.){{1,5}}(?:{_TLDS})\b", re.IGNORECASE)


def withhold_if_sensitive(text: str) -> str:
    """`text`, or a fixed line when it looks like a code, a bank message or a secret
    (`recall.sensitive.spoken_sensitive`). For text that stays on a screen but must not carry
    someone else's code (the brief's Deliveries item)."""
    return f"({WITHHELD_LINE})" if spoken_sensitive(text) else text


def speaking_now() -> bool:
    """True on a voice turn or a Telegram turn: what the tools return will be heard or read in
    public, so it is masked. False on the text console."""
    return spoken_in_context() or on_telegram()


def _mask_run(m: re.Match[str]) -> str:
    run = m.group(0)
    kept = _CLOCK.fullmatch(run) is not None or len(re.sub(r"\D", "", run)) < 4
    return run if kept else f" {NUMBER} "


def _mask_words(m: re.Match[str]) -> str:
    """Number words beside a currency word (or lakh / crore) are an amount; others stay."""
    if m.group("pre") or m.group("post") or _BIG.search(m.group("run")):
        return f" {AMOUNT} "
    return m.group(0)


def mask_for_speech(text: object, cap: int = MASK_CAP) -> str:
    """`text` as it may be spoken: no link, address, amount or 4+ digit number survives."""
    t = speech_normal(text, cap)
    if not t:
        return ""
    t = DIGIT_WORD_RUN.sub(f" {NUMBER} ", t)
    t = _URL.sub(f" {LINK} ", t)
    t = _ADDRESS.sub(f" {ADDRESS} ", t)
    t = _DOMAIN.sub(f" {LINK} ", t)
    t = _STREET.sub(f" {LINK} ", t)
    t = _WORD_AMOUNT.sub(_mask_words, t)
    t = _AMOUNT.sub(f" {AMOUNT} ", t)
    t = _RUN.sub(_mask_run, t)
    if sum(len(d) for d in _DIGITS.findall(t)) > MAX_KEPT_DIGITS:
        t = _DIGITS.sub(f" {NUMBER} ", t)
    return " ".join(t.split())


__all__ = [
    "ADDRESS",
    "AMOUNT",
    "LINK",
    "NUMBER",
    "WITHHELD_LINE",
    "mask_for_speech",
    "speaking_now",
    "withhold_if_sensitive",
]
