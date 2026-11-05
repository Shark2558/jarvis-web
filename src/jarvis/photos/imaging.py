# src/jarvis/photos/imaging.py
"""A dependency-free JPEG metadata stripper (R4 D-C1).

Walks the marker segments and keeps only what a decoder needs: SOI, DQT, DHT, DRI, one SOF
(baseline, extended or progressive Huffman), each SOS with its entropy-coded data, and EOI. Every
APPn segment (EXIF with GPS, XMP, ICC, JFIF, ...), COM and anything after EOI is dropped, so a
photo's location and camera data never leave the cloud. Anything that is not a well-formed JPEG,
or is wider/taller than MAX_IMAGE_SIDE, is refused with `PickerError(BAD_PICTURE)`.

This is a structural check, not a decoder: decompression-bomb protection lives at the home edge,
the only place the pixels are decoded (see INTEGRATION.md).
"""

from __future__ import annotations

import struct

from jarvis.photos.errors import BAD_PICTURE, PickerError

MAX_IMAGE_SIDE = 2048
_SOI, _EOI, _SOS, _DQT, _DHT, _DRI = 0xD8, 0xD9, 0xDA, 0xDB, 0xC4, 0xDD
_SOF_OK = frozenset({0xC0, 0xC1, 0xC2})  # baseline, extended sequential, progressive (Huffman)
_KEEP = frozenset({_DQT, _DHT, _DRI})
_APP_FIRST, _APP_LAST, _COM = 0xE0, 0xEF, 0xFE
_RST = range(0xD0, 0xD8)
_SOF_MIN_LEN = 8  # length field + precision + height + width


def _bad() -> PickerError:
    return PickerError(BAD_PICTURE)


def _segment(data: bytes, pos: int) -> tuple[bytes, int]:
    """(payload, next position) of the length-prefixed segment whose length field is at `pos`."""
    if pos + 2 > len(data):
        raise _bad()
    (length,) = struct.unpack_from(">H", data, pos)
    end = pos + length
    if length < 2 or end > len(data):
        raise _bad()
    return data[pos + 2 : end], end


def _skip_scan(data: bytes, pos: int) -> int:
    """Position of the first real marker after entropy-coded data (stuffing and RSTn stay)."""
    while True:
        pos = data.find(b"\xff", pos)
        if pos < 0 or pos + 1 >= len(data):
            raise _bad()
        nxt = data[pos + 1]
        if nxt == 0x00 or nxt in _RST:
            pos += 2
        elif nxt == 0xFF:
            pos += 1
        else:
            return pos


def _check_frame(payload: bytes) -> None:
    if len(payload) + 2 < _SOF_MIN_LEN + 1:
        raise _bad()
    _, height, width = struct.unpack_from(">BHH", payload, 0)
    if not 0 < width <= MAX_IMAGE_SIDE or not 0 < height <= MAX_IMAGE_SIDE:
        raise _bad()


def sanitise_jpeg(data: bytes) -> bytes:
    if not data.startswith(b"\xff\xd8\xff"):
        raise _bad()
    out = bytearray(b"\xff\xd8")
    pos, frames, scans = 2, 0, 0
    while True:
        if pos + 2 > len(data) or data[pos] != 0xFF:
            raise _bad()
        marker = data[pos + 1]
        if marker == 0xFF:  # fill byte
            pos += 1
            continue
        start = pos
        pos += 2
        if marker == _EOI:
            if not frames or not scans:
                raise _bad()
            return bytes(out + b"\xff\xd9")
        payload, pos = _segment(data, pos)
        if marker in _SOF_OK:
            if frames or scans:
                raise _bad()
            _check_frame(payload)
            frames += 1
            out += data[start:pos]
        elif marker == _SOS:
            if not frames:
                raise _bad()
            scans += 1
            pos = _skip_scan(data, pos)
            out += data[start:pos]
        elif marker in _KEEP:
            out += data[start:pos]
        elif not (_APP_FIRST <= marker <= _APP_LAST or marker == _COM):
            raise _bad()  # reserved, lossless, arithmetic, hierarchical, DNL ...


__all__ = ["MAX_IMAGE_SIDE", "sanitise_jpeg"]
