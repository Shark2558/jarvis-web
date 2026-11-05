# src/jarvis/people/guard.py
"""The scope guard for people research (R4 D10): deterministic, no model call.

JARVIS researches public figures and does work due-diligence from PUBLIC sources. It refuses a
request framed as assembling a private individual's private accounts, home or movements, and it
never face-matches a stranger to an identity. Every check reads the text as `_normal` gives it
(NFKC, invisible characters removed) so a zero-width space cannot split a trigger word.

`GUARD_ENABLED` exists only so the tests can show their negative control: the refusal suite
must fail when it is False.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from enum import StrEnum

from jarvis.tools.card import _is_invisible
from jarvis.web.guard import query_problem

GUARD_ENABLED = True
NAME_MAX = 80
CONTEXT_MAX = 200

PRIVATE_REFUSAL = (
    "I only research public figures and work contacts from public sources, Sir. I won't gather "
    "a private person's home, movements or private accounts."
)
FACE_REFUSAL = (
    "I only research public figures from public sources, Sir, and I never identify a person "
    "from their face."
)
BAD_NAME_REFUSAL = (
    "I need a plain public name to research, Sir, not a number or an address. "
    "I only research public figures."
)


class Scope(StrEnum):
    OK = "ok"
    PRIVATE_INDIVIDUAL = "private_individual"
    FACE_MATCH = "face_match"
    BAD_INPUT = "bad_input"


@dataclass(frozen=True)
class ScopeVerdict:
    allowed: bool
    scope: Scope = Scope.OK
    message: str = ""


_ALLOWED = ScopeVerdict(True)

_PRIVATE = re.compile(
    r"\b(?:home|house|residen\w*|domicile)\s+(?:address|location)\b"
    r"|\bhome\s*add\w*\b"
    r"|\b(?:where|whereabouts)\b[^.]{0,30}\b(?:live|lives|living|stays|staying|goes|is\s+now)\b"
    r"|\bwhereabouts\b|\bmovements?\b|\bdaily\s+(?:routine|movements?|schedule)\b"
    r"|\b(?:track|tracks|tracking|follow|following|trace|monitor|spy|stalk\w*)\b"
    r"|\bprivate\s+(?:accounts?|profiles?|number|email|photos?|life|whatsapp|instagram|facebook"
    r"|snapchat|telegram|twitter|social|dms?|messages?)\b"
    r"|\bpersonal\s+(?:email|phone|number|account|accounts|address)\b"
    r"|\b(?:phone|mobile|cell)\s+number\b|\bpassword\b|\blog-?in\b|\bpasscode\b"
    r"|\bmy\s+(?:ex\b|ex-|neighbou?rs?\b|crush\b|girlfriend\b|boyfriend\b|classmate\b)"
    r"|\bex-?(?:girlfriend|boyfriend|wife|husband)\b|\bneighbou?rs?\b"
    r"|\bdate\s+of\s+birth\b|\bdob\b|\bfind\s+everything\s+about\s+(?:her|him|them)\b"
    r"|\ball\s+(?:her|his|their)\s+(?:accounts|profiles|social)\b"
)
_FACE = re.compile(
    r"\b(?:face|faces|facial|selfie|photo|photograph|picture|image|pic)\b"
    r"|\bwho\s+is\s+(?:this|that)\b|\bidentify\b|\breverse\s+image\b|\blook-?alike\b"
)


def _normal(text: str) -> str:
    cleaned = "".join(
        " " if unicodedata.category(ch) in ("Cc", "Zl", "Zp") else ch
        for ch in unicodedata.normalize("NFKC", text)
        if unicodedata.category(ch) != "Cn" and not _is_invisible(ch)
    )
    return " ".join(cleaned.lower().split())


def _bad_name(name: str) -> bool:
    plain = name.strip()
    if not plain or len(plain) > NAME_MAX:
        return True
    if not any(ch.isalpha() for ch in plain):
        return True
    return query_problem(plain) is not None


def _hits(pattern: re.Pattern[str], text: str) -> bool:
    # also read the text with stray symbols removed, so "stal-k" style splits are still seen
    return bool(pattern.search(text) or pattern.search(re.sub(r"[^a-z0-9 ]", "", text)))


def check_scope(name: str, context: str | None = None) -> ScopeVerdict:
    """Is this request about a public figure / work contact? Refuses the rest, in plain words."""
    if not GUARD_ENABLED:
        return _ALLOWED
    if not isinstance(name, str) or _bad_name(name):
        return ScopeVerdict(False, Scope.BAD_INPUT, BAD_NAME_REFUSAL)
    ctx = context if isinstance(context, str) else ""
    if len(ctx) > CONTEXT_MAX or (ctx and query_problem(ctx) is not None):
        return ScopeVerdict(False, Scope.BAD_INPUT, BAD_NAME_REFUSAL)
    text = _normal(f"{name} {ctx}")
    if _hits(_FACE, text):
        return ScopeVerdict(False, Scope.FACE_MATCH, FACE_REFUSAL)
    if _hits(_PRIVATE, text):
        return ScopeVerdict(False, Scope.PRIVATE_INDIVIDUAL, PRIVATE_REFUSAL)
    return _ALLOWED


__all__ = [
    "BAD_NAME_REFUSAL",
    "FACE_REFUSAL",
    "GUARD_ENABLED",
    "PRIVATE_REFUSAL",
    "Scope",
    "ScopeVerdict",
    "check_scope",
]
