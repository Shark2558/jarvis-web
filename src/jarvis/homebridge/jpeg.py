# src/jarvis/homebridge/jpeg.py
"""A JPEG's size from its header, without decoding it (R11.1 O7; plan D15 "decoder safety").
Ships in the home kit; standard library only.

The laptop is the only place a picture is decoded, so the bridge checks BEFORE the decoder runs,
and it must read the header exactly as the decoder (libjpeg-turbo, inside OpenCV) will, or a
crafted file could show this reader one size and the decoder another (review C-sec H1: a TEM
marker, which libjpeg takes as having no length, hid the real 144-megapixel frame header from a
reader that took every marker as having one). So the walk from the start of the file to the
first scan accepts only:

- fill bytes (FF FF ...) before a marker;
- the segments libjpeg itself steps over by their length: APP0..APP15 (camera data, which may
  hold a thumbnail with its own frame header: never read), COM, DQT, DHT, DRI and DAC;
- exactly ONE frame header, baseline, extended or progressive Huffman, 8-bit, 1 to 4
  components, whose length is exactly what its components need (arithmetic, lossless and
  hierarchical frames are `unsupported`);
- then the first scan (SOS), which ends the walk.

Everything else is refused as `bad_jpeg`: a parameterless marker (TEM, RST0..7), a second SOI, a
second frame header, DNL, EXP, JPG and the reserved markers, bytes that are not a marker where a
marker must be, a scan before the frame, and a file that ends before its first scan. The caller
then compares the size with its caps.
"""

from __future__ import annotations

import struct

JPEG = b"\xff\xd8\xff"
_SOF_OK = frozenset({0xC0, 0xC1, 0xC2})
_SOF_OTHER = frozenset({0xC3, *range(0xC5, 0xC8), *range(0xC9, 0xCC), *range(0xCD, 0xD0)})
_DHT, _DAC, _DQT, _DRI, _COM, _SOS = 0xC4, 0xCC, 0xDB, 0xDD, 0xFE, 0xDA
# the segments libjpeg reads past by their own length before the first scan (jdmarker.c)
_WITH_LENGTH = frozenset({_DHT, _DAC, _DQT, _DRI, _COM, *range(0xE0, 0xF0)})
MAX_COMPONENTS = 4


class PictureRefused(ValueError):
    """A picture the bridge will not decode. `code` is a short word, never the picture."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def _frame(data: bytes, pos: int, length: int) -> tuple[int, int]:
    """(width, height) from one frame header segment at `pos`, read completely."""
    if length < 8:
        raise PictureRefused("bad_jpeg")
    bits, height, width, comps = struct.unpack_from(">BHHB", data, pos + 4)
    if bits != 8 or not 1 <= comps <= MAX_COMPONENTS or length != 8 + 3 * comps:
        raise PictureRefused("bad_jpeg")
    if width <= 0 or height <= 0:
        raise PictureRefused("bad_jpeg")
    return width, height


def jpeg_size(data: bytes) -> tuple[int, int]:
    """(width, height) of the picture's one frame, or `PictureRefused`."""
    if not data.startswith(JPEG):
        raise PictureRefused("not_jpeg")
    pos, size = 2, None
    while True:
        if pos + 2 > len(data) or data[pos] != 0xFF:
            raise PictureRefused("bad_jpeg")
        marker = data[pos + 1]
        if marker == 0xFF:  # a fill byte
            pos += 1
            continue
        if marker == _SOS:
            if size is None:
                raise PictureRefused("bad_jpeg")  # a scan before any frame
            return size
        if marker in _SOF_OTHER:
            raise PictureRefused("unsupported")
        if marker not in _SOF_OK and marker not in _WITH_LENGTH:
            raise PictureRefused("bad_jpeg")  # parameterless, reserved or unknown: never guessed
        if pos + 4 > len(data):
            raise PictureRefused("bad_jpeg")
        (length,) = struct.unpack_from(">H", data, pos + 2)
        if length < 2 or pos + 2 + length > len(data):
            raise PictureRefused("bad_jpeg")
        if marker in _SOF_OK:
            if size is not None:
                raise PictureRefused("bad_jpeg")  # a second frame header
            size = _frame(data, pos, length)
        pos += 2 + length


__all__ = ["JPEG", "PictureRefused", "jpeg_size"]
