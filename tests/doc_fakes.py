# tests/doc_fakes.py — slice 10 E helpers: tiny PDF / DOCX / zip files built in code (no binary
# fixtures in the repo). A plain module (not conftest) so test files import it directly.
from __future__ import annotations

import io
import zipfile

CONTENT_TYPES = (
    b'<?xml version="1.0" encoding="UTF-8"?><Types xmlns="http://schemas.openxmlformats.org/'
    b'package/2006/content-types"></Types>'
)


def _pdf_string(line: str) -> bytes:
    raw = line.encode("cp1252", errors="replace")
    return b"(" + raw.replace(b"\\", b"\\\\").replace(b"(", b"\\(").replace(b")", b"\\)") + b")"


def _page_content(text: str) -> bytes:
    if not text:
        return b""
    lines = [_pdf_string(ln) + b" Tj T*" for ln in text.split("\n")]
    return b"BT /F1 11 Tf 14 TL 72 760 Td " + b" ".join(lines) + b" ET"


def make_pdf(pages: list[str]) -> bytes:
    """A small valid PDF: Helvetica text, one text line per line of each page string. An empty
    string is a page without text (what a scan looks like to a text extractor)."""
    n = len(pages)
    kids = " ".join(f"{4 + 2 * i} 0 R" for i in range(n))
    objs: list[bytes] = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        f"<< /Type /Pages /Kids [{kids}] /Count {n} >>".encode(),
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>",
    ]
    for i, text in enumerate(pages):
        content = _page_content(text)
        objs.append(
            (
                "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
                f"/Resources << /Font << /F1 3 0 R >> >> /Contents {5 + 2 * i} 0 R >>"
            ).encode()
        )
        objs.append(b"<< /Length %d >>\nstream\n" % len(content) + content + b"\nendstream")
    out = bytearray(b"%PDF-1.4\n")
    offsets: list[int] = []
    for k, body in enumerate(objs, 1):
        offsets.append(len(out))
        out += f"{k} 0 obj\n".encode() + body + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode()
    for off in offsets:
        out += f"{off:010d} 00000 n \n".encode()
    out += f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    return bytes(out)


def encrypt_pdf(data: bytes, *, user_password: str = "secret") -> bytes:
    from pypdf import PdfReader, PdfWriter

    w = PdfWriter(clone_from=PdfReader(io.BytesIO(data)))
    w.encrypt(user_password=user_password, owner_password="owner-only", algorithm="AES-128")
    buf = io.BytesIO()
    w.write(buf)
    return buf.getvalue()


def make_docx(paragraphs: list[str], table: list[list[str]] | None = None) -> bytes:
    import docx

    d = docx.Document()
    for p in paragraphs:
        d.add_paragraph(p)
    if table:
        t = d.add_table(rows=len(table), cols=len(table[0]))
        for r, row in enumerate(table):
            for c, cell in enumerate(row):
                t.cell(r, c).text = cell
        d.add_paragraph("After the table.")
    buf = io.BytesIO()
    d.save(buf)
    return buf.getvalue()


def make_zip(entries: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in entries.items():
            z.writestr(name, data)
    return buf.getvalue()


def docx_bomb(uncompressed: int) -> bytes:
    """A .docx-shaped zip whose document.xml inflates to `uncompressed` bytes (~1000×)."""
    body = b"<w:document>" + b" " * uncompressed + b"</w:document>"
    return make_zip({"[Content_Types].xml": CONTENT_TYPES, "word/document.xml": body})


OLE_MAGIC = bytes.fromhex("D0CF11E0A1B11AE1")
