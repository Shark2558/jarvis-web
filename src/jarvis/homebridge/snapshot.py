# src/jarvis/homebridge/snapshot.py
"""The one picture that may leave home: a small burglar-alert snapshot (R3 D12).

Frigate is asked for a small JPEG (`h=480`, `bbox=0`); `Snapshot.small` then makes sure it really
is one: a baseline/progressive JPEG whose long side is at most 640 px and whose size is at most
80 KB, with every metadata segment removed (APPn: EXIF, GPS, ICC, XMP; COM comments). Anything
else - not a JPEG, too big, too large a picture, damaged - is refused (None) and the alert goes out
without a photo. Pure stdlib: no image library is needed because nothing is re-encoded.

The bridge attaches it only for a `person` detection while armed and only when the cloud's settings
say the owner opted in (`SettingsState.snapshot`). The cloud passes it to Telegram in memory.
"""

from __future__ import annotations

import struct

from jarvis.home.ports import JPEG_MAGIC, MAX_SNAPSHOT_BYTES

MAX_LONG_SIDE = 640
_SOI, _EOI, _SOS, _TEM = 0xD8, 0xD9, 0xDA, 0x01
_SOF = {0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF}
_STANDALONE = {_TEM, *range(0xD0, 0xD8)}  # no length: RSTn, TEM
_DROP = {*range(0xE0, 0xF0), 0xFE}  # APP0-APP15 and COM


def _scan(jpeg: bytes, start: int) -> bytes | None:
    """`jpeg[start:]` cut after the first EOI. None when there is no EOI or a second SOI starts
    inside the picture (a picture hidden in the picture)."""
    i = start
    n = len(jpeg)
    while i + 1 < n:
        if jpeg[i] != 0xFF:
            i += 1
            continue
        marker = jpeg[i + 1]
        if marker == _EOI:
            return jpeg[start : i + 2]
        if marker == _SOI:
            return None
        i += 2 if marker != 0xFF else 1
    return None


def _segments(jpeg: bytes) -> tuple[list[bytes], tuple[int, int]] | None:
    """The kept header segments and (width, height); None when the file isn't a sound JPEG."""
    if not jpeg.startswith(JPEG_MAGIC):
        return None
    kept: list[bytes] = [jpeg[:2]]
    size: tuple[int, int] | None = None
    i = 2
    n = len(jpeg)
    while i + 4 <= n:
        if jpeg[i] != 0xFF:
            return None
        marker = jpeg[i + 1]
        if marker == 0xFF:  # fill byte
            i += 1
            continue
        if marker in _STANDALONE:
            kept.append(jpeg[i : i + 2])
            i += 2
            continue
        (length,) = struct.unpack(">H", jpeg[i + 2 : i + 4])
        end = i + 2 + length
        if length < 2 or end > n:
            return None
        if marker in _SOF:
            if length < 8:
                return None
            height, width = struct.unpack(">HH", jpeg[i + 5 : i + 9])
            size = (width, height)
        if marker == _SOS:
            if size is None:
                return None
            scan = _scan(jpeg, i)  # the scan, up to and including the first EOI, and nothing after
            if scan is None:
                return None
            kept.append(scan)
            return kept, size
        if marker not in _DROP:
            kept.append(jpeg[i:end])
        i = end
    return None


def small(jpeg: bytes) -> bytes | None:
    """`jpeg` without metadata if it is a JPEG of at most 640 px and 80 KB; else None."""
    got = _segments(jpeg)
    if got is None:
        return None
    parts, (width, height) = got
    if width < 1 or height < 1 or max(width, height) > MAX_LONG_SIDE:
        return None
    out = b"".join(parts)
    if len(out) > MAX_SNAPSHOT_BYTES or not out.endswith(b"\xff\xd9"):
        return None
    return out


class Snapshot:
    """`Snapshot.small(jpeg)` as in the plan's key functions."""

    small = staticmethod(small)


__all__ = ["MAX_LONG_SIDE", "Snapshot", "small"]
