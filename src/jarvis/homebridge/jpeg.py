# src/jarvis/homebridge/jpeg.py
"""A JPEG's size from its header, without decoding it (R11.1 O7; plan D15 "decoder safety").
Ships in the home kit; standard library only.

The laptop is the only place a picture is decoded, so the bridge checks BEFORE the decoder runs:
the bytes must be a JPEG whose first frame header is baseline, extended or progressive Huffman
(arithmetic, lossless and hierarchical frames are refused), and the caller compares the declared
size with its caps. Camera data (APPn, which may hold a thumbnail with its own frame header) is
stepped over by its length, never read.
"""

from __future__ import annotations

import struct

JPEG = b"\xff\xd8\xff"
_SOF_OK = frozenset({0xC0, 0xC1, 0xC2})
_NOT_FRAMES = frozenset({0xC4, 0xC8, 0xCC})  # DHT, JPG, DAC sit in the SOF range but are not frames
_EOI, _SOS = 0xD9, 0xDA


class PictureRefused(ValueError):
    """A picture the bridge will not decode. `code` is a short word, never the picture."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def jpeg_size(data: bytes) -> tuple[int, int]:
    """(width, height) of the picture's first frame, or `PictureRefused`."""
    if not data.startswith(JPEG):
        raise PictureRefused("not_jpeg")
    pos = 2
    while pos + 4 <= len(data):
        if data[pos] != 0xFF:
            raise PictureRefused("bad_jpeg")
        marker = data[pos + 1]
        if marker == 0xFF:  # a fill byte
            pos += 1
            continue
        if marker in (_EOI, _SOS):
            break  # the picture's data starts (or the file ends) before any frame header
        (length,) = struct.unpack_from(">H", data, pos + 2)
        if length < 2 or pos + 2 + length > len(data):
            raise PictureRefused("bad_jpeg")
        if marker in _SOF_OK:
            if length < 8:
                raise PictureRefused("bad_jpeg")
            _, height, width = struct.unpack_from(">BHH", data, pos + 4)
            if width <= 0 or height <= 0:
                raise PictureRefused("bad_jpeg")
            return width, height
        if 0xC0 <= marker <= 0xCF and marker not in _NOT_FRAMES:
            raise PictureRefused("unsupported")
        pos += 2 + length
    raise PictureRefused("bad_jpeg")


__all__ = ["JPEG", "PictureRefused", "jpeg_size"]
