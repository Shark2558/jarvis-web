# src/jarvis/helpers/today/qr.py
"""The QR of a prepared UPI payment (docs/plans/r11-free-helpers.md D7): segno (BSD-3-Clause, pure
Python) encodes exactly the `upi://pay` link, error correction M, as an SVG data URI the console
shows as an image (`img-src 'self' data:`; an SVG in an <img> runs no script). Black on white, so
any UPI app's scanner reads it in Night mode too. Made on request, never stored or logged.
"""

from __future__ import annotations

import segno

from jarvis.helpers.today.upi import SCHEME

DATA_URI = "data:image/svg+xml;charset=utf-8,"
SCALE = 4
BORDER = 4  # the quiet zone the QR standard asks for


def qr_data_uri(link: str) -> str:
    if not isinstance(link, str) or not link.startswith(SCHEME):
        raise ValueError("only a UPI payment link becomes a QR")
    code = segno.make(link, error="m", micro=False)
    uri: str = code.svg_data_uri(scale=SCALE, border=BORDER, dark="#000", light="#fff")
    if not uri.startswith(DATA_URI):
        raise ValueError("unexpected QR output")
    return uri


__all__ = ["DATA_URI", "qr_data_uri"]
