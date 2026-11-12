# src/jarvis/documents/extract.py
"""Text out of an attached file (slice 10 E, D-E1). Pure and synchronous; in the app it runs only
inside the extraction worker, a child process per upload with CPU and memory limits
(`jarvis.documents.worker`). Model-agnostic: the model only ever sees the text.

    kind_for(name)      the type, from the extension (PDF, DOCX, TXT, MD, CSV; R11.1: XLSX /
                        XLSM, XLS, PPTX, PNG / JPG, ZIP) — else refused
    sniff(data, kind)   the bytes must agree: %PDF- for a PDF, a zip for a DOCX / XLSX / PPTX /
                        ZIP (an OLE file there is password-protected or an old format), an OLE
                        file for an XLS, the PNG or JPEG signature for a picture, no binary
                        signature for text
    extract(...)        pypdf (BSD-3) for PDF, python-docx (MIT; lxml with entities off) for
                        DOCX, UTF-8 / UTF-16 BOM / cp1252 / latin-1 for text; nothing is executed.
                        R11.1 (D10-D11): `sheets` (openpyxl, xlrd: values, never formulas),
                        `slides` (lxml, entities off), `archive` (zip / folder: members one by
                        one, never a nested archive) and `imagecheck` (structure only, no decoder)

Limits (`Limits`): ≤ 300 PDF pages read, ≤ 300,000 characters kept, a time budget checked
between pages, paragraphs and table rows (what was read in time is kept, marked truncated), and
for a DOCX the zip's central directory is checked BEFORE any XML is parsed: ≤ 1,000 entries,
≤ 50 MB unpacked in all, ≤ 10 MB of XML (lxml needs ~18× that in memory), no entry over 1 MB
packed more than 100×. Declared sizes bound what zipfile inflates (it stops at the declared size
and fails the CRC). Tables are read straight from their XML (python-docx's merged-cell lookup is
quadratic). All clean-up is linear in the text. Running out of memory is "too complex". No OCR:
a PDF without a text layer is "no text found". Every refusal is a `DocumentRejected` with a
plain message; any other exception from a hostile file becomes "unreadable", never a crash.

Imports: the standard library and `jarvis.documents.limits` only (pypdf / python-docx lazily),
so the worker starts fast and small.
"""

from __future__ import annotations

import codecs
import io
import logging
import re
import time
import zipfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any

from jarvis.documents.limits import (
    EXTENSIONS,
    MAX_CHARS,
    MAX_PAGES,
    MAX_PICTURES,
    MAX_SHEET_ROWS,
    MAX_SHEETS,
    MAX_TOTAL_BYTES,
    PICTURE_MAX_BYTES,
    SUPPORTED_WORDS,
    ZIP_MAX_FILES,
    DocumentRejected,
    Kind,
)

EXTRACT_BUDGET_S = 20.0
ZIP_MAX_ENTRIES = 1_000
ZIP_MAX_TOTAL = 50 * 1024 * 1024
ZIP_MAX_XML = 10 * 1024 * 1024
ZIP_MAX_RATIO = 100
ZIP_RATIO_FLOOR = 1024 * 1024  # smaller entries may compress as well as they like
PDF_MAGIC_WINDOW = 1024  # readers accept a little junk before %PDF-
CONTROL_SHARE = 0.01  # more control characters than this: not a text file
_W_NS = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"

_ZIP = b"PK\x03\x04"
_OLE = bytes.fromhex("D0CF11E0A1B11AE1")
_PNG = b"\x89PNG\r\n\x1a\n"
_JPEG = b"\xff\xd8\xff"
_ZIPPED: frozenset[str] = frozenset({"docx", "xlsx", "pptx", "zip", "folder"})
_XML_PARTS = (".xml", ".rels", ".vml")
_DTD = (b"<!DOCTYPE", b"<!ENTITY")
_BINARY: tuple[bytes, ...] = (
    b"%PDF-",
    _ZIP,
    b"PK\x05\x06",
    _OLE,
    b"\x89PNG",
    b"\xff\xd8\xff",
    b"GIF8",
    b"\x1f\x8b",
    b"7z\xbc\xaf",
    b"Rar!",
)
# the same characters `jarvis.tools.external.clean_text` removes (kept here: no app imports)
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]")
_SURROGATE = re.compile("[\ud800-\udfff]")
_BLANK_RUN = re.compile(r"\n{3,}")
_XML_ENCODING = re.compile(rb"""encoding\s*=\s*["']([A-Za-z0-9._\-]+)["']""")

