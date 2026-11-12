# src/jarvis/documents/limits.py
"""Attached-document limits, kinds and the one refusal type (slice 10 E; R11.1 D10-D11). Standard
library only: the extraction worker (a child process per upload, `jarvis.documents.worker`)
imports this and `extract` and nothing else from the app — no settings, no vendor SDKs, no
pydantic.

R11.1 adds Excel (`xlsx` for .xlsx / .xlsm, `xls`), PowerPoint (`pptx`), pictures (`image` for
.png / .jpg / .jpeg), `zip`, and `folder` (a folder the console packed into one bundle: it has no
extension, the upload says so). `AttachPolicy` is what one message may carry; its defaults are
the settings' own (`Settings.attach_*`), which the app passes in.
"""

from __future__ import annotations

import re
import secrets
from dataclasses import dataclass
from typing import Literal

Kind = Literal["pdf", "docx", "txt", "md", "csv", "xlsx", "xls", "pptx", "image", "zip", "folder"]
EXTENSIONS: dict[str, Kind] = {
    ".pdf": "pdf",
    ".docx": "docx",
    ".txt": "txt",
    ".md": "md",
    ".markdown": "md",
    ".csv": "csv",
    ".xlsx": "xlsx",
    ".xlsm": "xlsx",  # the same file with macros, which are never run: values only
    ".xls": "xls",
    ".pptx": "pptx",
    ".png": "image",
    ".jpg": "image",
    ".jpeg": "image",
    ".zip": "zip",
}
KIND_LABELS: dict[str, str] = {
    "pdf": "PDF",
    "docx": "Word",
    "txt": "text",
    "md": "Markdown",
    "csv": "CSV",
    "xlsx": "Excel",
    "xls": "Excel",
    "pptx": "PowerPoint",
    "image": "picture",
    "zip": "zip",
    "folder": "folder",
}
# what the console's file picker offers: its `accept` list is set from this (GET /v1/input)
ACCEPT: tuple[str, ...] = tuple(EXTENSIONS)
FOLDER: Kind = "folder"
ARCHIVE_KINDS: frozenset[str] = frozenset({"zip", "folder"})
# never opened from inside a zip or a folder (D11: no nested archives)
ARCHIVE_SUFFIXES: tuple[str, ...] = (
    ".zip",
    ".7z",
    ".rar",
    ".tar",
    ".gz",
    ".tgz",
    ".bz2",
    ".xz",
    ".jar",
    ".iso",
)

MAX_FILE_BYTES = 10 * 1024 * 1024  # 10 MB per file (the upload route's own body cap)
MAX_FILES_PER_MESSAGE = 10  # `attach_max_files` (3 before R11.1)
MAX_TOTAL_BYTES = 40 * 1024 * 1024  # `attach_total_mb`: all files of one message together
MAX_PAGES = 300
MAX_CHARS = 300_000
MAX_CHUNKS = 480  # one atomic Firestore commit (500 writes) with the header and the pictures
# chunk size in the gateway's JSON characters (real Unicode: one per letter in any script; only
# ASCII control characters escaped) ≈ 4,000 characters of text, Latin or Malayalam alike
CHUNK_COST = 4_400
CHUNKS_PER_PART = 2  # doc_read returns one part ≈ 8,000 characters
PREVIEW_CHARS = 2_000  # the start of the text that travels with the turn
NAME_LIMIT = 120
MAX_WAITING = 10  # uploaded, not yet sent, per owner
DOC_ID = re.compile(r"doc_[0-9a-f]{20}")

# ---- R11.1: workbooks, decks, archives, pictures ------------------------------------------------
MAX_SHEETS = 50  # a workbook with more is refused, never half-read
MAX_SHEET_ROWS = 5_000  # rows read from one sheet (the rest are counted and said)
MAX_ROW_CELLS = 200  # cells read from one row
MAX_CELL_CHARS = 500
MAX_SLIDES = 500
ZIP_MAX_FILES = 50  # `attach_zip_max_files` / `attach_folder_max_files`: files read from one
MAX_PICTURES = 4  # pictures that go with one message (D10)
PICTURE_MAX_BYTES = 900 * 1024  # `attach_picture_max_kb`: one Firestore document, as bytes
PICTURE_MAX_SIDE = 2_048  # pixels; the console shrinks to PICTURE_SHRINK_SIDE before it uploads
PICTURE_SHRINK_SIDE = 1_568
PICTURE_TYPES: tuple[str, ...] = ("image/jpeg", "image/png")

SUPPORTED_WORDS = (
    "PDF, Word (.docx), Excel (.xlsx, .xls), PowerPoint (.pptx), text (.txt), Markdown (.md) and "
    "CSV files, pictures (.png, .jpg), zip files and folders"
)


@dataclass(frozen=True)
class AttachPolicy:
    """What one message may carry (plan D10-D11). The defaults are the settings' defaults; the
    app hands the service the owner's own values (`policy_from`)."""

    max_files: int = MAX_FILES_PER_MESSAGE
    total_bytes: int = MAX_TOTAL_BYTES
    zip_max_files: int = ZIP_MAX_FILES
    folder_max_files: int = ZIP_MAX_FILES
    picture_max_bytes: int = PICTURE_MAX_BYTES
    max_pictures: int = MAX_PICTURES


def new_doc_id() -> str:
    return "doc_" + secrets.token_hex(10)


class DocumentRejected(Exception):
    """An upload (or a use of one) refused, with a plain message the console shows as is.
    `code` becomes the API's `error`; `status` its HTTP status."""

    def __init__(self, code: str, detail: str, *, status: int = 422) -> None:
        super().__init__(detail)
        self.code = code
        self.status = status


__all__ = [
    "ACCEPT",
    "ARCHIVE_KINDS",
    "ARCHIVE_SUFFIXES",
    "CHUNKS_PER_PART",
    "CHUNK_COST",
    "DOC_ID",
    "EXTENSIONS",
    "FOLDER",
    "KIND_LABELS",
    "MAX_CELL_CHARS",
    "MAX_CHARS",
    "MAX_CHUNKS",
    "MAX_FILES_PER_MESSAGE",
    "MAX_FILE_BYTES",
    "MAX_PAGES",
    "MAX_PICTURES",
    "MAX_ROW_CELLS",
    "MAX_SHEETS",
    "MAX_SHEET_ROWS",
    "MAX_SLIDES",
    "MAX_TOTAL_BYTES",
    "MAX_WAITING",
    "NAME_LIMIT",
    "PICTURE_MAX_BYTES",
    "PICTURE_MAX_SIDE",
    "PICTURE_SHRINK_SIDE",
    "PICTURE_TYPES",
    "PREVIEW_CHARS",
    "SUPPORTED_WORDS",
    "ZIP_MAX_FILES",
    "AttachPolicy",
    "DocumentRejected",
    "Kind",
    "new_doc_id",
]
