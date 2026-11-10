# src/jarvis/buildbook/guard.py
"""The talk-through's deterministic guards (R6 D12; docs/plans/r6-build-book.md). An untrusted
guest is at the keyboard: these run with NO model call and answer with D13's fixed lines.

- `pre_guard(question)` -> "refuse_data" | "refuse_action" | "refuse_meta" | None. The question is
  read in three views after `normalise` (NFKC, invisible/zero-width characters removed, Cyrillic,
  Greek and small-capital look-alikes folded to Latin, case folded, in-word separators and
  spaced-out letters joined): as written, with digits/symbols read as letters ("3mail"), and with
  every non-letter squeezed out. Order: injection/meta, then hard data (any "@", any 10+ digit
  run), then actions (imperatives: "send", "delete", "buy", "switch on", "arm", "call"...), then
  the owner's data (his e-mail, inbox, calendar, contacts, phone, address, whereabouts, family,
  passwords, keys, money, vault, memory with a person or request word). Feature questions ("How
  does JARVIS read e-mail?", "How does your memory work?") pass. English, Hindi and Malayalam.
- `post_guard(reply, ...)`: an e-mail address, a phone number, an owner e-mail or its local part,
  a secret pattern, the canary, a URL off the book's own list or a raw reference fence -> refused.
- `cap(reply)`: control characters out, at most `REPLY_MAX` characters, cut at a sentence end.
Nothing here logs; the caller never logs the question or the reply either.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Sequence
from typing import Literal
from urllib.parse import urlsplit

from jarvis.buildbook import guard_words as W
from jarvis.buildbook.guard_words import normalise

Refusal = Literal["refuse_data", "refuse_action", "refuse_meta"]
REPLY_MAX = 1_200


def _views(text: str) -> tuple[str, str, str]:
    plain = normalise(text)
    leet = normalise(plain.translate(W.LEET))
    squeezed = "".join(c for c in leet if c.isalpha())
    return plain, leet, squeezed


def _encoded(raw: str) -> bool:
    for m in W.BLOB.finditer(raw):
        run = m.group()
        digits = sum(c.isdigit() for c in run)
        if digits >= 2 or "+" in run or "/" in run:
            return True
    return False


def _meta(raw: str, views: tuple[str, str, str]) -> bool:
    plain, leet, squeezed = views
    if "<<" in plain or ">>" in plain or _encoded(raw):
        return True
    if W.META.search(plain) or W.META.search(leet):
        return True
    if any(k in squeezed for k in W.META_SQUEEZED) or any(k in plain for k in W.META_INDIC):
        return True
    return any(
        any(a in plain for a in first) and any(b in plain for b in second)
        for first, second in W.META_INDIC_PAIRS
    )


def _hard_data(nfkc: str) -> bool:
    return "@" in nfkc or bool(W.DIGITS.search(nfkc))


def _action(views: tuple[str, str, str]) -> bool:
    plain, leet, _ = views
    for view in (plain, leet):
        if any(W.ACTION.search(part) for part in W.SENTENCE.split(view)):
            return True
    return any(k in plain for k in W.ACTION_INDIC)


def _data_in(view: str) -> bool:
    if W.WHERE.search(view):
        return True
    if W.PERSON.search(view) and W.PERSON_ONLY.search(view):
        return True
    if not W.TOPIC.search(view):
        return False
    if W.PERSON.search(view):
        return True
    feature = bool(W.FEATURE.search(view))
    if feature:
        return False
    if W.YOURS.search(view) or W.REVEAL.search(view):
        return True
    return bool(W.REQUEST.search(view) and W.STRONG_RE.search(view))


def _data(views: tuple[str, str, str]) -> bool:
    plain, leet, _ = views
    if _data_in(plain) or _data_in(leet):
        return True
    return any(p in plain for p in W.PERSON_INDIC) and any(t in plain for t in W.TOPIC_INDIC)


def pre_guard(question: str) -> Refusal | None:
    """The fixed line to answer with (and NO model call), or None when the question may go on."""
    views = _views(question)
    if _meta(question, views):
        return "refuse_meta"
    if _hard_data(unicodedata.normalize("NFKC", question)):
        return "refuse_data"
    if _action(views):
        return "refuse_action"
    return "refuse_data" if _data(views) else None


def _host(url: str) -> str:
    text = url if "://" in url else "http://" + url
    try:
        return (urlsplit(text).hostname or "").rstrip(".")
    except ValueError:
        return ""


def book_hosts(book_text: str) -> frozenset[str]:
    """The hosts of every http(s) URL the book itself names: the only links a reply may give."""
    return frozenset(
        h
        for m in W.URL.finditer(book_text)
        if m.group().lower().startswith("http") and (h := _host(m.group().lower()))
    )


def _allowed(host: str, allowed: frozenset[str]) -> bool:
    return bool(host) and any(host == a or host.endswith("." + a) for a in allowed)


def _off_list_link(text: str, allowed: frozenset[str]) -> bool:
    hosts = [_host(m.group().lower()) for m in W.URL.finditer(text)]
    hosts += [m.group() for m in W.DOMAIN.finditer(text.lower())]
    return any(not _allowed(h, allowed) for h in hosts)


def _owner_hit(text: str, owner_emails: Sequence[str]) -> bool:
    low = text.casefold()
    for email in owner_emails:
        address = email.strip().casefold()
        local = address.split("@", 1)[0]
        if address and address in low:
            return True
        if len(local) >= 3 and re.search(rf"(?<![\w.]){re.escape(local)}(?!\w)", low):
            return True
    return False


def post_guard(
    reply: str, *, canary: str, owner_emails: Sequence[str], allowed_hosts: frozenset[str]
) -> Refusal | None:
    """The fixed line to answer with instead of the model's reply, or None when it may be shown."""
    nfkc = unicodedata.normalize("NFKC", reply)
    squeezed = "".join(c for c in normalise(nfkc) if c.isalnum())
    if canary and (canary in nfkc or canary.casefold() in squeezed):
        return "refuse_meta"
    if W.SECRETS.search(nfkc) or "<<" in nfkc or ">>" in nfkc:
        return "refuse_meta"
    if W.EMAIL.search(nfkc) or W.DIGITS.search(nfkc) or _owner_hit(nfkc, owner_emails):
        return "refuse_data"
    return "refuse_meta" if _off_list_link(nfkc, allowed_hosts) else None


def cap(reply: str, limit: int = REPLY_MAX) -> str:
    """Printable, single-spaced, at most `limit` characters (cut after a sentence when it can)."""
    text = " ".join(W.CONTROL.sub(" ", W.visible(reply)).split())
    if len(text) <= limit:
        return text
    cut = text[:limit]
    end = max(cut.rfind(". "), cut.rfind("! "), cut.rfind("? "))
    return cut[: end + 1] if end >= limit // 2 else cut


__all__ = ["REPLY_MAX", "Refusal", "book_hosts", "cap", "normalise", "post_guard", "pre_guard"]