logging.getLogger("pypdf").setLevel(logging.ERROR)  # a hostile file must not flood the logs

Clock = Callable[[], float]


@dataclass(frozen=True)
class Limits:
    max_pages: int = MAX_PAGES
    max_chars: int = MAX_CHARS
    budget_s: float = EXTRACT_BUDGET_S
    zip_max_entries: int = ZIP_MAX_ENTRIES
    zip_max_total: int = ZIP_MAX_TOTAL
    zip_max_xml: int = ZIP_MAX_XML
    zip_max_ratio: int = ZIP_MAX_RATIO
    # R11.1 D10-D11: workbooks, archives and pictures
    max_sheets: int = MAX_SHEETS
    max_sheet_rows: int = MAX_SHEET_ROWS
    archive_max_files: int = ZIP_MAX_FILES  # files read from one zip or folder
    archive_max_total: int = MAX_TOTAL_BYTES  # everything a zip or folder unpacks to
    picture_max_bytes: int = PICTURE_MAX_BYTES
    max_pictures: int = MAX_PICTURES


@dataclass(frozen=True)
class Picture:
    """A picture whose structure was checked and whose metadata was removed (never decoded)."""

    name: str
    media_type: str  # image/jpeg | image/png
    data: bytes


@dataclass(frozen=True)
class Extracted:
    kind: str
    text: str
    pages: int | None = None  # PDF: pages read
    pages_total: int | None = None  # PDF: pages the file says it has
    page_starts: tuple[int, ...] = ()  # PDF: where each page read begins in `text`
    truncated: bool = False
    sheets: int | None = None  # a workbook's sheets
    rows: int | None = None  # a workbook's rows read
    slides: int | None = None  # a deck's slides
    files: int | None = None  # a zip's or folder's files read
    skipped: int = 0  # a zip's or folder's files not read (each said in the text)
    pictures: tuple[Picture, ...] = ()


# ---- plain messages -----------------------------------------------------------------------------

ENCRYPTED_PDF = (
    "This PDF is password-protected. Remove the password (save or print it as a new PDF) and "
    "attach it again."
)
ENCRYPTED_DOCX = (
    "This Word file is password-protected, or it is an old .doc file. Remove the password, or "
    "save it as .docx, and attach it again."
)
NO_TEXT_PDF = (
    "No text found in this PDF. It looks like a scan or a picture of text, and JARVIS can't read "
    "scans yet."
)
TOO_COMPLEX = (
    "This file is too large or unusual to read safely. Save it as plain text or a simpler PDF "
    "and attach that."
)
TOO_SLOW = "This file took too long to read. Try a smaller file, or save it as text."
ENCRYPTED_OFFICE = (
    "This {label} file is password-protected, or it is in an old format. Remove the password, "
    "or save it as {ext}, and attach it again."
)
XLS_NOT_EXCEL = (
    "This .xls file is not a real Excel workbook (it may be a web page or text saved with an "
    "Excel name). Open it in Excel, save it as .xlsx, and attach that."
)
UNSAFE_XML = (
    "This file is too unusual to read safely (it carries a document type definition, which "
    "Office files never need). Save it again from Excel or PowerPoint and attach that."
)
_OFFICE_EXT = {"docx": ".docx", "xlsx": ".xlsx", "pptx": ".pptx"}
_OFFICE_LABEL = {"docx": "Word", "xlsx": "Excel", "pptx": "PowerPoint"}


def _unsupported(detail: str) -> DocumentRejected:
    return DocumentRejected("unsupported", detail, status=415)


def _mismatch(kind: str) -> DocumentRejected:
    return _unsupported(
        f"The file's contents don't match its name (.{kind}). JARVIS can read {SUPPORTED_WORDS}."
    )


def _unreadable() -> DocumentRejected:
    return DocumentRejected(
        "unreadable", "JARVIS couldn't read this file. It may be damaged; try saving it again."
    )


def too_complex() -> DocumentRejected:
    return DocumentRejected("too_complex", TOO_COMPLEX)


def _zip_too_big(label: str = "Word") -> DocumentRejected:
    return DocumentRejected(
        "too_complex",
        f"This {label} file is too large or unusual to open safely (it unpacks to too much, or is "
        "packed like a zip bomb). Save it as PDF or text and attach that.",
    )


def too_slow() -> DocumentRejected:
    return DocumentRejected("too_slow", TOO_SLOW)


