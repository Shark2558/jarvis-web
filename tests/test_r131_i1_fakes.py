# tests/test_r131_i1_fakes.py -- R13.1 I1: the fakes D's browser tests and screenshots read must
# have the real shapes. The fake picture is a PNG a browser can decode (INTEGRATION-D section 7:
# I0's was a signature and text, so the picture showed as broken), and the fake server's consent
# version is "c2-" + 12 hex, as C's real one is (INTEGRATION-C 10.4 a).
from __future__ import annotations

import re
import struct
import zlib

from r131_fake_seeme import CONSENT_VERSION
from r131_fake_tryon import PNG

from jarvis.wardrobe.tryon.http_seeme import ConsentIn


def _chunks(data: bytes) -> list[tuple[bytes, bytes]]:
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    out, at = [], 8
    while at < len(data):
        (size,) = struct.unpack(">I", data[at : at + 4])
        kind, body = data[at + 4 : at + 8], data[at + 8 : at + 8 + size]
        (crc,) = struct.unpack(">I", data[at + 8 + size : at + 12 + size])
        assert zlib.crc32(kind + body) == crc, kind
        out.append((kind, body))
        at += 12 + size
    return out


def test_the_fake_picture_is_a_png_a_browser_can_decode() -> None:
    chunks = _chunks(PNG)
    kinds = [k for k, _ in chunks]
    assert kinds[0] == b"IHDR" and kinds[-1] == b"IEND" and b"IDAT" in kinds
    w, h, depth, colour, comp, filt, lace = struct.unpack(">IIBBBBB", chunks[0][1])
    assert (depth, colour, comp, filt, lace) == (8, 2, 0, 0, 0)  # 8-bit RGB, no interlace
    assert 64 <= w <= 512 and 64 <= h <= 512  # a small drawn picture, portrait
    raw = zlib.decompress(b"".join(b for k, b in chunks if k == b"IDAT"))
    assert len(raw) == h * (1 + 3 * w)  # every row: a filter byte, then its pixels
    rows = [raw[y * (1 + 3 * w) : (y + 1) * (1 + 3 * w)] for y in range(h)]
    assert all(r[0] == 0 for r in rows)
    assert len({r[1:] for r in rows}) > 2  # drawn, not one flat colour
    assert len(PNG) < 16_000  # small enough for a test page


def test_the_fake_servers_consent_version_has_the_real_shape() -> None:
    assert re.fullmatch(r"c2-[0-9a-f]{12}", CONSENT_VERSION)
    ConsentIn(typed="YES", template_version=CONSENT_VERSION)  # the contract takes it


def test_importing_ds_fakes_leaves_i0s_photo_views_alone() -> None:
    """I1: D's fakes added its photos to I0's shared `VIEW_OF` at import, so any test module that
    imported them (the door's) broke A's fakes later in the same run (a KeyError on D's watch
    photo, 150 of A's tests). D's server process adds them when it builds its app."""
    import r131_fakes
    import r131_fakes_d  # noqa: F401 - the import is the test

    assert set(r131_fakes.VIEW_OF) == {
        "wh_00000000a001", "wh_00000000a002", "wh_00000000b001", "wh_00000000b002",
    }  # fmt: skip
