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

# ---- raw WordprocessingML (security review probes, rebuilt in code) -----------------------------
_W = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'
_CT_FULL = (
    '<?xml version="1.0" encoding="UTF-8"?><Types xmlns="http://schemas.openxmlformats.org/'
    'package/2006/content-types"><Default Extension="rels" ContentType="application/'
    'vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType='
    '"application/xml"/><Override PartName="/word/document.xml" ContentType="application/'
    'vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>'
)
_RELS = (
    '<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.openxmlformats.org'
    '/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/'
    'officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/></Relationships>'
)


def raw_docx(body: str) -> bytes:
    """A minimal valid .docx around a hand-written <w:body>."""
    head = '<?xml version="1.0" encoding="UTF-8"?>'
    doc = f"{head}<w:document {_W}><w:body>{body}</w:body></w:document>"
    return make_zip(
        {
            "[Content_Types].xml": _CT_FULL.encode(),
            "_rels/.rels": _RELS.encode(),
            "word/document.xml": doc.encode(),
        }
    )


def vmerge_docx(rows: int, cols: int) -> bytes:
    """A table whose every column is one vertically merged cell (python-docx's row.cells is
    quadratic on these)."""
    trs = []
    for r in range(rows):
        vm = '<w:vMerge w:val="restart"/>' if r == 0 else "<w:vMerge/>"
        word = "top" if r == 0 else ""
        cell = f"<w:tc><w:tcPr>{vm}</w:tcPr><w:p><w:r><w:t>{word}</w:t></w:r></w:p></w:tc>"
        tcs = cell * cols
        trs.append(f"<w:tr>{tcs}</w:tr>")
    grid = '<w:gridCol w:w="100"/>' * cols
    return raw_docx(
        f"<w:tbl><w:tblGrid>{grid}</w:tblGrid>{''.join(trs)}</w:tbl><w:p><w:r><w:t>end</w:t></w:r></w:p>"
    )


def table_docx(rows: int, cols: int) -> bytes:
    trs = "".join(
        "<w:tr>"
        + "".join(f"<w:tc><w:p><w:r><w:t>c{r}x{c}</w:t></w:r></w:p></w:tc>" for c in range(cols))
        + "</w:tr>"
        for r in range(rows)
    )
    grid = '<w:gridCol w:w="100"/>' * cols
    return raw_docx(f"<w:tbl><w:tblGrid>{grid}</w:tblGrid>{trs}</w:tbl>")


def empty_paragraphs_docx(xml_bytes: int) -> bytes:
    """Mostly empty paragraphs with random rsids (compresses only ~4×, parses to ~18× in lxml)."""
    import secrets

    one = len('<w:p w:rsidR="00000000"/>')
    body = "".join(
        f'<w:p w:rsidR="{secrets.token_hex(4).upper()}"/>' for _ in range(xml_bytes // one)
    )
    return raw_docx(body + "<w:p><w:r><w:t>end</w:t></w:r></w:p>")