def _no_text(kind: str) -> DocumentRejected:
    return DocumentRejected("no_text", NO_TEXT_PDF if kind == "pdf" else "No text found in it.")


# ---- type ---------------------------------------------------------------------------------------


def kind_for(name: str) -> Kind:
    suffix = PurePosixPath(name.replace("\\", "/")).suffix.lower()
    kind = EXTENSIONS.get(suffix)
    if kind is None:
        raise _unsupported(f"JARVIS can read {SUPPORTED_WORDS}.")
    return kind


def sniff(data: bytes, kind: str) -> None:
    """The bytes agree with the type the name claims (raises otherwise)."""
    if not data:
        raise DocumentRejected("empty", "That file is empty.")
    if kind == "pdf":
        if b"%PDF-" not in data[:PDF_MAGIC_WINDOW]:
            raise _mismatch(kind)
    elif kind == "docx":
        if data.startswith(_OLE):
            raise DocumentRejected("encrypted", ENCRYPTED_DOCX)
        if not data.startswith(_ZIP):
            raise _mismatch(kind)
    elif kind in ("xlsx", "pptx"):
        if data.startswith(_OLE):
            words = ENCRYPTED_OFFICE.format(label=_OFFICE_LABEL[kind], ext=_OFFICE_EXT[kind])
            raise DocumentRejected("encrypted", words)
        if not data.startswith(_ZIP):
            raise _mismatch(kind)
    elif kind == "xls":
        if not data.startswith(_OLE):
            raise _unsupported(XLS_NOT_EXCEL)
    elif kind in ("zip", "folder"):
        if not data.startswith((_ZIP, b"PK\x05\x06")):
            raise _mismatch("zip")
    elif kind == "image":
        if not data.startswith((_PNG, _JPEG)):
            raise _mismatch("png or .jpg")
    elif data.startswith(_BINARY):
        raise _mismatch(kind)


# ---- text clean-up ------------------------------------------------------------------------------


def normalise(text: str) -> str:
    """Controls out (line breaks and tabs kept), CR/CRLF → LF, lone surrogates out (a hostile
    font map can produce them), no trailing spaces, at most one blank line in a row. Joiners
    (ZWJ / ZWNJ) stay: Malayalam and other Indic scripts need them. Linear in the text: no
    pattern here can backtrack (review H1: `[ \\t]+\\n` was quadratic on long runs of spaces)."""
    t = text.replace("\r\n", "\n").replace("\r", "\n")
    t = _SURROGATE.sub("", _CONTROL.sub("", t))
    t = "\n".join(line.rstrip(" \t") for line in t.split("\n"))
    return _BLANK_RUN.sub("\n\n", t).strip()


def _cap(text: str, limits: Limits) -> tuple[str, bool]:
    return text[: limits.max_chars], len(text) > limits.max_chars


# ---- PDF ----------------------------------------------------------------------------------------


def _open_pdf(data: bytes) -> tuple[Any, int]:
    from pypdf import PdfReader  # BSD-3-Clause

    try:
        reader = PdfReader(io.BytesIO(data))
        # pypdf already tried the empty password: a file with only an owner password (printing
        # / copying restrictions) opens like it does in any viewer; a user password does not.
        if reader.is_encrypted and not reader.decrypt(""):
            raise DocumentRejected("encrypted", ENCRYPTED_PDF)
        return reader, len(reader.pages)
    except (DocumentRejected, MemoryError):
        raise
    except Exception as exc:  # noqa: BLE001 — anything a hostile file triggers is "unreadable"
        raise _unreadable() from exc


def _pdf(data: bytes, limits: Limits, deadline: float, clock: Clock) -> Extracted:
    reader, total = _open_pdf(data)
    texts: list[str] = []
    used = failed = 0
    more = total > limits.max_pages
    for i in range(min(total, limits.max_pages)):
        if clock() > deadline:
            more = True
            break
        try:
            raw = reader.pages[i].extract_text() or ""
        except IndexError:  # the page count was larger than the real page tree
            break
        except MemoryError:
            raise
        except Exception:  # noqa: BLE001 — one bad page never sinks the whole file
            failed += 1
            raw = ""
        texts.append(normalise(raw))
        used += len(texts[-1]) + 2
        if used > limits.max_chars:
            more = more or i + 1 < total
            break
    if not texts and more:
        raise too_slow()
    starts: list[int] = []
    pos = 0
    for t in texts:
        starts.append(pos)
        pos += len(t) + 2
    text, cut = _cap("\n\n".join(texts), limits)
    if not text.strip():
        raise _unreadable() if texts and failed == len(texts) else _no_text("pdf")
    return Extracted(
        kind="pdf",
        text=text,
        pages=len(texts),
        pages_total=total,
        page_starts=tuple(s for s in starts if s < len(text)),
        truncated=more or cut,
    )


