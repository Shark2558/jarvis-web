# src/jarvis/documents/imagecheck.py
"""An attached picture, checked by its structure and never decoded (R11.1, plan D10; Layer 2).
Pure and synchronous; in the app it runs only inside the extraction worker.

    JPEG   `jarvis.photos.imaging.sanitise_jpeg` (R4; dependency-free): only the segments a
           decoder needs are kept, so EXIF (camera, GPS), XMP, ICC and comments are gone. It
           alone decides whether a JPEG is too wide (its `MAX_IMAGE_SIDE`); when it refuses
           one, the frame's size is read here only to say why in words (code review L1)
    PNG    the same idea here: the header, palette, transparency and pixel chunks are kept, each
           with its checksum verified; text, EXIF, time and every other extra chunk is dropped,
           and so is anything after the end marker

A picture wider or taller than `PICTURE_MAX_SIDE` (2,048 px; the console shrinks to 1,568 before
it uploads) or heavier than `Limits.picture_max_bytes` after cleaning is refused in plain words.
No pixel is ever decompressed on the server: the only thing that decodes the picture is the
vision model it is shown to. Standard library plus `jarvis.photos.imaging` (itself standard
library only), so the worker stays small.
"""

from __future__ import annotations

import struct
import zlib

from jarvis.documents.extract import Extracted, Limits, Picture, _mismatch
from jarvis.documents.limits import PICTURE_MAX_SIDE, DocumentRejected

PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
JPEG_MAGIC = b"\xff\xd8\xff"
_KEPT = frozenset({b"IHDR", b"PLTE", b"tRNS", b"IDAT", b"IEND"})
_CRITICAL = frozenset({b"IHDR", b"PLTE", b"IDAT", b"IEND"})
_DEPTHS = frozenset({1, 2, 4, 8, 16})
_COLOURS = frozenset({0, 2, 3, 4, 6})
_SOF = frozenset({0xC0, 0xC1, 0xC2})
_NO_LENGTH = frozenset({0x01, *range(0xD0, 0xD8)})
SMALLER = (
    "The console makes a picture smaller before it sends it: attach it there, or save a smaller "
    "copy."
)


def _bad() -> DocumentRejected:
    return DocumentRejected(
        "bad_picture",
        "This picture couldn't be read. It may be damaged, or saved in an unusual way: open it "
        "and save it again as a JPEG or PNG, then attach that.",
    )


def _too_wide(width: int, height: int, limit: int = PICTURE_MAX_SIDE) -> DocumentRejected:
    return DocumentRejected(
        "too_large",
        f"This picture is {width:,} by {height:,} pixels; the limit is {limit:,} "
        f"pixels on its longer side. {SMALLER}",
        status=413,
    )


def _too_heavy(size: int, limit: int) -> DocumentRejected:
    return DocumentRejected(
        "too_large",
        f"This picture is {-(-size // 1024):,} KB once its camera data is removed; the limit is "
        f"{limit // 1024:,} KB. {SMALLER}",
        status=413,
    )


def _check_side(width: int, height: int) -> None:
    if width <= 0 or height <= 0:
        raise _bad()
    if max(width, height) > PICTURE_MAX_SIDE:
        raise _too_wide(width, height)


# ---- JPEG ---------------------------------------------------------------------------------------


def _jpeg_size(data: bytes) -> tuple[int, int] | None:
    """(width, height) from the first frame header, or None when the file is not walkable. For
    the words of a refusal only: the check itself is `sanitise_jpeg`'s."""
    pos, n = 2, len(data)
    while pos + 4 <= n and data[pos] == 0xFF:
        marker = data[pos + 1]
        if marker == 0xFF:
            pos += 1
            continue
        if marker in _NO_LENGTH:
            pos += 2
            continue
        (length,) = struct.unpack_from(">H", data, pos + 2)
        if length < 2:
            return None
        if marker in _SOF:
            if pos + 9 > n:
                return None
            height, width = struct.unpack_from(">HH", data, pos + 5)
            return width, height
        if marker == 0xDA:  # the scan started with no frame before it
            return None
        pos += 2 + length
    return None


def _clean_jpeg(data: bytes) -> bytes:
    from jarvis.photos import imaging  # standard library only (R4 D-C1)

    try:
        return imaging.sanitise_jpeg(data)
    except Exception:  # noqa: BLE001 — PickerError, or anything a hostile file triggers
        size = _jpeg_size(data)
        limit = imaging.MAX_IMAGE_SIDE
        if size is not None and min(size) > 0 and max(size) > limit:
            raise _too_wide(*size, limit) from None
        raise _bad() from None


# ---- PNG ----------------------------------------------------------------------------------------


def _check_header(body: bytes) -> None:
    if len(body) != 13:
        raise _bad()
    width, height, depth, colour, compression, filtering, interlace = struct.unpack(
        ">IIBBBBB", body
    )
    _check_side(width, height)
    if depth not in _DEPTHS or colour not in _COLOURS:
        raise _bad()
    if compression != 0 or filtering != 0 or interlace not in (0, 1):
        raise _bad()


def _clean_png(data: bytes) -> bytes:
    out = bytearray(PNG_MAGIC)
    pos, n = len(PNG_MAGIC), len(data)
    seen: list[bytes] = []
    while True:
        if pos + 12 > n:
            raise _bad()  # the file ended before its end marker
        (length,) = struct.unpack_from(">I", data, pos)
        kind = data[pos + 4 : pos + 8]
        end = pos + 12 + length
        if end > n:
            raise _bad()
        body = data[pos + 8 : pos + 8 + length]
        if not seen and kind != b"IHDR":
            raise _bad()
        if kind in _KEPT:
            (crc,) = struct.unpack_from(">I", data, end - 4)
            if zlib.crc32(kind + body) != crc:
                raise _bad()
            if kind == b"IHDR":
                if seen:
                    raise _bad()
                _check_header(body)
            out += data[pos:end]
            seen.append(kind)
            if kind == b"IEND":
                break
        elif not kind.isalpha() or kind[:1].isupper():
            raise _bad()  # a chunk a decoder must understand, and we don't know it
        pos = end
    if b"IDAT" not in seen or (seen.count(b"PLTE") > 1):
        raise _bad()
    return bytes(out)


# ---- entry points -------------------------------------------------------------------------------


def clean_picture(data: bytes, limits: Limits, *, name: str = "") -> Picture:
    """`data` as a picture safe to keep and show: structure checked, metadata removed, within
    the pixel and byte caps. Raises `DocumentRejected` in plain words otherwise."""
    if data.startswith(PNG_MAGIC):
        media, clean = "image/png", _clean_png(data)
    elif data.startswith(JPEG_MAGIC):
        media, clean = "image/jpeg", _clean_jpeg(data)
    else:
        raise _mismatch("png or .jpg")
    if len(clean) > limits.picture_max_bytes:
        raise _too_heavy(len(clean), limits.picture_max_bytes)
    return Picture(name=name, media_type=media, data=clean)


def read_picture(data: bytes, limits: Limits) -> Extracted:
    return Extracted(kind="image", text="", pictures=(clean_picture(data, limits),))


__all__ = ["JPEG_MAGIC", "PNG_MAGIC", "clean_picture", "read_picture"]
