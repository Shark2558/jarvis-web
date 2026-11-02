# src/jarvis/whatsapp/draft.py
"""A WhatsApp draft: its text, its link, and the card a reply carries (slice 12 D6). Pure; stdlib,
pydantic, `jarvis.contacts.phones` and the fence helper `jarvis.tools.external.fence_body` (the
reply model imports this module; `jarvis.tools` is already loaded by then).

Text (`clean_text`): what the owner will send, so it is kept as written — Malayalam with its
zero-width (non-)joiners, emoji sequences (ZWJ, skin tones, an emoji's variation selector), new
lines and tabs — and only what can't be seen or can reorder what is seen goes: control
characters, bidi controls and marks, zero-width spaces, BOMs, tag characters (invisible "ASCII
smuggling"), other format characters, private-use code points and lone surrogates. Line /
paragraph separators become new lines. Review S3 (hidden payloads): also the characters that
render blank although they are letters or marks (`BLANK`: Hangul fillers, the braille blank, the
combining grapheme joiner, Khmer inherent vowels, Mongolian selectors, variation selectors other
than an emoji's — which also encode bytes invisibly), a variation selector with nothing before it
or repeated, spaces at the end of a line, and more than two blank lines in a row. A text that is
empty or only blank after that is refused. At most `TEXT_MAX` characters after cleaning. The
console's draft card checks the same (`console-whatsapp.js`).

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
from jarvis.tools.external import fence_body

TEXT_MAX = 2000
NAME_MAX = 100
MAX_BLANK_LINES = 2
WA_BASE = "https://wa.me/"
JS_SAFE = "!*'()"  # with Python's always-safe "-_.~": exactly encodeURIComponent's set
WARNING = "This number didn't come from you or your contacts — check it before you send."
ASSUMED_INDIA = "Assumed India (+91)"  # review S5: the number was written without a country code
KNOWN_SOURCES = frozenset({"you", "contacts"})
_KEEP_FORMAT = frozenset({"\u200c", "\u200d"})  # ZWNJ / ZWJ: Indic scripts and emoji need them
_DROP_CATEGORIES = frozenset({"Cc", "Cf", "Co", "Cs"})
_EMOJI_SELECTORS = frozenset({"\ufe0e", "\ufe0f"})  # text / emoji presentation, after a base
# Letters and marks that render as nothing (review S3). Mirrored in console-whatsapp.js.
BLANK = frozenset(
    "\u115f\u1160\u3164\uffa0"  # Hangul fillers
    "\u2800"  # braille pattern blank
    "\u034f"  # combining grapheme joiner
    "\u17b4\u17b5"  # Khmer inherent vowels
    "\u180b\u180c\u180d\u180f"  # Mongolian free variation selectors
)
_BLANK_RANGES = ((0xFE00, 0xFE0D), (0xE0100, 0xE01EF))  # variation selectors but an emoji's
_TOO_MANY_BLANK_LINES = re.compile(r"\n{" + str(MAX_BLANK_LINES + 2) + r",}")


def _blank(ch: str) -> bool:
    code = ord(ch)
    return ch in BLANK or any(lo <= code <= hi for lo, hi in _BLANK_RANGES)


def _visible_chars(text: str) -> str:
    """Each character kept, dropped or turned into a new line (see the module docstring)."""
    out: list[str] = []
    for ch in text:
        if ch in "\n\t" or ch in _KEEP_FORMAT:
            out.append(ch)
        elif ch in _EMOJI_SELECTORS:
            prev = out[-1] if out else ""
            if prev and not prev.isspace() and prev not in _EMOJI_SELECTORS:
                out.append(ch)  # one selector, right after a character it can change
        elif not _blank(ch):
            cat = unicodedata.category(ch)
            if cat in ("Zl", "Zp"):
                out.append("\n")
            elif cat not in _DROP_CATEGORIES:
                out.append(ch)
    return "".join(out)


def clean_text(raw: str) -> str:
    """The draft text with only what the owner can see (see the module docstring)."""
    text = _visible_chars(raw.replace("\r\n", "\n").replace("\r", "\n"))
    text = "\n".join(line.rstrip() for line in text.split("\n"))
    text = _TOO_MANY_BLANK_LINES.sub("\n" * (MAX_BLANK_LINES + 1), text)
    return text.strip()


def text_arg(value: Any) -> str:
    """The draft text, cleaned, 1..TEXT_MAX characters — or ValueError in plain words."""
    if not isinstance(value, str):
        raise ValueError("text is required (the message to draft)")
    text = clean_text(value)
    if not text:
        raise ValueError("text is required (the message to draft; it can't be only blank)")
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
    when `value` is not exactly one fence (`jarvis.tools.external.fence_body`)."""
    body = fence_body(value)
    return " ".join(body.split())[:NAME_MAX] if body is not None else ""


class DraftCard(BaseModel):
    """One draft under a reply (ChatResponse.whatsapp): the console shows the name and number,
    "Assumed India (+91)" when no country code was written, the text, the warning line when
    there is one, and Open in WhatsApp (the link it builds from the number and text with
    encodeURIComponent — the same string as `link`)."""

    model_config = ConfigDict(frozen=True)

    name: str = ""
    number: str
    text: str
    link: str
    warning: str = ""
    assumed: str = ""  # review S5: ASSUMED_INDIA, or "" when the country code was written


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
    assumed = to.get("assumed_india") is True and number.startswith("+91")
    return DraftCard(
        name=unfenced(to.get("name")),
        number=number,
        text=text,
        link=wa_link(number, text),
        warning="" if known else WARNING,
        assumed=ASSUMED_INDIA if assumed else "",
    )


__all__ = [
    "ASSUMED_INDIA",
    "BLANK",
    "KNOWN_SOURCES",
    "MAX_BLANK_LINES",
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
