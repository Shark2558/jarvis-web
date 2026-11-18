# tests/r131_png_pixels.py -- R13.1 I1, after GitHub's browser job (run 44216933907): a
# screenshot's pixels read with Python's own tools (zlib, struct), so no test needs Pillow:
# GitHub's browser job installs only `.[dev]` and Playwright (the R7 lesson).
# Imported bare (`from r131_png_pixels import read_png`), never `from tests....`.
#   read_png(data)  a PNG as Chromium and Playwright write it: 8-bit RGB or RGBA, not interlaced,
#                   any of the five filter types; the alpha is dropped, as Pillow's convert("RGB")
#                   drops it. Anything else is refused in words (ValueError).
#   Pixels          size, getpixel((x, y)), crop((left, top, right, bottom)), colours()
#   diff_box(a, b)  the box of every pixel that differs, as ImageChops.difference(a, b).getbbox()
# Pinned by tests/test_r131_png_pixels.py.
from __future__ import annotations

import struct
import zlib
from dataclasses import dataclass

SIGNATURE = b"\x89PNG\r\n\x1a\n"
CHANNELS = {2: 3, 6: 4}  # PNG colour type -> bytes a pixel at 8 bits: RGB, RGBA


@dataclass(frozen=True)
class Pixels:
    """An RGB picture: `rgb` is row after row, 3 bytes a pixel."""

    width: int
    height: int
    rgb: bytes

    @property
    def size(self) -> tuple[int, int]:
        return self.width, self.height

    def getpixel(self, xy: tuple[int, int]) -> tuple[int, int, int]:
        x, y = xy
        if not (0 <= x < self.width and 0 <= y < self.height):
            raise IndexError(f"pixel {xy} is outside a {self.width} x {self.height} picture")
        i = (y * self.width + x) * 3
        return self.rgb[i], self.rgb[i + 1], self.rgb[i + 2]

    def crop(self, box: tuple[int, int, int, int]) -> Pixels:
        left, top, right, bottom = box
        if not (0 <= left <= right <= self.width and 0 <= top <= bottom <= self.height):
            raise ValueError(f"crop {box} is outside a {self.width} x {self.height} picture")
        rows = (self.rgb[(y * self.width + left) * 3 : (y * self.width + right) * 3]
                for y in range(top, bottom))  # fmt: skip
        return Pixels(right - left, bottom - top, b"".join(rows))

    def colours(self) -> set[tuple[int, int, int]]:
        """Every distinct colour (Pillow's getcolors() without the counts)."""
        seen = {self.rgb[i : i + 3] for i in range(0, len(self.rgb), 3)}
        return {(c[0], c[1], c[2]) for c in seen}


def _chunks(data: bytes) -> list[tuple[bytes, bytes]]:
    if data[:8] != SIGNATURE:
        raise ValueError("not a PNG: the signature is missing")
    out, at = [], 8
    while at < len(data):
        if at + 12 > len(data):
            raise ValueError("a PNG cut short")
        (n,) = struct.unpack(">I", data[at : at + 4])
        kind, body = data[at + 4 : at + 8], data[at + 8 : at + 8 + n]
        if len(body) != n or at + 12 + n > len(data):
            raise ValueError("a PNG cut short")
        (crc,) = struct.unpack(">I", data[at + 8 + n : at + 12 + n])
        if zlib.crc32(kind + body) != crc:
            raise ValueError(f"a PNG chunk {kind!r} fails its CRC")
        out.append((kind, body))
        at += 12 + n
        if kind == b"IEND":
            return out
    raise ValueError("a PNG cut short: no IEND")


def _paeth(a: int, b: int, c: int) -> int:
    p = a + b - c
    pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
    return a if pa <= pb and pa <= pc else (b if pb <= pc else c)


def _unfilter(kind: int, line: bytearray, prev: bytes, bpp: int) -> bytearray:
    if kind == 0:
        return line
    if kind == 2:  # Up (what Chromium writes)
        return bytearray((x + b) & 0xFF for x, b in zip(line, prev, strict=True))
    for i in range(len(line)):
        a = line[i - bpp] if i >= bpp else 0
        if kind == 1:  # Sub
            line[i] = (line[i] + a) & 0xFF
        elif kind == 3:  # Average
            line[i] = (line[i] + ((a + prev[i]) >> 1)) & 0xFF
        elif kind == 4:  # Paeth
            line[i] = (line[i] + _paeth(a, prev[i], prev[i - bpp] if i >= bpp else 0)) & 0xFF
        else:
            raise ValueError(f"a PNG row with an unknown filter type {kind}")
    return line


def read_png(data: bytes) -> Pixels:
    """An 8-bit RGB or RGBA PNG, not interlaced, as RGB pixels (the alpha dropped)."""
    chunks = _chunks(data)
    if not chunks or chunks[0][0] != b"IHDR" or len(chunks[0][1]) != 13:
        raise ValueError("not a PNG: IHDR does not come first")
    width, height, depth, ctype, _comp, _filt, interlace = struct.unpack(">IIBBBBB", chunks[0][1])
    if depth != 8 or ctype not in CHANNELS:
        raise ValueError(f"only 8-bit RGB or RGBA PNGs are read (depth {depth}, type {ctype})")
    if interlace:
        raise ValueError("an interlaced PNG is not read")
    bpp = CHANNELS[ctype]
    stride = width * bpp
    raw = zlib.decompress(b"".join(body for kind, body in chunks if kind == b"IDAT"))
    if len(raw) != (stride + 1) * height:
        raise ValueError("a PNG cut short: its pixel data has the wrong length")
    out, prev = bytearray(), bytes(stride)
    for y in range(height):
        at = y * (stride + 1)
        line = _unfilter(raw[at], bytearray(raw[at + 1 : at + 1 + stride]), prev, bpp)
        out += line
        prev = bytes(line)
    if bpp == 4:
        del out[3::4]
    return Pixels(width, height, bytes(out))


def diff_box(a: Pixels, b: Pixels) -> tuple[int, int, int, int] | None:
    """(left, top, right, bottom) around every pixel that differs, None when none does."""
    if a.size != b.size:
        raise ValueError(f"pictures of different sizes: {a.size} and {b.size}")
    row = a.width * 3
    xs: list[int] = []
    ys: list[int] = []
    for y in range(a.height):
        ra, rb = a.rgb[y * row : (y + 1) * row], b.rgb[y * row : (y + 1) * row]
        if ra == rb:
            continue
        ys.append(y)
        first = next(i for i in range(row) if ra[i] != rb[i])
        last = next(i for i in range(row - 1, -1, -1) if ra[i] != rb[i])
        xs += [first // 3, last // 3]
    if not ys:
        return None
    return min(xs), ys[0], max(xs) + 1, ys[-1] + 1
