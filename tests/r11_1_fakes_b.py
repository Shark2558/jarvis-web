# tests/r11_1_fakes_b.py -- R11.1 Part B (Voice and files) helpers: small Excel, PowerPoint, zip
# and picture files built in code, so no real document or photo is ever in the repository. The one
# binary fixture is tests/fixtures/r11_1/b_made_up.xls (a 5 KB made-up Excel 97-2003 workbook: the
# standard library cannot write that format). A plain module: tests import it as `r11_1_fakes_b`.
from __future__ import annotations

import io
import struct
import zipfile
import zlib
from pathlib import Path
from typing import Any

FIXTURES = Path(__file__).parent / "fixtures" / "r11_1"
XLS = FIXTURES / "b_made_up.xls"
MISHEARINGS = FIXTURES / "b_mishearings.json"

# ---- Excel (.xlsx / .xlsm) ----------------------------------------------------------------------


def make_xlsx(sheets: dict[str, list[list[Any]]]) -> bytes:
    """A workbook with these sheets; a cell that starts with "=" is written as a formula."""
    import openpyxl

    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    for title, rows in sheets.items():
        ws = wb.create_sheet(title)
        for row in rows:
            ws.append(row)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def study_plan_xlsx(rows: int = 60) -> bytes:
    plan = [["Session", "Topic", "Date", "Minutes"]]
    plan += [
        [i, f"Made-up topic {i}", f"2026-12-{(i % 28) + 1:02d}", 45] for i in range(1, rows + 1)
    ]
    return make_xlsx(
        {"Plan": plan, "Totals": [["Sessions", rows], ["Minutes", f"=SUM(D2:D{rows + 1})"]]}
    )


def many_sheets_xlsx(count: int) -> bytes:
    return make_xlsx({f"S{i}": [[f"cell {i}"]] for i in range(1, count + 1)})


# ---- PowerPoint (.pptx) -------------------------------------------------------------------------

_A = "http://schemas.openxmlformats.org/drawingml/2006/main"
_P = "http://schemas.openxmlformats.org/presentationml/2006/main"
_REL = "http://schemas.openxmlformats.org/package/2006/relationships"
_NOTES = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/notesSlide"
_HEAD = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
PPTX_TYPES = (
    f'{_HEAD}<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
    '<Default Extension="xml" ContentType="application/xml"/></Types>'
)


def _shapes(paragraphs: list[str]) -> str:
    body = "".join(f"<a:p><a:r><a:t>{p}</a:t></a:r></a:p>" for p in paragraphs)
    return f"<p:cSld><p:spTree><p:sp><p:txBody>{body}</p:txBody></p:sp></p:spTree></p:cSld>"


def _show_order(order: list[int], ns: str) -> dict[str, bytes]:
    """The deck's own slide order (PowerPoint keeps file numbers when slides are moved)."""
    r = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
    ids = "".join(f'<p:sldId id="{255 + n}" r:id="rId{n}"/>' for n in order)
    rels = "".join(
        f'<Relationship Id="rId{n}" Type="{r}/slide" Target="slides/slide{n}.xml"/>' for n in order
    )
    return {
        "ppt/presentation.xml": (
            f'{_HEAD}<p:presentation {ns} xmlns:r="{r}"><p:sldIdLst>{ids}</p:sldIdLst>'
            "</p:presentation>"
        ).encode(),
        "ppt/_rels/presentation.xml.rels": (
            f'{_HEAD}<Relationships xmlns="{_REL}">{rels}</Relationships>'
        ).encode(),
    }


def make_pptx(
    slides: list[tuple[list[str], list[str]]],
    *,
    extra: dict[str, bytes] | None = None,
    order: list[int] | None = None,
) -> bytes:
    """A deck whose slide file N shows `slides[N-1][0]` (one paragraph each) with notes `[1]`;
    `order` is the order the deck shows its slide files in (default: no order written)."""
    ns = f'xmlns:a="{_A}" xmlns:p="{_P}"'
    entries: dict[str, bytes] = {
        "[Content_Types].xml": PPTX_TYPES.encode(),
        "ppt/presentation.xml": f"{_HEAD}<p:presentation {ns}/>".encode(),
    }
    if order:
        entries.update(_show_order(order, ns))
    for i, (text, notes) in enumerate(slides, 1):
        entries[f"ppt/slides/slide{i}.xml"] = f"{_HEAD}<p:sld {ns}>{_shapes(text)}</p:sld>".encode()
        if notes:
            # notes are numbered the other way round on purpose: only the slide's own
            # relationship says which notes page is its own
            n = len(slides) - i + 1
            entries[f"ppt/slides/_rels/slide{i}.xml.rels"] = (
                f'{_HEAD}<Relationships xmlns="{_REL}"><Relationship Id="rId1" Type="{_NOTES}" '
                f'Target="../notesSlides/notesSlide{n}.xml"/></Relationships>'
            ).encode()
            entries[f"ppt/notesSlides/notesSlide{n}.xml"] = (
                f"{_HEAD}<p:notes {ns}>{_shapes(notes)}</p:notes>".encode()
            )
    entries.update(extra or {})
    return make_zip(entries)


# ---- zip ----------------------------------------------------------------------------------------


