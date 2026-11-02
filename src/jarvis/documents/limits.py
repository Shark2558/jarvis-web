# src/jarvis/documents/limits.py
"""Attached-document limits, kinds and the one refusal type (slice 10 E). Standard library only:
the extraction worker (a child process per upload, `jarvis.documents.worker`) imports this and
`extract` and nothing else from the app — no settings, no vendor SDKs, no pydantic."""

from __future__ import annotations

import re
import secrets
from typing import Literal

Kind = Literal["pdf", "docx", "txt", "md", "csv"]
EXTENSIONS: dict[str, Kind] = {
    ".pdf": "pdf",
    ".docx": "docx",
    ".txt": "txt",
    ".md": "md",
    ".markdown": "md",
    ".csv": "csv",
}
KIND_LABELS: dict[str, str] = {
    "pdf": "PDF",
    "docx": "Word",
    "txt": "text",
    "md": "Markdown",
    "csv": "CSV",
}

MAX_FILE_BYTES = 10 * 1024 * 1024  # 10 MB per file (the upload route's own body cap)
MAX_FILES_PER_MESSAGE = 3
MAX_PAGES = 300
MAX_CHARS = 300_000
MAX_CHUNKS = 480  # one atomic Firestore commit (500 writes) with the header
CHUNK_COST = 4_400  # chunk size in JSON-escaped characters (≈ 4,000 characters of plain text)
CHUNKS_PER_PART = 2  # doc_read returns one part ≈ 8,000 characters
PREVIEW_CHARS = 2_000  # the start of the text that travels with the turn
NAME_LIMIT = 120
MAX_WAITING = 10  # uploaded, not yet sent, per owner
DOC_ID = re.compile(r"doc_[0-9a-f]{20}")

SUPPORTED_WORDS = "PDF, Word (.docx), text (.txt), Markdown (.md) and CSV files"


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
    "CHUNKS_PER_PART",
    "CHUNK_COST",
    "DOC_ID",
    "EXTENSIONS",
    "KIND_LABELS",
    "MAX_CHARS",
    "MAX_CHUNKS",
    "MAX_FILES_PER_MESSAGE",
    "MAX_FILE_BYTES",
    "MAX_PAGES",
    "MAX_WAITING",
    "NAME_LIMIT",
    "PREVIEW_CHARS",
    "SUPPORTED_WORDS",
    "DocumentRejected",
    "Kind",
    "new_doc_id",
]
