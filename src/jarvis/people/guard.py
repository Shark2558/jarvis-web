# src/jarvis/people/guard.py
"""The PRE-FILTER for people research (R4 D10, D-D1.1): deterministic, no model call.

This is a fast deny list for requests that are plainly about a private person (home, movements,
private accounts, relations, "who is she" photos). It is NOT the control that decides who may be
researched: that is the positive verification gate in `jarvis.people.gate`, which produces links
only for a verifiable public figure or a due-diligence subject. A bare private name has no
wording to catch, so a deny list alone could never be enough.

The text is folded before it is read, so the usual evasions do not hide a trigger word: NFKD with
Latin accents dropped, invisible characters removed, Cyrillic/Greek look-alikes mapped to Latin,
leetspeak digits read as letters, single-letter spacing (`s t a l k`) collapsed, and punctuation
inside a word (`s.t.a.l.k`) ignored. Hinglish terms are included.

`enabled` is a parameter, not a module global: only a test can pass False (its negative control).
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from enum import StrEnum

from jarvis.tools.card import _is_invisible
from jarvis.web.guard import query_problem

NAME_MAX = 80
CONTEXT_MAX = 200
MIN_SPACED_RUN = 3  # this many single letters in a row are read as one spaced-out word
LATIN_LIMIT = 0x2B0  # code points below this are Latin: their combining accents are dropped

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
UNVERIFIED_REFUSAL = (
    "I can only research public figures or people in a stated professional role that I can "
    "verify, Sir."
)
REFUSAL_LINES = frozenset({PRIVATE_REFUSAL, FACE_REFUSAL, BAD_NAME_REFUSAL, UNVERIFIED_REFUSAL})


class Scope(StrEnum):
    OK = "ok"
    PRIVATE_PHRASING = "private_phrasing"
    FACE_MATCH = "face_match"
    BAD_INPUT = "bad_input"
    UNVERIFIED = "unverified"
    CLASSIFIER = "classifier"


@dataclass(frozen=True)
class ScopeVerdict:
    allowed: bool
    scope: Scope = Scope.OK
    message: str = ""


_ALLOWED = ScopeVerdict(True)


def refusal(scope: Scope) -> ScopeVerdict:
    message = {
        Scope.PRIVATE_PHRASING: PRIVATE_REFUSAL,
        Scope.FACE_MATCH: FACE_REFUSAL,
        Scope.BAD_INPUT: BAD_NAME_REFUSAL,
    }.get(scope, UNVERIFIED_REFUSAL)
    return ScopeVerdict(False, scope, message)


_POSSESSIVE = r"(?:her|his|their|hers|uska|uski|iska|iski)"
_PRIVATE = re.compile(
    r"\b(?:home|house|residen\w*|domicile|current|present|permanent|live)\s+(?:address|add|location)\b"
    r"|\bhome\s*add\w*\b|\bwhereabouts\b|\bgps\b|\bpin\s?code\b|\bstreet\b|\bnumber\s+plate\b"
    r"|\bwhere\b[^.]{0,30}\b(?:live|lives|living|lived|stays?|staying|resides?|goes|"
    r"works?\s*out|studies|is\s+now)\b"
    r"|\bresides?\b|\bresiding\b|\bresidence\b"
    rf"|\b{_POSSESSIVE}\s+(?:daily\s+)?(?:movements?|routine|schedule|gym|school|college|house|"
    r"flat|place|home|address|number|email|accounts?|handle|socials?|profiles?|family|kids?|"
    r"children|husband|wife|relationship|salary|dob|photos?)\b"
    r"|\bmovements?\s+of\s+(?:her|him|them)\b|\bdaily\s+(?:routine|movements?|schedule)\b"
    r"|\bevery\s*day\b|\bwhich\s+(?:gym|school|college)\b|\bwork\s*out\b"
    r"|\b(?:track|tracks|tracking|trace|follow|follows|following)\s+"
    rf"(?:{_POSSESSIVE}|him|them|down|someone|where)\b"
    r"|\b(?:monitor|spy|stalk\w*|dox+\w*|sneak\w*)\b|\bkeep\s+an\s+eye\b"
    rf"|\bwatch\s+(?:{_POSSESSIVE}|him|them)\b"
    r"|\bprivate\s+(?:accounts?|profiles?|number|email|photos?|life|whatsapp|instagram|facebook"
    r"|snapchat|telegram|twitter|social|dms?|messages?)\b"
    r"|\bpersonal\s+(?:email|phone|number|account|accounts|address)\b"
    r"|\b(?:phone|mobile|cell|home)\s+number\b|\bpassword\b|\blog-?in\b|\bpasscode\b"
    r"|\be-?mail\b|\bgmail\b|\bwhatsapp\b|\big\b|\bhandle\b|\baccounts\b|\btinder\b|\bbumble\b"
    r"|\bdating\b|\baadh?aa?r\b|\bpan\s*(?:card|number)\b|\bfamily\s+members?\b"
    r"|\b(?:salary|relationship\s+status)\b"
    r"|\beverything\s+(?:about|on)\b|\bdirt\s+on\b|\bevery\s+detail\b"
    r"|\b(?:my|our)\s+(?:ex\b|ex-|neighbou?rs?\b|crush\b|girlfriend\b|boyfriend\b|classmate\b|"
    r"colleague\b|boss\b|landlord\b|tenant\b|teacher\b|friend\b|cousin\b|sister\b|brother\b)"
    r"|\bfriend'?s\b|\bex-?(?:girlfriend|boyfriend|wife|husband)\b"
    r"|\bdate\s+of\s+birth\b|\bdob\s+of\b|\bborn\s+on\b"
    r"|\ball\s+(?:her|his|their)\s+(?:accounts|profiles|social)\b"
    # Hinglish
    r"|\bkahan\s+(?:rehti|rehta|rahti|rahta|jati|jata)\b|\bghar\b|\bpata\b"
    r"|\busk[ai]\s+(?:number|address|pata|ghar)\b|\bnumber\s+(?:do|chahiye)\b"
    r"|\bpehchan\b|\bmer[ai]\s+ex\b|\brehti\s+hai\b|\brehta\s+hai\b"
)
_FACE = re.compile(
    r"\b(?:face|faces|facial|selfie|photo|photograph|picture|image|pic|screenshot|attached)\b"
    r"|\bwho\s+is\s+(?:this|that|she|he|they)\b|\bidentify\b|\breverse\s+image\b|\blook-?alike\b"
    r"|\bwhois\b|\bthe\s+(?:girl|woman|man|guy|lady|boy)\s+(?:i|we)\s+(?:saw|met|noticed)\b"
)

_CONFUSABLES = str.maketrans(
    {
        # Cyrillic
        "а": "a", "в": "b", "е": "e", "к": "k", "м": "m", "н": "h", "о": "o", "р": "p",
        "с": "c", "т": "t", "у": "y", "х": "x", "і": "i", "ј": "j", "ѕ": "s", "ԁ": "d",
        "һ": "h", "ӏ": "l", "ь": "b", "г": "r", "п": "n", "и": "u", "з": "3", "ѵ": "v",
        # Greek
        "α": "a", "β": "b", "ε": "e", "ι": "i", "κ": "k", "ν": "v", "ο": "o", "ρ": "p",
        "τ": "t", "υ": "u", "χ": "x", "η": "n", "μ": "u", "γ": "y", "ω": "w", "ς": "s",
    }
)  # fmt: skip
_LEET = str.maketrans("013457@$!", "oieastasi")


def _drop(ch: str, kept: list[str]) -> bool:
    if unicodedata.category(ch) == "Mn":  # Latin accents go; Indic vowel signs stay
        return bool(kept) and ord(kept[-1]) < LATIN_LIMIT
    return unicodedata.category(ch) in ("Cn", "Cf") or _is_invisible(ch)


def fold(text: str) -> str:
    """Lower-case, accent-free (Latin only), invisible-free, look-alikes mapped to Latin."""
    kept: list[str] = []
    for ch in unicodedata.normalize("NFKD", text):
        if _drop(ch, kept):
            continue
        kept.append(" " if unicodedata.category(ch) in ("Cc", "Zl", "Zp") else ch)
    return " ".join("".join(kept).lower().translate(_CONFUSABLES).split())


def _collapse_spaced(text: str) -> str:
    """`s t a l k` -> `stalk`: runs of single letters are joined."""
    out: list[str] = []
    run: list[str] = []

    def flush() -> None:
        out.append("".join(run) if len(run) >= MIN_SPACED_RUN else " ".join(run))
        run.clear()

    for tok in text.split():
        if len(tok) == 1 and tok.isalpha():
            run.append(tok)
            continue
        if run:
            flush()
        out.append(tok)
    if run:
        flush()
    return " ".join(out)


def variants(text: str) -> list[str]:
    """Every reading of `text` the pre-filter checks (de-duplicated, order kept)."""
    base = fold(text)
    out: list[str] = []
    for v in (base, base.translate(_LEET)):
        stripped = re.sub(r"[^\w ]", "", v)
        for form in (v, _collapse_spaced(v), stripped, _collapse_spaced(stripped)):
            if form not in out:
                out.append(form)
    return out


def _bad_name(name: str) -> bool:
    plain = name.strip()
    if not plain or len(plain) > NAME_MAX:
        return True
    if not any(ch.isalpha() for ch in plain):
        return True
    return query_problem(plain) is not None


def scope_of(text: str) -> Scope:
    """OK, FACE_MATCH or PRIVATE_PHRASING for free text (name and context already joined)."""
    forms = variants(text)
    if any(_FACE.search(f) for f in forms):
        return Scope.FACE_MATCH
    if any(_PRIVATE.search(f) for f in forms):
        return Scope.PRIVATE_PHRASING
    return Scope.OK


def check_scope(name: str, context: str | None = None, *, enabled: bool = True) -> ScopeVerdict:
    """Pre-filter: refuses private phrasing and face matching, in plain words."""
    if not enabled:
        return _ALLOWED
    if not isinstance(name, str) or _bad_name(name):
        return refusal(Scope.BAD_INPUT)
    ctx = context if isinstance(context, str) else ""
    if len(ctx) > CONTEXT_MAX or (ctx and query_problem(ctx) is not None):
        return refusal(Scope.BAD_INPUT)
    found = scope_of(f"{name} {ctx}")
    return _ALLOWED if found is Scope.OK else refusal(found)


__all__ = [
    "BAD_NAME_REFUSAL",
    "CONTEXT_MAX",
    "FACE_REFUSAL",
    "NAME_MAX",
    "PRIVATE_REFUSAL",
    "REFUSAL_LINES",
    "UNVERIFIED_REFUSAL",
    "Scope",
    "ScopeVerdict",
    "check_scope",
    "fold",
    "refusal",
    "scope_of",
]
