# src/jarvis/documents/models.py
"""Attached documents (slice 10 E, Layer 7 data): limits, the stored header, what a turn and the
API show about an attachment, and the one error type with a plain message for the owner.

The raw file is never stored: only its extracted text (in ~4,000-character chunks) and this
header. An attachment belongs to one owner from upload, and to one conversation (and the turn it
was sent with) from the moment it is sent; until then it is "waiting" (`session == ""`).
"""

from __future__ import annotations

import re
import secrets
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

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


class AttachmentRef(BaseModel):
    """What the owner's turn, the transcript and the upload response show (never the text)."""

    id: str
    name: str
    kind: str
    size: int = Field(description="Bytes of the uploaded file (the file itself is not kept)")
    pages: int | None = Field(default=None, description="PDF pages read")
    words: int
    chars: int = Field(description="Characters of text kept")
    truncated: bool = Field(default=False, description="Only the start of the file was kept")


class Attachment(BaseModel):
    """The stored header: `{prefix}attachments/{id}`. Chunks live under it."""

    id: str
    owner: str
    session: str = ""  # "" while waiting to be sent
    turn: str = ""  # the owner turn it was sent with
    name: str
    kind: str
    size: int
    pages: int | None = None
    pages_total: int | None = None
    words: int
    chars: int
    chunk_count: int
    truncated: bool = False
    preview: str = ""  # the first ≤ PREVIEW_CHARS characters (what the turn note shows)
    created_at: datetime

    @property
    def waiting(self) -> bool:
        return not self.turn

    @property
    def parts(self) -> int:
        return max(1, -(-self.chunk_count // CHUNKS_PER_PART))

    def ref(self) -> AttachmentRef:
        return AttachmentRef(
            id=self.id,
            name=self.name,
            kind=self.kind,
            size=self.size,
            pages=self.pages,
            words=self.words,
            chars=self.chars,
            truncated=self.truncated,
        )


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
    "Attachment",
    "AttachmentRef",
    "DocumentRejected",
    "Kind",
    "new_doc_id",
]
