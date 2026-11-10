# src/jarvis/buildbook/model.py
"""The build book's one schema (R6 D2, D4-D6, D9; docs/plans/r6-build-book.md). Pure data: frozen
pydantic models (extra fields refused), no I/O, nothing from the app, so the generator (A), the
sealer (B), the session lane (C) and the show (D) all read the same shapes.

- `Release` = `release.json` (D4). `id` is `sha[:7]`; a good build carries both SHA-256s, a failed
  one (`error`, best effort at deploy) carries neither and no book. `skipped` counts the tracked
  files left out of the snapshot (listed in its THIRD_PARTY.json, D5).
- `Book` v1 = `book.json`: `release` (a `ReleaseRef`), the eight reader sections (`SECTION_IDS`,
  D2's table; their models live in `buildbook/sections.py` and are re-exported here), `show`
  (scenes 1-11; 12 and 13 are `lines.py`) and `digest` (the talk-through's reference, D11).
  `canonical_bytes` is THE byte form (sorted keys, NFC, compact UTF-8): the same commit gives the
  same bytes; `load_book` checks the 2 MiB cap and the version first.
- `SealedRelease` = one entry of the sealed index (D6); `view()` is the status route's row.
- `SessionView`, `OpenedSession`, `ClosedSession`, `ShowLockState`, `TalkReply`, `TalkState`: what
  the session lane hands the routes (D9, D10, D11, D14). A token appears only in `OpenedSession`,
  never in a repr.
Book text holds no personal data by construction (D3: the generator scrubs; the sealer re-checks).
"""

from __future__ import annotations

import json
import unicodedata
from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import AfterValidator, Field, ValidationError, field_validator, model_validator

from jarvis.buildbook.sections import (
    FLOW_IDS,
    LAYERS,
    NAME,
    RELEASE_LABEL,
    SECTION_IDS,
    AlertRow,
    Architecture,
    CostItem,
    Costs,
    FitRow,
    Frozen,
    Integrations,
    Library,
    Limitation,
    Package,
    PlanDecisions,
    Service,
    Stack,
    StackItem,
    Step,
    Workflow,
)

SCHEMA_VERSION = 1
KEEP = 3  # releases kept sealed (D5: fixed)
MIB = 1024 * 1024
SNAPSHOT_CAP_BYTES = 15 * MIB  # one source snapshot (D5)
BOOK_JSON_CAP_BYTES = 2 * MIB  # book.json (D5)
DIGEST_CHUNK_CHARS = 1_500  # D2 / D11
MAX_LIMITATIONS = 80  # D2
ZIP_STAMP = (2026, 1, 1, 0, 0, 0)  # every zip entry's time, as home/kit.py (D5)

RELEASE_ID = r"^[0-9a-f]{7}$"
GIT_SHA = r"^[0-9a-f]{40}$"
SHA256 = r"^[0-9a-f]{64}$"
SESSION_ID = r"^bk_[0-9a-f]{16}$"  # D9
LOCK_ID = r"^bl_[0-9a-f]{12}$"  # D10; == permissions.models.BOOK_LOCK_TARGET (seam test)
FILE_ID = r"^bf_[0-9a-f]{12}$"  # a sealed file (D6)
LINE_ID = r"^s[0-9]{2}b[0-9]{2}$"  # a show beat: scene nn, beat nn (D15); fixed lines: lines.LINES

Audience = Literal["owner", "guest"]
FileKind = Literal["book", "source"]
SHOW_SCENES: tuple[tuple[int, str, str], ...] = (
    (1, "book", "The build book"),
    (2, "layers", "Eight layers"),
    (3, "turn", "One conversation turn"),
    (4, "memory", "Memory and privacy"),
    (5, "confirm", "Confirm before commit"),
    (6, "voice", "Voice"),
    (7, "home", "Home"),
    (8, "own", "On its own"),
    (9, "stack", "Stack and licences"),
    (10, "costs", "Costs"),
    (11, "later", "Not built yet"),
    (12, "questions", "Questions"),
    (13, "closing", "Closing"),
)
BOOK_SCENES = 11  # scenes 1-11 come from book.json; 12 and 13 are D13's fixed lines


def _aware(value: str) -> str:
    """An ISO 8601 time WITH its UTC offset (a naive time is ambiguous across servers)."""
    if datetime.fromisoformat(value).tzinfo is None:
        raise ValueError("a time needs its UTC offset")
    return value


# an ISO 8601 time with its UTC offset, kept as text so book.json's bytes never depend on a parser
Instant = Annotated[str, Field(min_length=10, max_length=40), AfterValidator(_aware)]


