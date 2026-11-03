# src/jarvis/whatsapp/draft.py
"""A WhatsApp draft: its text, its link, and the card a reply carries (slice 12 D6). Pure; stdlib,
pydantic and `jarvis.contacts.phones` only (`jarvis.tools.reply_cards` imports this module for
its `WhatsAppCard` kind, so nothing here may import `jarvis.tools`).

Text (`clean_text`): what the owner will send, so it is kept as written — Malayalam with its
zero-width (non-)joiners, emoji sequences (ZWJ, skin tones, an emoji's variation selector) and new
lines — and only what can't be seen or can reorder what is seen goes. Security review SEC-1 (an
invisible channel: 80 ZWNJ / ZWJ between Latin letters carried "OTP 482913" past a card that
showed only the words): every space character (Unicode Zs) and tab becomes one plain space and
runs of spaces collapse; a ZWNJ / ZWJ stays only between two letters of a non-Latin script
(`external.model_text`'s rule, minus Latin and generic marks: `NOT_A_SCRIPT`) or, for a ZWJ,
between an emoji and the next emoji; FE0E / FE0F stay only right after an emoji
(Extended_Pictographic, `jarvis.whatsapp.pictographic`) or a keycap base [0-9#*]. Also gone: control
characters, bidi controls and marks, zero-width spaces, BOMs, tag characters (invisible "ASCII
smuggling"), other format characters, private-use code points and lone surrogates. Line /
paragraph separators become new lines. Review S3 (hidden payloads): also the characters that
render blank although they are letters or marks (`BLANK`: Hangul fillers, the braille blank, the
combining grapheme joiner, Khmer inherent vowels, Mongolian selectors, variation selectors other
than an emoji's — which also encode bytes invisibly — and, with the final review's
console-text.js, the unassigned code points that render as nothing: U+2065, U+FFF0-FFF8 and
the whole tag block U+E0000-E0FFF), a variation selector with nothing before it
or repeated, spaces at the end of a line, and more than two blank lines in a row. A text that is
empty or only blank after that is refused. At most `TEXT_MAX` characters after cleaning. Review
FE-8: more than `MAX_MARKS` combining marks in a row ("Zalgo" text, a smear that hides what it
says) is refused in plain words (`STACKED`). The console's draft card checks the same
(`console-whatsapp.js`).

Link (verified 2026-11-03; WhatsApp's own FAQ "How to use click to chat",
faq.whatsapp.com/5913398998672934, could not be fetched — robots.txt and this network's proxy
refuse it — so the format is taken from pages that cite it): `https://wa.me/<number>` with the
full international number, digits only (no "+", leading zeros, spaces, dashes or brackets), and
`?text=<URL-encoded message>` to pre-fill the chat box. The text is encoded exactly as the
console's `encodeURIComponent` encodes it (UTF-8; unreserved A-Z a-z 0-9 - _ . ! ~ * ' ( )), so
the server's link and the console's are the same string.

Card (`WhatsAppCard`, kind "whatsapp" in `ChatResponse.cards`): whatsapp_draft adds it with
`jarvis.tools.reply_cards.add_card` when a draft is ready, beside its result and never inside what
the model sees. `draft_card` checks the number and text again and builds the link from them, and
the model re-checks every field whenever a card is made (its validator below: the text must
already be what `clean_text` leaves and not `stacked`), so a card whose link is not exactly
`wa_link(number, text)` never exists. A conversation opened again gets its draft cards back the
same way: rebuilt from the stored draft results through `draft_card` (`jarvis.whatsapp.restore`,
final review) — so a stored text that today's rule (SEC-1, FE-8) would change or refuse is
skipped, never shown altered.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any, Literal, Self
from urllib.parse import quote

from pydantic import BaseModel, ConfigDict, model_validator

from jarvis.contacts.phones import is_e164, wa_digits
from jarvis.whatsapp.pictographic import extended_pictographic

TEXT_MAX = 2000
NAME_MAX = 100
MAX_BLANK_LINES = 2
MAX_MARKS = 4  # review FE-8: combining marks in a row; console-whatsapp.js mirrors it exactly
STACKED = "That text has stacked accent marks I can't show clearly; please retype it."
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
_BLANK_RANGES = (
    (0xFE00, 0xFE0D),  # variation selectors but an emoji's
    # Default_Ignorable code points that are unassigned (category Cn, so `_DROP_CATEGORIES`
    # misses them) yet render as nothing: U+2065, U+FFF0-FFF8 and the whole tag block
    # U+E0000-E0FFF (tags, its unassigned rest, and the variation selectors supplement).
    # Not every Cn: a new emoji is Cn to an older Python. Mirrored in console-whatsapp.js.
    (0x2065, 0x2065),
    (0xFFF0, 0xFFF8),
    (0xE0000, 0xE0FFF),
)
_TOO_MANY_BLANK_LINES = re.compile(r"\n{" + str(MAX_BLANK_LINES + 2) + r",}")
_MANY_SPACES = re.compile(" {2,}")
# SEC-1: letters and marks next to which a ZWNJ / ZWJ is never kept — Latin (with its accents,
# precomposed or combining), and the generic marks any script may carry (diacritics for
# symbols incl. the keycap mark, half marks, variation selectors). Mirrored in console-whatsapp.js.
NOT_A_SCRIPT: tuple[tuple[int, int], ...] = (
    (0x0000, 0x036F),  # Basic Latin .. Latin Extended-B, IPA, modifier letters, combining marks
    (0x1AB0, 0x1AFF),  # Combining Diacritical Marks Extended
    (0x1D00, 0x1EFF),  # Phonetic Extensions (+ Supplement), marks supplement, Latin Ext. Additional
    (0x20D0, 0x20FF),  # Combining Diacritical Marks for Symbols (the keycap mark U+20E3)
    (0x2C60, 0x2C7F),  # Latin Extended-C
    (0xA720, 0xA7FF),  # Latin Extended-D
    (0xAB30, 0xAB6F),  # Latin Extended-E
    (0xFB00, 0xFB06),  # Latin ligatures
    (0xFE00, 0xFE0F),  # Variation Selectors
    (0xFE20, 0xFE2F),  # Combining Half Marks
    (0xFF21, 0xFF3A),  # Fullwidth Latin capitals
    (0xFF41, 0xFF5A),  # Fullwidth Latin small letters
    (0x10780, 0x107BF),  # Latin Extended-F
    (0x1DF00, 0x1DFFF),  # Latin Extended-G
)
ZWJ = "\u200d"
KEYCAP_BASES = frozenset("0123456789#*")  # what FE0F + U+20E3 makes a keycap emoji of
SKIN_TONES = range(0x1F3FB, 0x1F3FF + 1)  # Emoji_Modifier (Fitzpatrick types 1-2 .. 6)


def _blank(ch: str) -> bool:
    code = ord(ch)
    return ch in BLANK or any(lo <= code <= hi for lo, hi in _BLANK_RANGES)


def _script_letter(ch: str) -> bool:
    """A letter or mark of a non-Latin script: `jarvis.tools.external`'s joiner rule (non-ASCII,
    category L* or M*), minus the Latin and generic blocks (`NOT_A_SCRIPT`) — an accented Latin
    letter, a combining accent or a variation selector (category Mn) is not one."""
    if not ch or ch.isascii() or unicodedata.category(ch)[0] not in "LM":
        return False
    code = ord(ch)
    return not any(lo <= code <= hi for lo, hi in NOT_A_SCRIPT)


def _emoji_before(text: str, i: int) -> bool:
    """Whether text[i] ends an emoji a ZWJ may follow: an emoji (Extended_Pictographic), its skin
    tone (Emoji_Modifier, U+1F3FB..U+1F3FF) or its FE0F right after an emoji."""
    ch = text[i] if 0 <= i < len(text) else ""
    if ch == "\ufe0f":
        return i > 0 and extended_pictographic(text[i - 1])
    return bool(ch) and (extended_pictographic(ch) or ord(ch) in SKIN_TONES)


def _selector_ok(text: str, i: int) -> bool:
    """Whether the FE0E / FE0F at text[i] may stay: directly after an emoji (Extended_
    Pictographic) or a keycap base [0-9#*] (1 + FE0F + U+20E3 is the keycap 1)."""
    prev = text[i - 1] if i > 0 else ""
    return bool(prev) and (prev in KEYCAP_BASES or extended_pictographic(prev))


def _visible_chars(text: str) -> str:
    """Pass 1: each character kept, dropped, turned into a new line or a plain space. ZWNJ / ZWJ
    and the presentation selectors are kept here for pass 2 (`_joined`) to judge in place."""
    out: list[str] = []
    for ch in text:
        if ch == "\n" or ch in _KEEP_FORMAT or ch in _EMOJI_SELECTORS:
            out.append(ch)
        elif ch == "\t" or unicodedata.category(ch) == "Zs":
            out.append(" ")  # SEC-1: every space and tab is one plain space (no channel)
        elif not _blank(ch):
            cat = unicodedata.category(ch)
            if cat in ("Zl", "Zp"):
                out.append("\n")
            elif cat not in _DROP_CATEGORIES:
                out.append(ch)
    return "".join(out)


def _joined(text: str) -> str:
    """Pass 2 (SEC-1): a ZWNJ / ZWJ stays only between two letters of a non-Latin script, or a
    ZWJ between an emoji and the next emoji (an emoji ZWJ sequence); FE0E / FE0F only where
    `_selector_ok`. Each is judged against its IMMEDIATE neighbours in pass 1's text, so a run of
    joiners or selectors (or one split by characters pass 1 dropped) keeps none of them."""
    out: list[str] = []
    for i, ch in enumerate(text):
        prev = text[i - 1] if i > 0 else ""
        nxt = text[i + 1] if i + 1 < len(text) else ""
        if ch in _KEEP_FORMAT:
            scripts = _script_letter(prev) and _script_letter(nxt)
            emoji = ch == ZWJ and _emoji_before(text, i - 1) and extended_pictographic(nxt)
            if scripts or emoji:
                out.append(ch)
        elif ch in _EMOJI_SELECTORS:
            if _selector_ok(text, i):
                out.append(ch)
        else:
            out.append(ch)
    return "".join(out)


def clean_text(raw: str) -> str:
    """The draft text with only what the owner can see (see the module docstring)."""
    text = _joined(_visible_chars(raw.replace("\r\n", "\n").replace("\r", "\n")))
    text = _MANY_SPACES.sub(" ", text)
    text = "\n".join(line.rstrip(" ") for line in text.split("\n"))
    text = _TOO_MANY_BLANK_LINES.sub("\n" * (MAX_BLANK_LINES + 1), text)
    return text.strip()


def stacked(text: str) -> bool:
    """True when more than MAX_MARKS combining marks (Unicode category M*) follow one another —
    after one base character or none (review FE-8: "Zalgo" text renders as a smear that hides
    what it says). A zero-width (non-)joiner between two marks does not break the run. Real
    scripts stay well inside: Malayalam, Devanagari, Odia and Tibetan stack at most 3."""
    run = 0
    for ch in text:
        if ch in _KEEP_FORMAT:
            continue
        run = run + 1 if unicodedata.category(ch).startswith("M") else 0
        if run > MAX_MARKS:
            return True
    return False


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
    if stacked(text):
        raise ValueError(STACKED)
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
        if stacked(self.text):
            raise ValueError("text has stacked marks")
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
    "MAX_MARKS",
    "NAME_MAX",
    "STACKED",
    "TEXT_MAX",
    "WARNING",
    "WhatsAppCard",
    "card_name",
    "clean_text",
    "draft_card",
    "stacked",
    "text_arg",
    "wa_link",
]