# ---- DOCX ---------------------------------------------------------------------------------------


def zip_infos(data: bytes) -> list[zipfile.ZipInfo]:
    """The zip's central directory (nothing is inflated), or "unreadable"."""
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            return zf.infolist()
    except (zipfile.BadZipFile, zipfile.LargeZipFile, OSError, ValueError, EOFError) as exc:
        raise _unreadable() from exc


def bomb_check(
    infos: list[zipfile.ZipInfo], limits: Limits, label: str, *, total: int | None = None
) -> None:
    """Refuse a zip bomb from its central directory alone, before any part is inflated."""
    if len(infos) > limits.zip_max_entries:
        raise _zip_too_big(label)
    if sum(i.file_size for i in infos) > (limits.zip_max_total if total is None else total):
        raise _zip_too_big(label)
    for i in infos:
        if i.file_size > ZIP_RATIO_FLOOR and i.file_size > limits.zip_max_ratio * max(
            i.compress_size, 1
        ):
            raise _zip_too_big(label)


def _zip_guard(
    data: bytes, limits: Limits, *, kind: str = "docx", folder: str = "word/"
) -> list[zipfile.ZipInfo]:
    """An Office file's zip, checked before any XML is parsed: not a bomb, not too much XML,
    and it holds the parts its kind must have (`folder`)."""
    label = _OFFICE_LABEL[kind]
    infos = zip_infos(data)
    bomb_check(infos, limits, label)
    xml = sum(i.file_size for i in infos if i.filename.lower().endswith(_XML_PARTS))
    if xml > limits.zip_max_xml:
        raise _zip_too_big(label)
    names = {i.filename for i in infos}
    if "[Content_Types].xml" not in names or not any(n.startswith(folder) for n in names):
        raise _mismatch(kind)
    return infos


def office_guard(data: bytes, limits: Limits, *, kind: str, folder: str) -> list[zipfile.ZipInfo]:
    """`_zip_guard` plus (R11.1): no XML part may carry a document type definition or be in
    anything but UTF-8. Office never writes either; an entity bomb needs both. Every XML part is
    inflated once here (≤ `zip_max_xml` in all), before a parser sees any of them."""
    infos = _zip_guard(data, limits, kind=kind, folder=folder)
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            for info in infos:
                if info.filename.lower().endswith(_XML_PARTS) and _unsafe_xml(zf.read(info)):
                    raise DocumentRejected("too_complex", UNSAFE_XML)
    except DocumentRejected:
        raise
    except MemoryError:
        raise too_complex() from None
    except Exception as exc:  # noqa: BLE001 — a bad CRC, an unknown compression method
        raise _unreadable() from exc
    return infos


def _unsafe_xml(part: bytes) -> bool:
    head = part[:200]
    if b"\x00" in head or head.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)):
        return True  # UTF-16 / UTF-32: a DTD would hide from the byte search below
    declared = _XML_ENCODING.search(head)
    if declared is not None and declared.group(1).lower() not in (b"utf-8", b"utf8"):
        return True
    return any(mark in part for mark in _DTD)


class _OutOfTime(Exception):
    """The budget ran out in the middle of a table: keep the rows read so far."""

    def __init__(self, partial: str) -> None:
        super().__init__("out of time")
        self.partial = partial


def _cell_text(tc: Any) -> str:
    paras = ("".join(t.text or "" for t in p.iter(_W_NS + "t")) for p in tc.iter(_W_NS + "p"))
    return " ".join(" ".join(paras).split())


def _table_text(tbl: Any, deadline: float, clock: Clock) -> str:
    """Rows as "a | b | c", straight from the XML. A vertically merged continuation cell holds
    no text of its own and is skipped (python-docx repeats the first cell, quadratically)."""
    lines: list[str] = []
    for tr in tbl.iterchildren(_W_NS + "tr"):  # this table's rows (a nested one is cell text)
        if clock() > deadline:
            raise _OutOfTime("\n".join(lines))
        cells: list[str] = []
        for tc in tr.iterchildren(_W_NS + "tc"):
            pr = tc.find(_W_NS + "tcPr")
            merged = pr.find(_W_NS + "vMerge") if pr is not None else None
            if merged is not None and merged.get(_W_NS + "val") != "restart":
                continue
            cells.append(_cell_text(tc))
        if cells:
            lines.append(" | ".join(cells))
    return "\n".join(lines)


