# tests/test_r131_png_pixels.py -- R13.1 I1, after GitHub's browser job (run 44216933907): the
# stage tests read a screenshot's pixels with Python's own tools (`tests/r131_png_pixels.py`), as
# that job installs only `.[dev]` and Playwright, no Pillow (the R7 lesson). Pinned here:
#   - every PNG filter type (None, Sub, Up, Average, Paeth), 8-bit RGB and RGBA, split IDATs;
#   - two PNGs Chromium itself wrote (`tests/fixtures/r13_1/png/`: an element screenshot, RGB, and
#     a canvas's toBlob, RGBA), read to the very values Pillow read from them when they were made;
#   - what the reader refuses (another bit depth or colour type, interlacing, a broken file);
#   - the helpers the tests use (size, getpixel, crop, colours, diff_box);
#   - no module under tests/ imports Pillow.
from __future__ import annotations

import ast
import hashlib
import random
import struct
import zlib
from pathlib import Path

import pytest
from r131_png_pixels import Pixels, diff_box, read_png

TESTS = Path(__file__).resolve().parent
PNGS = TESTS / "fixtures" / "r13_1" / "png"


def _chunk(kind: bytes, body: bytes) -> bytes:
    return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body))


def _predict(kind: int, a: int, b: int, c: int) -> int:
    if kind == 1:
        return a
    if kind == 2:
        return b
    if kind == 3:
        return (a + b) >> 1
    if kind == 4:
        p = a + b - c
        pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
        return a if pa <= pb and pa <= pc else (b if pb <= pc else c)
    return 0


def _encode(
    width: int, rows: list[bytes], ctype: int, *, interlace: int = 0, depth: int = 8
) -> bytes:
    """A PNG written here, independently of the reader: row y uses filter y % 5."""
    bpp = {2: 3, 6: 4}.get(ctype, 1)
    raw, prev = bytearray(), bytes(width * bpp)
    for y, row in enumerate(rows):
        kind = y % 5
        line = bytearray([kind])
        for i, x in enumerate(row):
            a = row[i - bpp] if i >= bpp else 0
            c = prev[i - bpp] if i >= bpp else 0
            line.append((x - _predict(kind, a, prev[i], c)) & 0xFF)
        raw += line
        prev = row
    data = zlib.compress(bytes(raw))
    half = len(data) // 2
    ihdr = struct.pack(">IIBBBBB", width, len(rows), depth, ctype, 0, 0, interlace)
    return (b"\x89PNG\r\n\x1a\n" + _chunk(b"IHDR", ihdr) + _chunk(b"IDAT", data[:half])
            + _chunk(b"IDAT", data[half:]) + _chunk(b"IEND", b""))  # fmt: skip


def _picture(width: int, height: int, channels: int, seed: int) -> list[bytes]:
    rnd = random.Random(seed)
    return [bytes(rnd.randrange(256) for _ in range(width * channels)) for _ in range(height)]


@pytest.mark.parametrize("ctype", [2, 6], ids=["rgb", "rgba"])
def test_every_filter_type_reads_back_the_exact_pixels(ctype: int) -> None:
    channels = 3 if ctype == 2 else 4
    rows = _picture(7, 11, channels, seed=ctype)  # 11 rows: each of the 5 filters twice or more
    got = read_png(_encode(7, rows, ctype))
    assert got.size == (7, 11)
    want = b"".join(rows)
    if channels == 4:  # the alpha is dropped, as Pillow's convert("RGB") drops it
        want = b"".join(want[i : i + 3] for i in range(0, len(want), 4))
    assert got.rgb == want


