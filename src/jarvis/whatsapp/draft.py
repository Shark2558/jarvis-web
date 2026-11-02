# src/jarvis/whatsapp/draft.py
"""A WhatsApp draft: its text, its link, and the card a reply carries (slice 12 D6). Pure; stdlib,
pydantic and `jarvis.contacts.phones` only (the reply model imports it: no `jarvis.tools` here).

Text (`clean_text`): what the owner will send, so it is kept as written — Malayalam with its
zero-width (non-)joiners, emoji sequences (ZWJ, skin tones, variation selectors), new lines and
tabs — and only what can't be seen or can reorder what is seen goes: control characters, bidi
controls and marks, zero-width spaces, BOMs, tag characters (invisible "ASCII smuggling"), other
format characters, private-use code points and lone surrogates. Line / paragraph separators
become new lines. At most `TEXT_MAX` characters after cleaning.

Link (verified 2026-11-03; WhatsApp's own FAQ "How to use click to chat",
faq.whatsapp.com/5913398998672934, could not be fetched — robots.txt and this network's proxy
refuse it — so the format is taken from pages that cite it): `https://wa.me/<number>` with the
full international number, digits only (no "+", leading zeros, spaces, dashes or brackets), and
`?text=<URL-encoded message>` to pre-fill the chat box. The text is encoded exactly as the
console's `encodeURIComponent` encodes it (UTF-8; unreserved A-Z a-z 0-9 - _ . ! ~ * ' ( )), so
the server's link and the console's are the same string.

`DraftCard` is rebuilt from a result's number and text — never from a link a result carries.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any
from urllib.parse import quote

from pydantic import BaseModel, ConfigDict

from jarvis.contacts.phones import is_e164, wa_digits

TEXT_MAX = 2000
NAME_MAX = 100
WA_BASE = "https://wa.me/"
JS_SAFE = "!*'()"  # with Python's always-safe "-_.~": exactly encodeURIComponent's set
WARNING = "This number didn't come from you or your contacts — check it before you send."
KNOWN_SOURCES = frozenset({"you", "contacts"})
_KEEP_FORMAT = frozenset({"\u200c", "\u200d"})  # ZWNJ / ZWJ: Indic scripts and emoji need them
_DROP_CATEGORIES = frozenset({"Cc", "Cf", "Co", "Cs"})
_FENCED = re.compile(
    r"\A<<EXTERNAL CONTENT from [^\n]*· ([0-9a-f]{6})>>\n(.*)\n<<END \1>>\Z", re.DOTALL
)


def clean_text(raw: str) -> str:
    """The draft text with only what the owner can see (see the module docstring)."""
    text = raw.replace("\r\n", "\n").replace("\r", "\n")
    out: list[str] = []
    for ch in text:
        if ch in "\n\t" or ch in _KEEP_FORMAT:
            out.append(ch)
            continue
        cat = unicodedata.category(ch)
        if cat in ("Zl", "Zp"):
            out.append("\n")
        elif cat not in _DROP_CATEGORIES:
            out.append(ch)
    return "".join(out).strip()


def text_arg(value: Any) -> str:
    """The draft text, cleaned, 1..TEXT_MAX characters — or ValueError in plain words."""
    if not isinstance(value, str):
        raise ValueError("text is required (the message to draft)")
    text = clean_text(value)
    if not text:
        raise ValueError("text is required (the message to draft)")
    if len(text) > TEXT_MAX:
        raise ValueError(
            f"text is too long (at most {TEXT_MAX:,} characters; it has {len(text):,})"
        )
    return text


def wa_link(number: str, text: str) -> str:
    """https://wa.me/<digits>?text=<percent-encoded text>; ValueError unless E.164."""
    return f"{WA_BASE}{wa_digits(number)}?text={quote(text, safe=JS_SAFE)}"


def unfenced(value: Any) -> str:
    """The text inside one external-content fence (a contact's name as the model saw it), or ''
    when `value` is not exactly one fence."""
    m = _FENCED.match(value) if isinstance(value, str) else None
    return " ".join(m.group(2).split())[:NAME_MAX] if m else ""


class DraftCard(BaseModel):
    """One draft under a reply (ChatResponse.whatsapp): the console shows the name and number,
    the text, the warning line when there is one, and Open in WhatsApp (the link it builds from
    the number and text with encodeURIComponent — the same string as `link`)."""

    model_config = ConfigDict(frozen=True)

    name: str = ""
    number: str
    text: str
    link: str
    warning: str = ""


def card_from_result(result: Any) -> DraftCard | None:
    """The card for a whatsapp_draft result that made a draft; None for anything else (a choice
    list, a message, a malformed result). Number and text are re-checked; the link is rebuilt."""
    if not isinstance(result, dict) or result.get("status") != "draft_ready":
        return None
    to, text = result.get("to"), result.get("text")
    if not isinstance(to, dict) or not is_e164(to.get("number")) or not isinstance(text, str):
        return None
    if not text or len(text) > TEXT_MAX or clean_text(text) != text:
        return None
    number = str(to["number"])
    known = isinstance(to.get("from"), str) and to["from"] in KNOWN_SOURCES
    return DraftCard(
        name=unfenced(to.get("name")),
        number=number,
        text=text,
        link=wa_link(number, text),
        warning="" if known else WARNING,
    )


__all__ = [
    "KNOWN_SOURCES",
    "NAME_MAX",
    "TEXT_MAX",
    "WARNING",
    "DraftCard",
    "card_from_result",
    "clean_text",
    "text_arg",
    "unfenced",
    "wa_link",
]