def _docx(data: bytes, limits: Limits, deadline: float, clock: Clock) -> Extracted:
    _zip_guard(data, limits)
    import docx  # python-docx, MIT
    from docx.text.paragraph import Paragraph

    parts: list[str] = []
    used = 0
    more = False
    try:
        document = docx.Document(io.BytesIO(data))
        for block in document.iter_inner_content():  # paragraphs and tables, in body order
            if clock() > deadline:
                more = True
                break
            if isinstance(block, Paragraph):
                parts.append(block.text)
            else:
                try:
                    parts.append(_table_text(block._tbl, deadline, clock))
                except _OutOfTime as late:
                    parts.append(late.partial)
                    more = True
                    break
            used += len(parts[-1]) + 1
            if used > limits.max_chars * 2:
                more = True
                break
    except DocumentRejected:
        raise
    except MemoryError:
        raise too_complex() from None
    except Exception as exc:  # noqa: BLE001 — malformed XML, missing parts, wrong content type
        raise _unreadable() from exc
    if not parts and more:
        raise too_slow()
    text, cut = _cap(normalise("\n".join(parts)), limits)
    if not text:
        raise _no_text("docx")
    return Extracted(kind="docx", text=text, truncated=more or cut)


# ---- text, Markdown, CSV ------------------------------------------------------------------------


def _decode(data: bytes) -> str:
    if data.startswith(codecs.BOM_UTF8):
        return data[len(codecs.BOM_UTF8) :].decode("utf-8", errors="replace")
    if data.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)):
        return data.decode("utf-16", errors="replace")
    for encoding in ("utf-8", "cp1252"):  # Windows "ANSI" files: smart quotes
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("latin-1")  # never fails


def _looks_binary(text: str) -> bool:
    if "\x00" in text:
        return True
    controls = sum(1 for ch in text if ord(ch) < 32 and ch not in "\t\n\r\f\v")
    return controls > max(8, CONTROL_SHARE * len(text))


def _plain(data: bytes, kind: str, limits: Limits) -> Extracted:
    raw = _decode(data)
    if _looks_binary(raw[:200_000]):
        raise _unsupported(
            f"This doesn't look like a text file. JARVIS can read {SUPPORTED_WORDS}."
        )
    head = raw[: 2 * limits.max_chars]
    text, cut = _cap(normalise(head), limits)
    if not text:
        raise _no_text(kind)
    return Extracted(kind=kind, text=text, truncated=cut or len(raw) > len(head))


# ---- entry point --------------------------------------------------------------------------------


def extract(
    data: bytes, kind: str, limits: Limits | None = None, *, clock: Clock = time.monotonic
) -> Extracted:
    """The text of `data` read as `kind` (from `kind_for`), within `limits`."""
    lim = limits or Limits()
    sniff(data, kind)
    try:
        return _read(data, kind, lim, clock() + lim.budget_s, clock)
    except MemoryError:
        raise too_complex() from None


def _read(data: bytes, kind: str, lim: Limits, deadline: float, clock: Clock) -> Extracted:
    """One file of one kind. The R11.1 kinds live in their own modules, imported only when a
    file of that kind arrives (the worker starts small)."""
    if kind == "pdf":
        return _pdf(data, lim, deadline, clock)
    if kind == "docx":
        return _docx(data, lim, deadline, clock)
    if kind in ("xlsx", "xls"):
        from jarvis.documents.sheets import read_workbook

        return read_workbook(data, kind, lim, deadline, clock)
    if kind == "pptx":
        from jarvis.documents.slides import read_deck

        return read_deck(data, lim, deadline, clock)
    if kind == "image":
        from jarvis.documents.imagecheck import read_picture

        return read_picture(data, lim)
    if kind in ("zip", "folder"):
        from jarvis.documents.archive import read_archive

        return read_archive(data, kind, lim, deadline, clock)
    return _plain(data, kind, lim)


__all__ = [
    "EXTRACT_BUDGET_S",
    "ZIP_MAX_XML",
    "Clock",
    "Extracted",
    "Limits",
    "Picture",
    "bomb_check",
    "extract",
    "kind_for",
    "normalise",
    "office_guard",
    "sniff",
    "too_complex",
    "too_slow",
    "zip_infos",
]
