# tests/browser/test_r7_i1_exif.py -- R7 I1 (Workshop decision, INTEGRATION-B "Needs I1" 13):
# R11.1's `shrink`, which I0's one picture door (`console-r7-send.js`: Ask, Vault, Attach) and the
# composer use, REDRAWS every picture before it leaves the browser, so no camera or location data
# travels: a small JPEG carrying a GPS tag comes out as a new JPEG without it; a small PNG comes out
# as a new, lossless PNG without its text chunks; the vault path gets the clean bytes too.
from __future__ import annotations

import base64
import struct
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from test_console import DESKTOP
from test_r11_1_b_files import Page

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from r11_1_fakes_b import make_png  # noqa: E402

_pw = pytest.importorskip("playwright.sync_api")
sync_playwright = _pw.sync_playwright
pytestmark = pytest.mark.browser

MARK = b"GPS-LAT-12.97-LON-77.59"


def gps_app1() -> bytes:
    """An APP1 "Exif" segment (little-endian TIFF): ImageDescription = MARK, and a GPS IFD with
    GPSLatitudeRef N and GPSLatitude 12 deg 58 min 12 s (made-up numbers, nobody's place)."""
    desc = MARK + b"\x00"
    ifd0 = struct.pack("<H", 2)
    ifd0 += struct.pack("<HHII", 0x010E, 2, len(desc), 38)  # the description, at 38
    ifd0 += struct.pack("<HHII", 0x8825, 4, 1, 62)  # the GPS IFD, at 62
    ifd0 += struct.pack("<I", 0)
    gps = struct.pack("<H", 2)
    gps += struct.pack("<HHI", 1, 2, 2) + b"N\x00\x00\x00"
    gps += struct.pack("<HHII", 2, 5, 3, 92)  # three rationals, at 92
    gps += struct.pack("<I", 0)
    rationals = struct.pack("<IIIIII", 12, 1, 58, 1, 1200, 100)
    tiff = b"II*\x00" + struct.pack("<I", 8) + ifd0 + desc + gps + rationals
    assert len(b"II*\x00") + 4 + len(ifd0) == 38 and 38 + len(desc) + len(gps) == 92
    payload = b"Exif\x00\x00" + tiff
    return b"\xff\xe1" + struct.pack(">H", len(payload) + 2) + payload


# A small JPEG drawn in the page, with the APP1 above put right after its SOI marker.
JPEG_WITH_GPS = """async (b64) => {
  const c = document.createElement('canvas'); c.width = 64; c.height = 48;
  const g = c.getContext('2d'); g.fillStyle = '#5a7896'; g.fillRect(0, 0, 64, 48);
  const blob = await new Promise((r) => c.toBlob(r, 'image/jpeg', 0.9));
  const jpg = new Uint8Array(await blob.arrayBuffer());
  const app1 = Uint8Array.from(atob(b64), (ch) => ch.charCodeAt(0));
  const out = new Uint8Array(jpg.length + app1.length);
  out.set(jpg.subarray(0, 2)); out.set(app1, 2); out.set(jpg.subarray(2), 2 + app1.length);
  window.__gpsJpeg = new File([out], 'IMG_0001.jpg', { type: 'image/jpeg' });
  return btoa(String.fromCharCode(...out));
}"""
SHRUNK = """async (name) => {
  const f = name === 'jpeg' ? window.__gpsJpeg : window.__png;
  const out = await window.JarvisFixes.parts.files.shrink(f);
  const bytes = new Uint8Array(await out.arrayBuffer());
  let s = ''; for (const b of bytes) s += String.fromCharCode(b);
  return { same: out === f, name: out.name, type: out.type, b64: btoa(s) };
}"""


@pytest.fixture(scope="module")
def browser() -> Iterator[Any]:
    with sync_playwright() as p:
        b = p.chromium.launch()
        yield b
        b.close()


@pytest.fixture
def console(browser: Any, server_url: str, token: str) -> Iterator[Page]:
    c = Page(browser, server_url, token, DESKTOP)
    c.open()
    c.page.wait_for_function("window.JarvisFixes && window.JarvisFixes.parts.files")
    yield c
    c.close()


def _jpeg(c: Page) -> bytes:
    raw = base64.b64decode(c.page.evaluate(JPEG_WITH_GPS, base64.b64encode(gps_app1()).decode()))
    assert raw.startswith(b"\xff\xd8\xff\xe1") and MARK in raw and b"Exif\x00\x00" in raw
    return raw


def test_a_small_jpeg_with_a_gps_tag_is_redrawn_without_it(console: Page) -> None:
    raw = _jpeg(console)
    got = console.page.evaluate(SHRUNK, "jpeg")
    out = base64.b64decode(got["b64"])
    assert got["same"] is False and got["type"] == "image/jpeg" and got["name"] == "IMG_0001.jpg"
    assert out.startswith(b"\xff\xd8\xff") and out != raw
    assert b"Exif" not in out and MARK not in out
    assert struct.pack("<IIIIII", 12, 1, 58, 1, 1200, 100) not in out  # no GPS rational left