@pytest.mark.parametrize(
    ("name", "sha", "corner", "hole"),
    [("chromium_element_shot.png",
      "b7134a52907181a259c9b1f26ad8da2285b7b10582200fa27223c04781fa5368",
      (247, 7, 4), (17, 34, 51)),
     ("chromium_canvas_blob.png",
      "6ceb674d26e1d6809777624a207b9b4eacc29bcbe0f7972ce82a4974a096313f",
      (247, 7, 4), (0, 0, 0))],
    ids=["element-screenshot-rgb", "canvas-blob-rgba"],
)  # fmt: skip
def test_a_png_chromium_wrote_reads_as_pillow_read_it(
    name: str, sha: str, corner: tuple[int, int, int], hole: tuple[int, int, int]
) -> None:
    got = read_png((PNGS / name).read_bytes())
    assert got.size == (40, 24)
    assert hashlib.sha256(got.rgb).hexdigest() == sha  # every pixel, as Pillow's convert("RGB")
    assert got.getpixel((0, 0)) == corner and got.getpixel((39, 23)) == (33, 40, 251)
    assert got.getpixel((20, 12)) == (3, 246, 142)
    assert got.getpixel((32, 3)) == hole  # the canvas's cleared hole: the page, or alpha dropped
    assert len(got.colours()) == 640


def _broken(png: bytes, at: int, value: bytes) -> bytes:
    return png[:at] + value + png[at + len(value) :]


def test_what_the_reader_refuses_it_says() -> None:
    rows = _picture(3, 2, 3, seed=1)
    good = _encode(3, rows, 2)
    with pytest.raises(ValueError, match="not a PNG"):
        read_png(b"GIF89a" + good[6:])
    with pytest.raises(ValueError, match="8-bit RGB or RGBA"):
        read_png(_encode(3, [bytes(3)] * 2, 0))  # greyscale
    with pytest.raises(ValueError, match="8-bit RGB or RGBA"):
        read_png(_encode(3, rows, 2, depth=16))
    with pytest.raises(ValueError, match="interlaced"):
        read_png(_encode(3, rows, 2, interlace=1))
    with pytest.raises(ValueError, match="CRC"):
        read_png(_broken(good, 8 + 8 + 13, b"\x00\x00\x00\x00"))  # IHDR's CRC
    with pytest.raises(ValueError, match="filter"):
        raw = zlib.compress(b"\x07" + bytes(9) + b"\x00" + bytes(9))
        ihdr = struct.pack(">IIBBBBB", 3, 2, 8, 2, 0, 0, 0)
        read_png(b"\x89PNG\r\n\x1a\n" + _chunk(b"IHDR", ihdr) + _chunk(b"IDAT", raw)
                 + _chunk(b"IEND", b""))  # fmt: skip
    with pytest.raises(ValueError, match="short"):
        read_png(good[:-20])


def test_the_helpers_the_stage_tests_use() -> None:
    rows = [bytes([10, 20, 30] * 4), bytes([10, 20, 30, 1, 2, 3, 10, 20, 30, 10, 20, 30]),
            bytes([10, 20, 30] * 4)]  # fmt: skip
    img = read_png(_encode(4, rows, 2))
    assert img.size == (4, 3) and img.getpixel((1, 1)) == (1, 2, 3)
    assert img.colours() == {(10, 20, 30), (1, 2, 3)}
    part = img.crop((1, 1, 3, 3))
    assert isinstance(part, Pixels) and part.size == (2, 2) and part.getpixel((0, 0)) == (1, 2, 3)
    assert diff_box(img, img) is None
    other = read_png(_encode(4, [rows[0], rows[0], rows[0]], 2))
    assert diff_box(img, other) == (1, 1, 2, 2)  # as Pillow's ImageChops.difference().getbbox()
    with pytest.raises(IndexError):
        img.getpixel((4, 0))
    with pytest.raises(ValueError):
        img.crop((0, 0, 5, 1))
    with pytest.raises(ValueError):
        diff_box(img, part)


def test_no_module_under_tests_imports_pillow() -> None:
    """GitHub's jobs install `.[dev]` (+ Playwright for the browser job): never Pillow."""
    found = []
    for path in sorted(TESTS.rglob("*.py")):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""]
            else:
                continue
            found += [f"{path.relative_to(TESTS)}: {n}" for n in names if n.split(".")[0] == "PIL"]
    assert found == []