# ---- release.json (D4) ---------------------------------------------------------------------------
class ReleaseRef(Frozen):
    """The release a book describes (inside book.json; no digests, they would be circular)."""

    id: str = Field(pattern=RELEASE_ID)
    sha: str = Field(pattern=GIT_SHA)
    label: str = Field(pattern=RELEASE_LABEL)
    committed_at: Instant

    @model_validator(mode="after")
    def _id_is_the_sha(self) -> ReleaseRef:
        if self.id != self.sha[:7]:
            raise ValueError("a release id is the first seven characters of its commit")
        return self


class Release(ReleaseRef):
    v: Literal[1] = 1
    book_sha256: str | None = Field(default=None, pattern=SHA256)
    source_sha256: str | None = Field(default=None, pattern=SHA256)
    source_bytes: int = Field(default=0, ge=0, le=SNAPSHOT_CAP_BYTES)
    skipped: int = Field(default=0, ge=0)
    error: str | None = Field(default=None, min_length=1, max_length=200)

    @model_validator(mode="after")
    def _digests(self) -> Release:
        digests = (self.book_sha256, self.source_sha256)
        if self.error is None and None in digests:
            raise ValueError("a good build names both files' SHA-256")
        if self.error is not None and digests != (None, None):
            raise ValueError("a failed build wrote no book")
        return self

    @property
    def ok(self) -> bool:
        return self.error is None

    def ref(self) -> ReleaseRef:
        return ReleaseRef(
            id=self.id, sha=self.sha, label=self.label, committed_at=self.committed_at
        )


# ---- the show (D15) and the digest (D11) ---------------------------------------------------------
class Fact(Frozen):
    """A number or label a scene draws (a layer's module count, a library tag, a ₹ bar)."""

    label: str = Field(max_length=80)
    value: str = Field(default="", max_length=120)
    n: float | None = None
    group: str = Field(default="", max_length=40)
    flag: str = Field(default="", max_length=20)


class Beat(Frozen):
    id: str = Field(pattern=LINE_ID)  # the line id POST /v1/book/show/speak takes
    text: str = Field(min_length=1, max_length=400)
    focus: str = Field(default="", max_length=60)  # what the scene lights: a layer, a flow, ...


class Scene(Frozen):
    n: int = Field(ge=1, le=BOOK_SCENES)
    id: str = Field(pattern=NAME)
    title: str = Field(max_length=60)
    beats: tuple[Beat, ...] = Field(min_length=1, max_length=40)
    facts: tuple[Fact, ...] = Field(default=(), max_length=60)

    @model_validator(mode="after")
    def _known(self) -> Scene:
        if (self.n, self.id, self.title) != SHOW_SCENES[self.n - 1]:
            raise ValueError("a scene must match SHOW_SCENES")
        if any(not b.id.startswith(f"s{self.n:02d}b") for b in self.beats):
            raise ValueError("a beat's id names its scene")
        return self


class Show(Frozen):
    scenes: tuple[Scene, ...]

    @model_validator(mode="after")
    def _in_order(self) -> Show:
        if [s.n for s in self.scenes] != list(range(1, BOOK_SCENES + 1)):
            raise ValueError("the show is scenes 1 to 11, in order")
        ids = [b.id for s in self.scenes for b in s.beats]
        if len(ids) != len(set(ids)):
            raise ValueError("a line id is used twice")
        return self


class DigestChunk(Frozen):
    id: str = Field(pattern=r"^c[0-9]{3}$")
    section: str = Field(pattern=NAME)
    text: str = Field(min_length=1, max_length=DIGEST_CHUNK_CHARS)


class Digest(Frozen):
    overview: str = Field(max_length=2_000)
    chunks: tuple[DigestChunk, ...] = Field(max_length=400)


class Book(Frozen):
    v: Literal[1] = 1
    release: ReleaseRef
    architecture: Architecture
    stack: Stack
    libraries: tuple[Library, ...]
    integrations: Integrations
    workflows: tuple[Workflow, ...]
    limitations: tuple[Limitation, ...] = Field(max_length=MAX_LIMITATIONS)
    costs: Costs
    decisions: tuple[PlanDecisions, ...]
    show: Show
    digest: Digest

    def sections(self) -> dict[str, Any]:
        """The eight reader sections (GET /v1/book/sections), JSON-ready, in SECTION_IDS order."""
        dumped = self.model_dump(mode="json")
        return {k: dumped[k] for k in SECTION_IDS}


def canonical_bytes(book: Book) -> bytes:
    """THE bytes of book.json: sorted keys, compact separators, UTF-8, NFC (D2)."""
    text = json.dumps(
        book.model_dump(mode="json"), sort_keys=True, ensure_ascii=False, separators=(",", ":")
    )
    return unicodedata.normalize("NFC", text).encode("utf-8")


