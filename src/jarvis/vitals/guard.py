# src/jarvis/vitals/guard.py
"""The "a key VALUE is never stored" guard and the label rules (R4 D-A1, D-A3).

Defence in depth, not a proof: it refuses text that LOOKS like a credential, on every entry path,
because `Provider` runs it as a model validator (tool, REST route, any importer). Natural prose is
spared: the separator-stripped copy keeps spaces, so ordinary labels and notes do not trip it. A
secret split over THREE or more fields, or spaced out on purpose, is not caught.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from itertools import combinations

NEVER_PASTE = "Never paste a key's value here: type only its name, limit and expiry."
LABEL_RULE = "A label may use letters, digits, spaces and . & ( ) / - only, with no web address."
LABEL_ALLOWED = re.compile(r"[\w .&()/-]+")
_URL_LIKE = re.compile(r"(?i)http|www\.|\b[\w-]+\.[a-z]{2,}\b")

LONG_RUN = 32  # any token-char run this long is refused
MIXED_RUN = 20  # a run this long with upper + lower + digit is refused
HALF_MIN = 8  # a field's edge token must be this long to be glued to a neighbour

_PREFIXES = re.compile(
    r"(?<![A-Za-z0-9])(?:[Ss][Kk]-|AKIA|AIza|ghp_|gho_|github_pat_|xox[bap]-|eyJ|tvly-)"
    r"[A-Za-z0-9_\-]{8,}"
)
_TELEGRAM = re.compile(r"\d{8,}:[A-Za-z0-9_-]{30,}")
_TOKEN = re.compile(r"[A-Za-z0-9_-]+")
_ALNUM = re.compile(r"[A-Za-z0-9]+")
_NOT_ALNUM_OR_SPACE = re.compile(r"[^A-Za-z0-9\s]")


def _mixed(run: str) -> bool:
    return (
        any(c.isupper() for c in run)
        and any(c.islower() for c in run)
        and any(c.isdigit() for c in run)
    )


def _run_hit(text: str) -> bool:
    if any(len(r) >= LONG_RUN for r in _TOKEN.findall(text)):
        return True
    return any(len(r) >= MIXED_RUN and _mixed(r) for r in _ALNUM.findall(text))


def _text_hit(text: str) -> bool:
    if _PREFIXES.search(text) or _TELEGRAM.search(text):
        return True
    return _run_hit(text) or _run_hit(_NOT_ALNUM_OR_SPACE.sub("", text))


def _edges(text: str) -> tuple[str, str]:
    words = _NOT_ALNUM_OR_SPACE.sub("", text).split()
    return (words[-1], words[0]) if words else ("", "")


def _id_hit(pid: str) -> bool:
    """An id is a slug of the label ("electricity-bill-payment-reminder"): its dashes are word
    breaks, so a long slug of ordinary words is not a long run. Credential prefixes, a Telegram
    token or a real long run (a hex id) are still refused."""
    if _PREFIXES.search(pid) or _TELEGRAM.search(pid):
        return True
    return _text_hit(re.sub(r"[-_]+", " ", pid))


def looks_like_a_key(fields: Sequence[str], *, ident: str = "") -> bool:
    """True when a field, or one field's tail glued to a later field's head, looks like a key.

    `fields[0]` is the label and `ident` the id derived from it. The id is checked on its own
    (`_id_hit`) and glued to every field EXCEPT the label: it is a slug of the label, so gluing
    the two double-counts an ordinary long name."""
    if ident and _id_hit(ident):
        return True
    if any(_text_hit(f) for f in fields):
        return True
    edges = [_edges(f) for f in fields]
    pairs = list(combinations(range(len(edges)), 2))
    if ident:
        edges.append(_edges(ident))
        pairs += [(len(edges) - 1, k) for k in range(1, len(fields))]  # not the label (index 0)
    for a, b in pairs:
        tail, head = edges[a][0], edges[b][1]
        if len(tail) >= HALF_MIN and len(head) >= HALF_MIN and _run_hit(tail + head):
            return True
    return False


def label_problem(label: str) -> str | None:
    """Why a manual label is refused, or None (constrained text: no lure in an urgent push)."""
    if not LABEL_ALLOWED.fullmatch(label) or _URL_LIKE.search(label):
        return LABEL_RULE
    return None


__all__ = ["LABEL_RULE", "NEVER_PASTE", "label_problem", "looks_like_a_key"]
