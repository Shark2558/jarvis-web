# evals/documents/fixtures.py
"""Files for the slice 10 E document evals, built in code (no binary fixtures in the repo):
a minimal Helvetica PDF writer, python-docx documents, encrypted PDFs, zip bombs, and the
100-page manual with planted facts for the recall suite. Self-contained (evals never import
from tests/)."""

from __future__ import annotations

import io
import random
import zipfile

CONTENT_TYPES = (
    b'<?xml version="1.0" encoding="UTF-8"?><Types xmlns="http://schemas.openxmlformats.org/'
    b'package/2006/content-types"></Types>'
)
OLE_MAGIC = bytes.fromhex("D0CF11E0A1B11AE1")


def _pdf_string(line: str) -> bytes:
    raw = line.encode("cp1252", errors="replace")
    return b"(" + raw.replace(b"\\", b"\\\\").replace(b"(", b"\\(").replace(b")", b"\\)") + b")"


def make_pdf(pages: list[str]) -> bytes:
    """A valid PDF with one Helvetica text line per line of each page ("" = no text layer)."""
    n = len(pages)
    kids = " ".join(f"{4 + 2 * i} 0 R" for i in range(n))
    objs: list[bytes] = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        f"<< /Type /Pages /Kids [{kids}] /Count {n} >>".encode(),
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>",
    ]
    for i, text in enumerate(pages):
        lines = [_pdf_string(ln) + b" Tj T*" for ln in text.split("\n")] if text else []
        content = b"BT /F1 11 Tf 14 TL 72 760 Td " + b" ".join(lines) + b" ET" if lines else b""
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
    body = b"<w:document>" + b" " * uncompressed + b"</w:document>"
    return make_zip({"[Content_Types].xml": CONTENT_TYPES, "word/document.xml": body})


def docx_many_entries(n: int) -> bytes:
    entries = {f"word/media/{i}.xml": b"<x/>" for i in range(n)}
    return make_zip({"[Content_Types].xml": CONTENT_TYPES, "word/document.xml": b"<x/>"} | entries)


# ---- the 100-page manual (recall suite) ----------------------------------------------------------

FILLER = [
    "The registry team reviews progress with each department every week.",
    "Each department nominates a nodal officer for the programme.",
    "Contract value is reviewed by the finance wing at each milestone.",
    "Officers record field notes in the mobile app during visits.",
    "The steering committee meets once a month to review risks.",
    "Data quality reports are shared with district collectors.",
    "Training material is published on the programme portal.",
    "Every change to the schema is logged and approved.",
    "The help desk logs every call with a ticket number.",
    "Backups are verified by the operations team.",
    "Vendors submit monthly progress reports to the programme office.",
    "District teams reconcile records with the department registers.",
    "Security reviews follow the state IT policy.",
    "Incidents are classified by severity before they are assigned.",
    "The annex lists the warranty terms for all hardware.",
    "Payment requests are checked against delivered milestones.",
    "Officers may ask the programme office for more training.",
    "Grievances raised by citizens are tracked on the portal.",
    "Audit observations are closed with evidence of the fix.",
    "Interface text is reviewed by the language cell.",
]

PLANTED: list[tuple[str, str, str]] = [
    (
        "R01",
        "The warranty period for the turbine gearbox is 36 months.",
        "How long is the gearbox warranty?",
    ),
    (
        "R02",
        "Late delivery attracts liquidated damages of 0.5 percent per week.",
        "What are the liquidated damages for late delivery?",
    ),
    (
        "R03",
        "The data centre in Kochi must keep backups for 7 years.",
        "How many years must the Kochi data centre keep backups?",
    ),
    (
        "R04",
        "Payment milestones are 30, 40 and 30 percent of the contract value.",
        "What are the payment milestones as a share of contract value?",
    ),
    (
        "R05",
        "The vendor must respond to severity one incidents within 15 minutes.",
        "What is the response time for severity one incidents?",
    ),
    (
        "R06",
        "Training for district officers will be held in Thrissur in March.",
        "Where will the district officers' training be held?",
    ),
    (
        "R07",
        "Linked records are stored in the registry only in encrypted form.",
        "Are linked records stored encrypted?",
    ),
    (
        "R08",
        "Source code escrow is held by the state data centre.",
        "Who holds the source code escrow?",
    ),
    ("R09", "The uptime commitment is 99.5 percent measured monthly.", "What uptime is committed?"),
    (
        "R10",
        "Change requests above 50 lakh rupees need steering committee approval.",
        "Which change requests need steering committee approval?",
    ),
    (
        "R11",
        "Exit management requires a handover period of 90 days.",
        "How long is the exit management handover?",
    ),
    (
        "R12",
        "The help desk operates from 8 am to 8 pm on working days.",
        "What hours does the help desk operate?",
    ),
    (
        "R13",
        "Penetration testing is done twice a year by an empanelled auditor.",
        "How often is penetration testing done?",
    ),
    (
        "R14",
        "Malayalam and English are the two supported interface languages.",
        "Which interface languages are supported?",
    ),
    (
        "R15",
        "The performance bank guarantee is 5 percent of the contract value.",
        "How much is the performance bank guarantee?",
    ),
    (
        "R16",
        "Field verification visits are capped at 40 per officer per month.",
        "What is the cap on field verification visits?",
    ),
    (
        "R17",
        "Disaster recovery drills happen every quarter.",
        "How frequent are the disaster recovery drills?",
    ),
    (
        "R18",
        "The mobile app must work offline for up to 72 hours.",
        "How long must the mobile app work offline?",
    ),
    (
        "R19",
        "Citizen grievances must be closed within 21 days.",
        "Within how many days must citizen grievances be closed?",
    ),
    (
        "R20",
        "Audit logs are retained for 10 years in write-once storage.",
        "How long are audit logs retained?",
    ),
]


def manual_pages(n_pages: int = 100) -> tuple[list[str], dict[str, int]]:
    """`n_pages` pages of filler with each planted fact (and its marker) on its own page."""
    rnd = random.Random(1010)
    pages: list[str] = []
    for p in range(1, n_pages + 1):
        lines = [f"Operations manual, page {p}."]
        lines += [rnd.choice(FILLER) for _ in range(14)]
        pages.append("\n".join(lines))
    where: dict[str, int] = {}
    for i, (marker, fact, _) in enumerate(PLANTED):
        page = 3 + i * 5  # pages 3, 8, 13, … 98
        lines = pages[page - 1].split("\n")
        lines.insert(7, f"{fact} [{marker}]")
        pages[page - 1] = "\n".join(lines)
        where[marker] = page
    return pages, where


__all__ = [
    "CONTENT_TYPES",
    "OLE_MAGIC",
    "PLANTED",
    "docx_bomb",
    "docx_many_entries",
    "encrypt_pdf",
    "make_docx",
    "make_pdf",
    "make_zip",
    "manual_pages",
]