def make_zip(entries: dict[str, bytes], *, stored: bool = False) -> bytes:
    buf = io.BytesIO()
    how = zipfile.ZIP_STORED if stored else zipfile.ZIP_DEFLATED
    with zipfile.ZipFile(buf, "w", how) as z:
        for name, data in entries.items():
            z.writestr(name, data)
    return buf.getvalue()


def zip_bomb(megabytes: int = 60) -> bytes:
    """A few KB that unpack to `megabytes` of zeros in one member (a classic bomb)."""
    return make_zip({"notes.txt": b"hello", "big.csv": b"0" * (megabytes * 1024 * 1024)})


def nested_zip() -> bytes:
    return make_zip({"a.txt": b"outer", "inner.zip": make_zip({"b.txt": b"inner"})})


def escaping_zip(name: str = "../../outside.txt") -> bytes:
    return make_zip({"ok.txt": b"fine", name: b"escaped"})


def encrypted_zip() -> bytes:
    """A zip whose only member has the "encrypted" flag set (no real cipher is needed)."""
    raw = bytearray(make_zip({"secret.txt": b"hidden words"}, stored=True))
    local = raw.find(b"PK\x03\x04")
    central = raw.find(b"PK\x01\x02")
    raw[local + 6] |= 0x01
    raw[central + 8] |= 0x01
    return bytes(raw)


# ---- pictures (never a photo: a few made-up bytes with the right structure) ----------------------


def _chunk(kind: bytes, body: bytes) -> bytes:
    return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body))


def make_png(
    width: int = 8,
    height: int = 6,
    *,
    text: bytes | None = None,
    declared: tuple[int, int] | None = None,
) -> bytes:
    """A real, decodable grey PNG of `width` x `height`; `text` adds a tEXt chunk (metadata);
    `declared` writes other dimensions into the header than the pixels really have."""
    w, h = declared or (width, height)
    ihdr = struct.pack(">IIBBBBB", w, h, 8, 0, 0, 0, 0)
    rows = b"".join(
        b"\x00" + bytes((x * 7 + y * 13) % 256 for x in range(width)) for y in range(height)
    )
    out = b"\x89PNG\r\n\x1a\n" + _chunk(b"IHDR", ihdr)
    if text is not None:
        out += _chunk(b"tEXt", b"Comment\x00" + text)
        out += _chunk(b"eXIf", b"Exif\x00\x00" + text)
    return out + _chunk(b"IDAT", zlib.compress(rows)) + _chunk(b"IEND", b"")


def _seg(marker: int, payload: bytes) -> bytes:
    return bytes([0xFF, marker]) + struct.pack(">H", len(payload) + 2) + payload


def make_jpeg(
    width: int = 64, height: int = 48, *, exif: bytes | None = None, pad: int = 0
) -> bytes:
    """A structurally valid baseline JPEG (the server checks structure; it never decodes).
    `exif` adds an APP1 segment; `pad` adds that many bytes of scan data."""
    out = b"\xff\xd8"
    if exif is not None:
        out += _seg(0xE1, b"Exif\x00\x00" + exif)
    out += _seg(0xDB, b"\x00" + bytes(64))
    out += _seg(0xC0, struct.pack(">BHHB", 8, height, width, 1) + b"\x01\x11\x00")
    out += _seg(0xDA, b"\x01\x01\x00\x00\x3f\x00") + b"\x12\x34\x56" + b"\x11" * pad
    return out + b"\xff\xd9"


# ---- hostile and slow inputs --------------------------------------------------------------------


def slow_xlsx(megabytes: int = 9) -> bytes:
    """A workbook whose one sheet is `megabytes` of real rows, stored uncompressed (so it is not
    a zip bomb): reading it takes a child process several seconds."""
    row = '<row><c t="inlineStr"><is><t>made-up words</t></is></c><c><v>42</v></c></row>'
    count = megabytes * 1024 * 1024 // len(row)
    sheet = (
        '<?xml version="1.0" encoding="UTF-8"?><worksheet xmlns="http://schemas.openxmlformats.org'
        '/spreadsheetml/2006/main"><sheetData>' + row * count + "</sheetData></worksheet>"
    ).encode()
    buf = io.BytesIO()
    with (
        zipfile.ZipFile(io.BytesIO(make_xlsx({"Big": [["x"]]}))) as src,
        zipfile.ZipFile(buf, "w") as dst,
    ):
        for info in src.infolist():
            if info.filename == "xl/worksheets/sheet1.xml":
                dst.writestr(zipfile.ZipInfo(info.filename), sheet, zipfile.ZIP_STORED)
            else:
                dst.writestr(info.filename, src.read(info))
    return buf.getvalue()


def alive(pid: int) -> bool:
    """Is that process still running? (A zombie is not: it only waits to be reaped.)"""
    import os

    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    try:
        with open(f"/proc/{pid}/stat") as f:
            return f.read().split(")")[-1].split()[0] != "Z"
    except OSError:
        return False


__all__ = [
    "FIXTURES",
    "MISHEARINGS",
    "XLS",
    "alive",
    "encrypted_zip",
    "escaping_zip",
    "make_jpeg",
    "make_png",
    "make_pptx",
    "make_xlsx",
    "make_zip",
    "many_sheets_xlsx",
    "nested_zip",
    "slow_xlsx",
    "study_plan_xlsx",
    "zip_bomb",
]
