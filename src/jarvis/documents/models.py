# src/jarvis/documents/models.py
"""Attached documents (slice 10 E, Layer 7 data): the stored header and what a turn and the API
show about an attachment. Limits, kinds and `DocumentRejected` live in `limits` (standard
library only, for the extraction worker) and are re-exported here.

The raw file is never stored: only its extracted text (in ~4,000-character chunks) and this
header. An attachment belongs to one owner from upload, and to one conversation (and the turn it
was sent with) from the moment it is sent; until then it is "waiting" (`session == ""`).
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from jarvis.documents.limits import (
    CHUNK_COST,
    CHUNKS_PER_PART,
    DOC_ID,
    EXTENSIONS,
    KIND_LABELS,
    MAX_CHARS,
    MAX_CHUNKS,
    MAX_FILE_BYTES,
    MAX_FILES_PER_MESSAGE,
    MAX_PAGES,
    MAX_WAITING,
    NAME_LIMIT,
    PREVIEW_CHARS,
    SUPPORTED_WORDS,
    DocumentRejected,
    Kind,
    new_doc_id,
)


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
