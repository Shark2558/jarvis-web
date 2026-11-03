# src/jarvis/whatsapp/draft.py
"""A WhatsApp draft: its text, its link, and the card a reply carries (slice 12 D6). Pure; stdlib,
pydantic and `jarvis.contacts.phones` only (`jarvis.tools.reply_cards` imports this module for
its `WhatsAppCard` kind, so nothing here may import `jarvis.tools`).

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

Card (`WhatsAppCard`, kind "whatsapp" in `ChatResponse.cards`): whatsapp_draft adds it with
`jarvis.tools.reply_cards.add_card` when a draft is ready, beside its result and never inside what
the model sees. `draft_card` checks the number and text again and builds the link from them; the
model re-checks every field when the card is made (cards are never stored or read back), so a
card whose link is not exactly `wa_link(number, text)` never exists.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any, Literal, Self
from urllib.parse import quote

from pydantic import BaseModel, ConfigDict, model_validator

from jarvis.contacts.phones import is_e164, wa_digits

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


def card_name(raw: object) -> str:
    """A contact's name as the card shows it: what `clean_text` keeps, on one line (runs of
    white space become one space), at most NAME_MAX characters; '' for anything but a string."""
    if not isinstance(raw, str):
        return ""
    return " ".join(clean_text(raw).split())[:NAME_MAX].strip()


class WhatsAppCard(BaseModel):
    """One draft under a reply (kind "whatsapp" in ChatResponse.cards): the console shows the
    name and number, "Assumed India (+91)" when no country code was written, the text, the
    warning line when there is one, and Open in WhatsApp (the link it builds from the number and
    text with encodeURIComponent — the same string as `link`). Every field is checked when a
    card is made, so one that doesn't check is never shown."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: Literal["whatsapp"] = "whatsapp"
    name: str = ""
    number: str
    text: str
    link: str
    warning: str = ""
    assumed: str = ""  # review S5: ASSUMED_INDIA, or "" when the country code was written

    @model_validator(mode="after")
    def _reads_back(self) -> Self:
        if not is_e164(self.number):
            raise ValueError("number is not E.164")
        if not self.text or len(self.text) > TEXT_MAX or clean_text(self.text) != self.text:
            raise ValueError("text is not a clean draft text")
        if self.link != wa_link(self.number, self.text):
            raise ValueError("link is not the number and text's wa.me link")
        if card_name(self.name) != self.name:
            raise ValueError("name is not one clean line")
        if self.warning not in ("", WARNING):
            raise ValueError("unknown warning")
        if self.assumed not in ("", ASSUMED_INDIA) or (
            self.assumed and not self.number.startswith("+91")
        ):
            raise ValueError("assumed is only for a +91 number")
        return self


def draft_card(
    *, name: str | None, number: str, text: str, source: str, assumed: bool
) -> WhatsAppCard | None:
    """The card for a draft that is ready; None when the number or text doesn't check (never
    raises). The number and text are checked again and the link is built from them — never taken
    from anywhere else; a number that came from neither the owner's words nor Contacts
    (`source`, `jarvis.whatsapp.provenance`) carries WARNING."""
    try:
        return WhatsAppCard(
            name=card_name(name),
            number=number,
            text=text,
            link=wa_link(number, text),
            warning="" if source in KNOWN_SOURCES else WARNING,
            assumed=ASSUMED_INDIA if assumed and number.startswith("+91") else "",
        )
    except ValueError:  # pydantic's ValidationError is one
        return None


__all__ = [
    "ASSUMED_INDIA",
    "BLANK",
    "KNOWN_SOURCES",
    "MAX_BLANK_LINES",
    "NAME_MAX",
    "TEXT_MAX",
    "WARNING",
    "WhatsAppCard",
    "card_name",
    "clean_text",
    "draft_card",
    "text_arg",
    "wa_link",
]
