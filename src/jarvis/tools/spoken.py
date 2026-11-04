# src/jarvis/tools/spoken.py
"""Masking for anything JARVIS SPEAKS (or sends to a phone) from mail (R1 D16 review redesign).

A denylist of "sensitive" words can never win, so what reaches a speaker is MASKED instead of
classified: links become "a link", addresses (e-mail, UPI handle) "an address", money amounts
"an amount", and any number of four or more digits "a number" -- digits in any script, split by
spaces, dots, dashes or commas, with zero-width characters inside, fullwidth or not. Short numbers
and clock times (10:30, 5 Nov) are kept; but when more than eight digits remain in the text (a
code read in two goes) every number is masked. `recall.sensitive.spoken_sensitive` sits on top
as a second layer that withholds a whole mail.

The console on the owner's own screen is NOT masked; `speaking_now()` says when to mask: a voice
turn, or a Telegram turn (the words go to a phone, to be read in public). The brief on screen keeps
its text; if the brief is ever spoken it goes through `jarvis.brief.render.spoken_brief_text`.
"""

from __future__ import annotations

import re

from jarvis.core.channel import on_telegram
from jarvis.recall.sensitive import speech_normal
from jarvis.tools.taint import spoken_in_context

MASK_CAP = 20_000
LINK = "a link"
ADDRESS = "an address"
AMOUNT = "an amount"
NUMBER = "a number"
MAX_KEPT_DIGITS = 8

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
_RUN = re.compile(r"\d(?:[ .,\-]{0,2}\d)*")
_DIGITS = re.compile(r"\d+")


def speaking_now() -> bool:
    """True on a voice turn or a Telegram turn: what the tools return will be heard or read in
    public, so it is masked. False on the text console."""
    return spoken_in_context() or on_telegram()


def _mask_run(m: re.Match[str]) -> str:
    kept = len(re.sub(r"\D", "", m.group(0))) < 4
    return m.group(0) if kept else f" {NUMBER} "


def mask_for_speech(text: object, cap: int = MASK_CAP) -> str:
    """`text` as it may be spoken: no link, address, amount or 4+ digit number survives."""
    t = speech_normal(text, cap)
    if not t:
        return ""
    t = _URL.sub(f" {LINK} ", t)
    t = _ADDRESS.sub(f" {ADDRESS} ", t)
    t = _AMOUNT.sub(f" {AMOUNT} ", t)
    t = _RUN.sub(_mask_run, t)
    if sum(len(d) for d in _DIGITS.findall(t)) > MAX_KEPT_DIGITS:
        t = _DIGITS.sub(f" {NUMBER} ", t)
    return " ".join(t.split())


__all__ = ["mask_for_speech", "speaking_now"]
