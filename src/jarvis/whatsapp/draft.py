# src/jarvis/whatsapp/draft.py
"""A WhatsApp draft: its text, its link, and the card a reply carries (slice 12 D6). Pure; stdlib,
pydantic and `jarvis.contacts.phones` only (`jarvis.tools.reply_cards` imports this module for
its `WhatsAppCard` kind, so nothing here may import `jarvis.tools`).

Text (`clean_text`): what the owner will send, so it is kept as written (Malayalam with its
zero-width (non-)joiners, emoji sequences with their ZWJ, skin tones and FE0F, new lines) and
only what can't be seen or can reorder what is seen goes. Security review SEC-1 (an invisible
channel: 80 ZWNJ / ZWJ between Latin letters carried "OTP 482913" past a card that showed only
the words): every space character (Unicode Zs) and tab becomes one plain space and runs of
spaces collapse. Security review SEC-5 ("Call 9<FE0F>8<FE0E>76" still showed as "Call 9876"):
every invisible character that stays must be one the visible text needs, so
- variation selectors (H1): FE0E always goes; FE0F stays only inside a keycap ([0-9#*] FE0F
  U+20E3) or right after a code point whose fully-qualified RGI emoji is cp + FE0F
  (`pictographic.EMOJI_FE0F_BASES`: the heart, the white flag; not the watch or a smiley, which
  are emoji already);
- joiners (M1, RFC 5892 CONTEXTJ, `jarvis.whatsapp.joining`): a ZWNJ / ZWJ stays only right
  after a virama (Malayalam chillu, Hindi half forms), a ZWNJ also between two Arabic letters
  (Persian), a ZWJ also inside an emoji sequence (after an emoji, its skin tone or its FE0F,
  before the next emoji); never between Latin, Cyrillic, CJK, mathematical or letterlike ones;
- no space at the start or end of a line (M2: the approval card's pre-line would hide one);
- unassigned code points (category Cn) go, but the Extended_Pictographic ones Unicode keeps for
  future emoji (M3: Python 3.11, 3.12 and the browser know different Unicode versions; a
  character this Python can't name is dropped, never judged).
Also gone: control characters, bidi controls and marks, zero-width spaces, BOMs, tag characters
(invisible "ASCII smuggling"), other format characters, private-use code points and lone
surrogates. Line / paragraph separators become new lines. Review S3 (hidden payloads): also the
characters that render blank although they are letters or marks (`BLANK`: Hangul fillers and
the Khitan small script filler, the braille blank, the combining grapheme joiner, Khmer inherent
vowels, Mongolian selectors, variation selectors other than an emoji's FE0F, which also encode
bytes invisibly, and, with the final review's console-text.js, the code points that render as
nothing: U+2065, U+FFF0-FFF8 and the whole tag block U+E0000-E0FFF), and more than two blank
lines in a row. A text that is empty or only blank after that is refused. At most `TEXT_MAX`
characters after cleaning. Review FE-8: more than `MAX_MARKS` combining marks in a row ("Zalgo"
text, a smear that hides what it says) is refused in plain words (`STACKED`), counted on the
cleaned text (so a dropped character can't split the run). The console's draft card checks the
same, character for character (`console-whatsapp.js`; tests/fixtures/whatsapp_clean_cases.json).

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
from jarvis.whatsapp.joining import arabic_letter, virama
from jarvis.whatsapp.pictographic import emoji_fe0f_base, extended_pictographic

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
ZWNJ = "\u200c"
ZWJ = "\u200d"
_JOINERS = frozenset({ZWNJ, ZWJ})  # Indic scripts, Persian and emoji sequences need them
VS16 = "\ufe0f"  # the emoji presentation selector: kept only where it makes an emoji (SEC-5 H1)
KEYCAP = "\u20e3"  # combining enclosing keycap: [0-9#*] + FE0F + U+20E3 is a keycap emoji
KEYCAP_BASES = frozenset("0123456789#*")
SKIN_TONES = range(0x1F3FB, 0x1F3FF + 1)  # Emoji_Modifier (Fitzpatrick types 1-2 .. 6)
_DROP_CATEGORIES = frozenset({"Cc", "Cf", "Co", "Cs"})
# Letters and marks that render as nothing (review S3). Mirrored in console-whatsapp.js.
BLANK = frozenset(
    "\u115f\u1160\u3164\uffa0"  # Hangul fillers
    "\U00016fe4"  # Khitan small script filler (SEC-5)
    "\u2800"  # braille pattern blank
    "\u034f"  # combining grapheme joiner
    "\u17b4\u17b5"  # Khmer inherent vowels
    "\u180b\u180c\u180d\u180f"  # Mongolian free variation selectors
)
_BLANK_RANGES = (
    (0xFE00, 0xFE0E),  # variation selectors but an emoji's FE0F (SEC-5 H1: FE0E always goes)
    # Default_Ignorable code points that render as nothing: U+2065, U+FFF0-FFF8 (unassigned,
    # so also caught as Cn) and the whole tag block U+E0000-E0FFF (tags, its unassigned rest,
    # and the variation selectors supplement, category Mn). Mirrored in console-whatsapp.js.
    (0x2065, 0x2065),
    (0xFFF0, 0xFFF8),
    (0xE0000, 0xE0FFF),
)
_TOO_MANY_BLANK_LINES = re.compile(r"\n{" + str(MAX_BLANK_LINES + 2) + r",}")
_MANY_SPACES = re.compile(" {2,}")


def _blank(ch: str) -> bool:
    code = ord(ch)
    return ch in BLANK or any(lo <= code <= hi for lo, hi in _BLANK_RANGES)


def _dropped(ch: str) -> bool:
    """Pass 1 drops it: a control, format, private-use or surrogate code point, or one that is
    unassigned (Cn) to this Python but not a future emoji (SEC-5 M3: a character Unicode 14
    can't name is dropped, never judged, so no rule below depends on the Python's version)."""
    cat = unicodedata.category(ch)
    return cat in _DROP_CATEGORIES or (cat == "Cn" and not extended_pictographic(ch))


def _emoji_before(text: str, i: int) -> bool:
    """Whether text[i] ends an emoji a ZWJ may follow: an emoji (Extended_Pictographic), its skin
    tone (Emoji_Modifier, U+1F3FB..U+1F3FF) or its FE0F right after an emoji."""
    ch = text[i] if 0 <= i < len(text) else ""
    if ch == VS16:
        return i > 0 and extended_pictographic(text[i - 1])
    return bool(ch) and (extended_pictographic(ch) or ord(ch) in SKIN_TONES)


def _keep_selector(prev: str, nxt: str) -> bool:
    """SEC-5 H1: an FE0F stays only inside a keycap (1 + FE0F + U+20E3 is the keycap 1) or right
    after a code point whose RGI emoji is cp + FE0F (`EMOJI_FE0F_BASES`). Anywhere else (after
    a digit, a letter, a smiley that is emoji-style already, a skin tone) it changes nothing on
    screen, so it could only carry data."""
    keycap = prev in KEYCAP_BASES and nxt == KEYCAP
    return keycap or emoji_fe0f_base(prev)


def _keep_joiner(text: str, i: int) -> bool:
    """SEC-5 M1 (RFC 5892 CONTEXTJ): the ZWNJ / ZWJ at text[i] stays right after a virama, a ZWNJ
    also between two Arabic letters, a ZWJ also between an emoji (or its skin tone or FE0F) and
    the next emoji."""
    prev = text[i - 1] if i > 0 else ""
    nxt = text[i + 1] if i + 1 < len(text) else ""
    if virama(prev):
        return True
    if text[i] == ZWNJ:
        return arabic_letter(prev) and arabic_letter(nxt)
    return _emoji_before(text, i - 1) and extended_pictographic(nxt)


def _visible_chars(text: str) -> str:
    """Pass 1: each character kept, dropped, turned into a new line or a plain space. ZWNJ / ZWJ
    and FE0F are kept here for pass 2 (`_joined`) to judge in place."""
    out: list[str] = []
    for ch in text:
        if ch == "\n" or ch in _JOINERS or ch == VS16:
            out.append(ch)
        elif ch == "\t" or unicodedata.category(ch) == "Zs":
            out.append(" ")  # SEC-1: every space and tab is one plain space (no channel)
        elif _blank(ch):
            continue
        elif unicodedata.category(ch) in ("Zl", "Zp"):
            out.append("\n")
        elif not _dropped(ch):
            out.append(ch)
    return "".join(out)


def _joined(text: str) -> str:
    """Pass 2: a ZWNJ / ZWJ stays only where `_keep_joiner`, an FE0F only where `_keep_selector`.
    Each is judged against its IMMEDIATE neighbours in pass 1's text, so a run of joiners or
    selectors (or one split by characters pass 1 dropped) keeps at most the first."""
    out: list[str] = []
    for i, ch in enumerate(text):
        if ch in _JOINERS:
            if _keep_joiner(text, i):
                out.append(ch)
        elif ch == VS16:
            prev = text[i - 1] if i > 0 else ""
            if _keep_selector(prev, text[i + 1] if i + 1 < len(text) else ""):
                out.append(ch)
        else:
            out.append(ch)
    return "".join(out)


def clean_text(raw: str) -> str:
    """The draft text with only what the owner can see (see the module docstring)."""
    text = _joined(_visible_chars(raw.replace("\r\n", "\n").replace("\r", "\n")))
    text = _MANY_SPACES.sub(" ", text)
    # SEC-5 M2: no space at either end of a line (the approval card's pre-line hides them)
    text = "\n".join(line.strip(" ") for line in text.split("\n"))
    text = _TOO_MANY_BLANK_LINES.sub("\n" * (MAX_BLANK_LINES + 1), text)
    return text.strip()


def stacked(text: str) -> bool:
    """True when more than MAX_MARKS combining marks (Unicode category M*) follow one another —
    after one base character or none (review FE-8: "Zalgo" text renders as a smear that hides
    what it says). A zero-width (non-)joiner between two marks does not break the run. Real
    scripts stay well inside: Malayalam, Devanagari, Odia and Tibetan stack at most 3."""
    run = 0
    for ch in text:
        if ch in _JOINERS:
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