def test_a_small_png_is_redrawn_as_a_lossless_png_without_its_text(console: Page) -> None:
    png = make_png(16, 16, text=MARK)
    console.page.evaluate(
        "(b64) => { const b = Uint8Array.from(atob(b64), (c) => c.charCodeAt(0));"
        " window.__png = new File([b], 'icon.png', { type: 'image/png' }); }",
        base64.b64encode(png).decode(),
    )
    got = console.page.evaluate(SHRUNK, "png")
    out = base64.b64decode(got["b64"])
    assert got["same"] is False and got["type"] == "image/png" and got["name"] == "icon.png"
    assert out.startswith(b"\x89PNG\r\n\x1a\n") and MARK not in out and b"tEXt" not in out


def test_the_one_doors_vault_path_sends_the_redrawn_bytes(console: Page) -> None:
    _jpeg(console)
    sent: list[bytes] = []

    def vault(route: Any) -> None:
        sent.append(route.request.post_data_buffer or b"")
        route.fulfill(status=503, content_type="application/json", body='{"detail": "off"}')

    console.page.route("**/v1/vault/upload", vault)
    console.page.evaluate(
        "async () => { try { await JarvisMobile.parts.send.vault(window.__gpsJpeg); }"
        " catch (_) {} }"
    )
    (body,) = sent
    assert body.startswith(b"\xff\xd8\xff") and b"Exif" not in body and MARK not in body


# ---- Workshop decision (I1 fixer, security M1): a picture that cannot be redrawn is never sent ----------------
UNPREPARED = "That picture could not be prepared on this device, so it was not sent, Sir."
# A JPEG the canvas cannot decode, with a GPS APP1 in front: the original bytes must never leave.
BAD_JPEG = """(b64) => {
  const app1 = Uint8Array.from(atob(b64), (ch) => ch.charCodeAt(0));
  const junk = new Uint8Array(200).fill(7);
  const out = new Uint8Array(2 + app1.length + junk.length);
  out.set([0xff, 0xd8]); out.set(app1, 2); out.set(junk, 2 + app1.length);
  window.__badJpeg = new File([out], 'IMG_0002.jpg', { type: 'image/jpeg' });
  return true;
}"""


def _bad_jpeg(c: Page) -> None:
    c.page.evaluate(BAD_JPEG, base64.b64encode(gps_app1()).decode())


def test_shrink_signals_failure_for_a_picture_the_canvas_cannot_decode(console: Page) -> None:
    _bad_jpeg(console)
    got = console.page.evaluate(
        "async () => { const out = await window.JarvisFixes.parts.files.shrink(window.__badJpeg);"
        " return { isNull: out === null, same: out === window.__badJpeg }; }"
    )
    assert got == {"isNull": True, "same": False}


def test_the_one_door_refuses_an_undecodable_picture_and_nothing_is_posted(console: Page) -> None:
    _bad_jpeg(console)
    posted: list[str] = []
    console.page.route("**/v1/vault/upload", lambda r: (posted.append(r.request.url), r.abort()))
    console.page.route("**/v1/attachments", lambda r: (posted.append(r.request.url), r.abort()))
    got = console.page.evaluate(
        "async () => { const r = {};"
        " for (const k of ['vault', 'attach']) {"
        "   try { await JarvisMobile.parts.send[k](k === 'attach' ? [window.__badJpeg] : window.__badJpeg); r[k] = 'sent'; }"
        "   catch (e) { r[k] = e.message; } }"
        " return r; }"
    )
    assert got == {"vault": UNPREPARED, "attach": UNPREPARED}
    assert posted == []


def test_the_composer_clip_refuses_an_undecodable_picture_in_plain_words(console: Page) -> None:
    _bad_jpeg(console)
    posted: list[str] = []
    console.page.route("**/v1/attachments", lambda r: (posted.append(r.request.url), r.abort()))
    console.page.evaluate("() => window.JarvisAttach.add([window.__badJpeg])")
    console.page.locator("#attachErr").filter(has_text=UNPREPARED).wait_for()
    console.page.wait_for_timeout(300)
    assert posted == [] and console.page.locator("#attachChips .achip").count() == 0


def test_a_folder_leaves_out_a_picture_it_cannot_redraw(console: Page) -> None:
    _bad_jpeg(console)
    got = console.page.evaluate(
        "async () => { const f = window.__badJpeg; Object.defineProperty(f, 'webkitRelativePath', { value: 'trip/IMG_0002.jpg' });"
        " const t = new File(['hello'], 'note.txt', { type: 'text/plain' });"
        " Object.defineProperty(t, 'webkitRelativePath', { value: 'trip/note.txt' });"
        " const r = await window.JarvisFixes.parts.files.folder([f, t]);"
        " const s = new TextDecoder('latin1').decode(new Uint8Array(await r.blob.arrayBuffer()));"
        " return { count: r.count, left: r.left, hasJpg: s.includes('IMG_0002'), hasGps: s.includes('GPS-LAT') }; }"
    )
    assert got["count"] == 1 and not got["hasJpg"] and not got["hasGps"]
    assert any("IMG_0002.jpg" in x for x in got["left"])
