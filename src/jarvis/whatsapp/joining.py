# src/jarvis/whatsapp/joining.py
"""Where a zero-width non-joiner / joiner (U+200C / U+200D) may stay in a WhatsApp draft (slice
12 security reviews SEC-5 M1 and SEC-6; Layer 4 Safety). Pure, stdlib only.

The rule starts from RFC 5892's CONTEXTJ (IDNA): a ZWNJ or ZWJ right after a virama (canonical
combining class 9: Malayalam's chillu and ZWNJ, Hindi's half forms, Odia, Tamil ...).
`jarvis.whatsapp.draft` narrows it (SEC-6 #4: a letter must follow, or for a ZWJ the virama is
Malayalam's, the old-style chillu) and adds the one other place a ZWJ belongs: inside an RGI
emoji ZWJ sequence (`jarvis.whatsapp.zwj_sequences`). Anywhere else (between Latin, Cyrillic,
CJK, Arabic, mathematical or letterlike letters) a joiner shows nothing and could carry data, so
it goes. SEC-6 #3 removed CONTEXTJ's ZWNJ between Arabic letters: without a Joining_Type table on
either side it can't be judged, and the owner writes Malayalam, Hindi, Odia and English.

`VIRAMAS` was generated once with Python 3.12 (Unicode 15.0) from
`unicodedata.combining(c) == 9`. It is explicit so that every Python (CI also runs 3.11,
Unicode 14) and the browser (JavaScript has no combining-class property) apply exactly the same
rule: console-whatsapp.js keeps an identical copy (tests/test_whatsapp_console.py compares them,
and checks the table against this Python's unicodedata).
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
_VIRAMAS = frozenset(c for lo, hi in VIRAMAS for c in range(lo, hi + 1))


def virama(ch: str) -> bool:
    """True for a virama (canonical combining class 9): a joiner right after it may stay."""
    return len(ch) == 1 and ord(ch) in _VIRAMAS


__all__ = ["UNICODE_VERSION", "VIRAMAS", "virama"]