def load_book(data: bytes) -> Book:
    """Parse book.json. ValueError (never a partial book): over 2 MiB, not JSON, not v1."""
    if len(data) > BOOK_JSON_CAP_BYTES:
        raise ValueError("book.json is over its 2 MiB cap")
    try:
        return Book.model_validate_json(data)
    except ValidationError as exc:
        raise ValueError(f"book.json is not a v1 book ({exc.error_count()} problems)") from None


# ---- sealed releases (D6) and sessions (D9-D14) --------------------------------------------------
class SealedFile(Frozen):
    kind: FileKind
    fid: str = Field(pattern=FILE_ID)
    size: int = Field(ge=0, le=SNAPSHOT_CAP_BYTES)
    sha256: str = Field(pattern=SHA256)
    count: int = Field(ge=1, le=64)  # 512 KiB chunks
    dek: str = Field(min_length=1, max_length=512, repr=False)  # Keyring.wrap output, never a key


class SealedRelease(ReleaseRef):
    sealed_at: Instant
    files: tuple[SealedFile, ...] = Field(min_length=2, max_length=2)

    @field_validator("files")
    @classmethod
    def _one_of_each(cls, v: tuple[SealedFile, ...]) -> tuple[SealedFile, ...]:
        if sorted(f.kind for f in v) != ["book", "source"]:
            raise ValueError("a sealed release is one book and one source snapshot")
        return v

    @property
    def size(self) -> int:
        return sum(f.size for f in self.files)

    def file(self, kind: FileKind) -> SealedFile:
        return next(f for f in self.files if f.kind == kind)

    def view(self) -> dict[str, Any]:
        """The status route's row: {id, label, sealed_at, mb}."""
        mb = round(self.size / MIB, 1)
        return {"id": self.id, "label": self.label, "sealed_at": self.sealed_at, "mb": mb}


CloseReason = Literal["closing", "end", "expired", "idle", "new_open", "resume", "privacy"]


class SessionView(Frozen):
    """A live book session as the routes may show it: no uid, no token, no MAC, no turns."""

    session_id: str = Field(pattern=SESSION_ID)
    audience: Audience
    created_at: Instant
    until: Instant  # absolute end (book_session_minutes)
    idle_until: Instant  # last beat + book_idle_minutes
    questions: int = Field(ge=0)
    questions_left: int = Field(ge=0)
    state: Literal["open", "closing"] = "open"


class OpenedSession(Frozen):
    """POST /v1/book/open's answer. The token (32 random bytes, base64url) is shown ONCE."""

    token: str = Field(min_length=32, max_length=128, repr=False)
    session: SessionView


class ClosedSession(Frozen):
    """What a close did (D14): the notice and the content-free audit line are built from it."""

    session_id: str = Field(pattern=SESSION_ID)
    audience: Audience
    reason: CloseReason
    created_at: Instant
    closed_at: Instant
    minutes: int = Field(ge=0)
    questions: int = Field(ge=0)
    wiped: bool  # the document was deleted and read back absent
    notified: bool = False


class ShowLockState(Frozen):
    """`{prefix}book_lock/{uid}` (D10): set at a guest open, lifted only by a book_resume proof."""

    id: str = Field(pattern=LOCK_ID)
    bk: str = Field(pattern=SESSION_ID)
    since: Instant


class TalkState(Frozen):
    on: bool
    why: str = Field(default="", max_length=200)  # plain words when off


class TalkReply(Frozen):
    """POST /v1/book/show/ask's answer: only the guarded reply is ever stored or spoken (D12)."""

    reply_id: str = Field(pattern=r"^r_[0-9a-f]{12}$")
    reply: str = Field(max_length=1_200)
    refused: bool
    follow_up: str = Field(default="", max_length=200)
    left: int = Field(ge=0)


__all__ = [
    "BOOK_JSON_CAP_BYTES",
    "BOOK_SCENES",
    "FLOW_IDS",
    "KEEP",
    "LAYERS",
    "LOCK_ID",
    "SCHEMA_VERSION",
    "SECTION_IDS",
    "SESSION_ID",
    "SHOW_SCENES",
    "SNAPSHOT_CAP_BYTES",
    "ZIP_STAMP",
    "AlertRow",
    "Architecture",
    "Audience",
    "Beat",
    "Book",
    "CloseReason",
    "ClosedSession",
    "CostItem",
    "Costs",
    "Digest",
    "DigestChunk",
    "Fact",
    "FileKind",
    "FitRow",
    "Integrations",
    "Library",
    "Limitation",
    "OpenedSession",
    "Package",
    "PlanDecisions",
    "Release",
    "ReleaseRef",
    "Scene",
    "SealedFile",
    "SealedRelease",
    "Service",
    "SessionView",
    "Show",
    "ShowLockState",
    "Stack",
    "StackItem",
    "Step",
    "TalkReply",
    "TalkState",
    "Workflow",
    "canonical_bytes",
    "load_book",
]
