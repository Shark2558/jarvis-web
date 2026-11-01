# src/jarvis/documents/extract.py
"""Text out of an attached file (slice 10 E, D-E1). Pure and synchronous: the service runs it in
a worker thread with a time budget. Model-agnostic: the model only ever sees the text.

    kind_for(name)      the type, from the extension (PDF, DOCX, TXT, MD, CSV) — else refused
    sniff(data, kind)   the bytes must agree: %PDF- for a PDF, a zip for a DOCX (an OLE file is
                        a password-protected or old .doc), no binary signature for text
    extract(...)        pypdf (BSD-3) for PDF, python-docx (MIT; lxml with entities off) for
                        DOCX, UTF-8 / UTF-16 BOM / cp1252 / latin-1 for text; nothing is executed

Limits (`Limits`): ≤ 300 PDF pages read, ≤ 300,000 characters kept, a time budget checked
between pages / paragraphs (what was read in time is kept, marked truncated), and for a DOCX the
zip's central directory is checked BEFORE any XML is parsed: ≤ 1,000 entries, ≤ 50 MB unpacked
in total, no entry over 1 MB packed more than 100×. Declared sizes bound what zipfile inflates
(it stops at the declared size and fails the CRC), so a lying header cannot inflate more. No OCR:
a PDF without a text layer is "no text found". Every refusal is a `DocumentRejected` with a plain
message; any other exception from a hostile file becomes "unreadable", never a crash.
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

from jarvis.documents.models import (
    EXTENSIONS,
    MAX_CHARS,
    MAX_PAGES,
    SUPPORTED_WORDS,
    DocumentRejected,
    Kind,
)
from jarvis.tools.external import clean_text

EXTRACT_BUDGET_S = 25.0
ZIP_MAX_ENTRIES = 1_000
ZIP_MAX_TOTAL = 50 * 1024 * 1024
ZIP_MAX_RATIO = 100
ZIP_RATIO_FLOOR = 1024 * 1024  # smaller entries may compress as well as they like
PDF_MAGIC_WINDOW = 1024  # readers accept a little junk before %PDF-
CONTROL_SHARE = 0.01  # more control characters than this: not a text file

_ZIP = b"PK\x03\x04"
_OLE = bytes.fromhex("D0CF11E0A1B11AE1")
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
_SURROGATE = re.compile("[\ud800-\udfff]")
_TRAILING_WS = re.compile(r"[ \t]+\n")
_BLANK_RUN = re.compile(r"\n{3,}")

logging.getLogger("pypdf").setLevel(logging.ERROR)  # a hostile file must not flood the logs

Clock = Callable[[], float]


@dataclass(frozen=True)
class Limits:
    max_pages: int = MAX_PAGES
    max_chars: int = MAX_CHARS
    budget_s: float = EXTRACT_BUDGET_S
    zip_max_entries: int = ZIP_MAX_ENTRIES
    zip_max_total: int = ZIP_MAX_TOTAL
    zip_max_ratio: int = ZIP_MAX_RATIO


@dataclass(frozen=True)
class Extracted:
    kind: str
    text: str
    pages: int | None = None  # PDF: pages read
    pages_total: int | None = None  # PDF: pages the file says it has
    page_starts: tuple[int, ...] = ()  # PDF: where each page read begins in `text`
    truncated: bool = False


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


def _unsupported(detail: str) -> DocumentRejected:
    return DocumentRejected("unsupported", detail, status=415)


def _mismatch(kind: str) -> DocumentRejected:
    ext = "docx" if kind == "docx" else kind
    return _unsupported(
        f"The file's contents don't match its name (.{ext}). JARVIS can read {SUPPORTED_WORDS}."
    )


def _unreadable() -> DocumentRejected:
    return DocumentRejected(
        "unreadable", "JARVIS couldn't read this file. It may be damaged; try saving it again."
    )


def _too_complex() -> DocumentRejected:
    return DocumentRejected(
        "too_complex",
        "This Word file is too large or unusual to open safely (it unpacks to more than 50 MB, "
        "or is packed like a zip bomb). Save it as PDF or text and attach that.",
    )


def _too_slow() -> DocumentRejected:
    return DocumentRejected(
        "too_slow", "This file took too long to read. Try a smaller file, or save it as text."
    )


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
    elif data.startswith(_BINARY):
        raise _mismatch(kind)


# ---- text clean-up ------------------------------------------------------------------------------


def normalise(text: str) -> str:
    """Controls out (line breaks and tabs kept), CR/CRLF → LF, lone surrogates out (a hostile
    font map can produce them), no trailing spaces, at most one blank line in a row. Joiners
    (ZWJ / ZWNJ) stay: Malayalam and other Indic scripts need them."""
    t = _SURROGATE.sub("", clean_text(text))
    t = _TRAILING_WS.sub("\n", t)
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
    except DocumentRejected:
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
        except Exception:  # noqa: BLE001 — one bad page never sinks the whole file
            failed += 1
            raw = ""
        texts.append(normalise(raw))
        used += len(texts[-1]) + 2
        if used > limits.max_chars:
            more = more or i + 1 < total
            break
    if not texts and more:
        raise _too_slow()
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


def _zip_guard(data: bytes, limits: Limits) -> None:
    """Refuse a zip bomb from its central directory alone, before any part is inflated."""
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            infos = zf.infolist()
    except (zipfile.BadZipFile, zipfile.LargeZipFile, OSError, ValueError, EOFError) as exc:
        raise _unreadable() from exc
    if len(infos) > limits.zip_max_entries:
        raise _too_complex()
    if sum(i.file_size for i in infos) > limits.zip_max_total:
        raise _too_complex()
    for i in infos:
        if i.file_size > ZIP_RATIO_FLOOR and i.file_size > limits.zip_max_ratio * max(
            i.compress_size, 1
        ):
            raise _too_complex()
    names = {i.filename for i in infos}
    if "[Content_Types].xml" not in names or not any(n.startswith("word/") for n in names):
        raise _mismatch("docx")


def _table_text(table: Any) -> str:
    lines: list[str] = []
    for row in table.rows:
        cells: list[str] = []
        for cell in row.cells:
            text = " ".join(cell.text.split())
            if not cells or cells[-1] != text:  # a merged cell repeats across the row
                cells.append(text)
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
            parts.append(block.text if isinstance(block, Paragraph) else _table_text(block))
            used += len(parts[-1]) + 1
            if used > limits.max_chars * 2:
                more = True
                break
    except DocumentRejected:
        raise
    except Exception as exc:  # noqa: BLE001 — malformed XML, missing parts, wrong content type
        raise _unreadable() from exc
    if not parts and more:
        raise _too_slow()
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
    for encoding in ("utf-8", "cp1252"):  # Windows "ANSI" files: smart quotes, ₹-less Latin
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
    if kind == "pdf":
        return _pdf(data, lim, clock() + lim.budget_s, clock)
    if kind == "docx":
        return _docx(data, lim, clock() + lim.budget_s, clock)
    return _plain(data, kind, lim)


__all__ = ["EXTRACT_BUDGET_S", "Extracted", "Limits", "extract", "kind_for", "normalise", "sniff"]
