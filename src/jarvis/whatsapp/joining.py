# src/jarvis/whatsapp/joining.py
"""Where a zero-width non-joiner / joiner (U+200C / U+200D) may stay in a WhatsApp draft (slice
12 security review SEC-5 M1; Layer 4 Safety). Pure, stdlib only.

The rule is RFC 5892's CONTEXTJ (IDNA): a ZWNJ or ZWJ right after a virama (canonical combining
class 9: Malayalam's chillu and ZWNJ, Hindi's half forms, Odia, Tamil ...), and a ZWNJ also
between two Arabic letters (Persian "mi-khaham"). `jarvis.whatsapp.draft` adds the third place a
ZWJ belongs: inside an emoji sequence. Anywhere else (between Latin, Cyrillic, CJK, mathematical
or letterlike letters) a joiner shows nothing and could carry data, so it goes.

Both tables were generated once with Python 3.12 (Unicode 15.0): `VIRAMAS` from
`unicodedata.combining(c) == 9`, `ARABIC_LETTERS` from the letters (category L*) whose name starts
"ARABIC LETTER " (so not U+061C ARABIC LETTER MARK, a format character, nor U+0670 ARABIC LETTER
SUPERSCRIPT ALEF, a mark). They are explicit so that every Python (CI also runs 3.11, Unicode 14)
and the browser (JavaScript has no combining-class property) apply exactly the same rule:
console-whatsapp.js keeps identical copies (tests/test_whatsapp_console.py compares them, and
checks them against this Python's unicodedata).
"""

from __future__ import annotations

UNICODE_VERSION = "15.0"
VIRAMAS: tuple[tuple[int, int], ...] = (
    (0x094D, 0x094D), (0x09CD, 0x09CD), (0x0A4D, 0x0A4D), (0x0ACD, 0x0ACD),
    (0x0B4D, 0x0B4D), (0x0BCD, 0x0BCD), (0x0C4D, 0x0C4D), (0x0CCD, 0x0CCD),
    (0x0D3B, 0x0D3C), (0x0D4D, 0x0D4D), (0x0DCA, 0x0DCA), (0x0E3A, 0x0E3A),
    (0x0EBA, 0x0EBA), (0x0F84, 0x0F84), (0x1039, 0x103A), (0x1714, 0x1715),
    (0x1734, 0x1734), (0x17D2, 0x17D2), (0x1A60, 0x1A60), (0x1B44, 0x1B44),
    (0x1BAA, 0x1BAB), (0x1BF2, 0x1BF3), (0x2D7F, 0x2D7F), (0xA806, 0xA806),
    (0xA82C, 0xA82C), (0xA8C4, 0xA8C4), (0xA953, 0xA953), (0xA9C0, 0xA9C0),
    (0xAAF6, 0xAAF6), (0xABED, 0xABED), (0x10A3F, 0x10A3F), (0x11046, 0x11046),
    (0x11070, 0x11070), (0x1107F, 0x1107F), (0x110B9, 0x110B9), (0x11133, 0x11134),
    (0x111C0, 0x111C0), (0x11235, 0x11235), (0x112EA, 0x112EA), (0x1134D, 0x1134D),
    (0x11442, 0x11442), (0x114C2, 0x114C2), (0x115BF, 0x115BF), (0x1163F, 0x1163F),
    (0x116B6, 0x116B6), (0x1172B, 0x1172B), (0x11839, 0x11839), (0x1193D, 0x1193E),
    (0x119E0, 0x119E0), (0x11A34, 0x11A34), (0x11A47, 0x11A47), (0x11A99, 0x11A99),
    (0x11C3F, 0x11C3F), (0x11D44, 0x11D45), (0x11D97, 0x11D97), (0x11F41, 0x11F42),
)  # fmt: skip
ARABIC_LETTERS: tuple[tuple[int, int], ...] = (
    (0x0620, 0x063F), (0x0641, 0x064A), (0x066E, 0x066F), (0x0671, 0x06D3),
    (0x06D5, 0x06D5), (0x06EE, 0x06EF), (0x06FA, 0x06FC), (0x06FF, 0x06FF),
    (0x0750, 0x077F), (0x0870, 0x0882), (0x0886, 0x0886), (0x0889, 0x088D),
    (0x08A0, 0x08C8), (0xFB50, 0xFBB1), (0xFBD3, 0xFBE9), (0xFBFC, 0xFBFF),
    (0xFE80, 0xFEF4),
)  # fmt: skip
_VIRAMAS = frozenset(c for lo, hi in VIRAMAS for c in range(lo, hi + 1))
_ARABIC = frozenset(c for lo, hi in ARABIC_LETTERS for c in range(lo, hi + 1))


def virama(ch: str) -> bool:
    """True for a virama (canonical combining class 9): a joiner right after it is kept."""
    return len(ch) == 1 and ord(ch) in _VIRAMAS


def arabic_letter(ch: str) -> bool:
    """True for an Arabic letter: a ZWNJ between two of them is kept."""
    return len(ch) == 1 and ord(ch) in _ARABIC


__all__ = ["ARABIC_LETTERS", "UNICODE_VERSION", "VIRAMAS", "arabic_letter", "virama"]
