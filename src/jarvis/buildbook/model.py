# src/jarvis/buildbook/model.py
"""The build book's data model (R6, docs/plans/r6-build-book.md D2, D4-D6, D9, D11-D15). Pure data.

- `Release`: `_book/release.json`, written by the generator (part A) and read by
  `buildbook.release.current()`. A failed build carries `error` and no book (D4).
- `Book` v1: `_book/book.json`, canonical (sorted keys, NFC; same commit -> same bytes). Its eight
  sections (`SECTION_IDS`), the show script (`Show`: scenes 1-11; 12 and 13 are the fixed lines of
  `buildbook.lines`) and the talk-through digest (chunks of <= 1,500 characters). Rupees only.
- `SealedRelease` / `SealedFile`: one entry of the sealed release list (part B, D6). It lives only
  inside the blob sealed under keyring purpose `book_index`; `dek` is a wrapped data key.
- `GuestLock`, `SessionView`, `TalkReply`, `CloseResult`: the guest lock, a book session as it is
  shown (never its token), one talk-through answer and the end of a session (part C, D9-D14).

Every model is frozen and refuses unknown fields. The caps and fixed numbers from the decisions
live here so the four parts share one value.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool, field_validator, model_validator

BOOK_SCHEMA = 1
KEEP = 3  # D5: sealed releases kept (fixed); the oldest beyond it is pruned
CHUNK_BYTES = 512 * 1024  # D6
CHUNKS_PER_COMMIT = 6  # D6: <= 6 chunks a commit, the index last
MAX_BOOK_BYTES = 2 * 1024 * 1024  # D5: book.json
MAX_SOURCE_BYTES = 15 * 1024 * 1024  # D5: one source snapshot
MAX_LIMITATIONS = 80  # D2
LIMITATION_CHARS = 200  # D2: a limitation's first sentence
DIGEST_CHUNK_CHARS = 1500  # D2
DIGEST_CONTEXT_CHARS = 10_000  # D11: the fenced digest in one talk-through call
QUESTION_CHARS = 500  # D12
REPLY_CHARS = 1200  # D12
HISTORY_TURNS = 8  # D11
TALK_MAX_TOKENS = 400  # D11
ASKS_PER_MINUTE = 6  # D12
OPENS_PER_MINUTE = 5  # D8
LEASE_S = 120  # D7: the seal lease
SEAL_BUDGET_S = 20  # D7: sealing inside GET /v1/book
TICKET_S = 60  # D9: a code-download ticket
BEAT_EVERY_S = 60  # D9: the show's keep-alive
HEAR_MAX_S = 15  # Contract: POST /v1/book/show/hear
HEAR_MAX_BYTES = 600 * 1024
CREATOR_NAME_MAX = 40  # D16
OVERLAY_LABELS_MAX = 24  # D15: HTML-overlay labels a scene

SHA = r"^[0-9a-f]{40}$"
RELEASE_ID = r"^[0-9a-f]{7}$"
SHA256 = r"^[0-9a-f]{64}$"
LABEL = r"^R[0-9]{1,3}(\.[0-9]{1,2})?$"  # "R6", "R5.1": from the highest docs/plans/r<N>[-<M>]
FILE_ID = r"^bf_[0-9a-f]{12}$"
SESSION_ID = r"^bk_[0-9a-f]{16}$"
LOCK_ID = r"^bl_[0-9a-f]{12}$"  # = permissions.models.BOOK_LOCK_TARGET (pinned by a test)
REPLY_ID = r"^br_[0-9a-f]{12}$"
SLUG = r"^[a-z0-9_]{1,40}$"
SYMBOL = r"^jarvis(\.[A-Za-z_][A-Za-z0-9_]*)+$"

SECTION_IDS: tuple[str, ...] = (
    "architecture",
    "stack",
    "libraries",
    "integrations",
    "workflows",
    "limitations",
    "costs",
    "decisions",
)
# D15: the show's thirteen scenes (id, title). 1-11 come from the book; 12 and 13 are lines.py's.
SCENES: tuple[tuple[str, str], ...] = (
    ("book", "The build book"),
    ("layers", "Eight layers"),
    ("turn", "One conversation turn"),
    ("memory", "Memory and privacy"),
    ("confirm", "Confirm before commit"),
    ("voice", "Voice"),
    ("home", "Home"),
    ("own", "On its own"),
    ("stack", "Stack and licences"),
    ("costs", "Costs"),
    ("later", "Not built yet"),
    ("questions", "Questions"),
    ("closing", "Closing"),
)
BOOK_SCENES = 11

FileKind = Literal["book", "source"]
Audience = Literal["owner", "guest"]
SessionState = Literal["open", "closing", "closed"]
LicenceFlag = Literal["", "copyleft", "non_commercial", "not_stated"]
LimitKind = Literal["not_in_plan", "risk", "needs_you", "open_question", "deferred", "licence"]
FactFlag = Literal["", "amber", "later"]


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


def _aware(value: str) -> str:
    """An ISO 8601 time WITH its offset (a naive time can't be compared across servers)."""
    if datetime.fromisoformat(value).tzinfo is None:
        raise ValueError("a time needs its UTC offset")
    return value


class Release(_Frozen):
    """`_book/release.json` (D4). `id` is the first 7 characters of `sha`."""

    v: Literal[1] = 1
    id: str = Field(pattern=RELEASE_ID)
    sha: str = Field(pattern=SHA)
    label: str = Field(pattern=LABEL)
    committed_at: str = Field(max_length=40)
    book_sha256: str | None = Field(default=None, pattern=SHA256)
    source_sha256: str | None = Field(default=None, pattern=SHA256)
    source_bytes: int = Field(default=0, ge=0, le=MAX_SOURCE_BYTES)
    skipped: int = Field(default=0, ge=0)  # files left out of the snapshot (THIRD_PARTY.json)
    error: str = Field(default="", max_length=500)

    _committed = field_validator("committed_at")(_aware)

    @model_validator(mode="after")
    def _consistent(self) -> Release:
        if self.id != self.sha[:7]:
            raise ValueError("id must be the first 7 characters of sha")
        hashes = (self.book_sha256, self.source_sha256)
        if self.error and any(h is not None for h in hashes):
            raise ValueError("a failed build carries no book")
        if not self.error and any(h is None for h in hashes):
            raise ValueError("a built release names both files' sha256")
        return self

    @property
    def built(self) -> bool:
        return not self.error


class ReleaseRef(_Frozen):
    """The release a book was built from (inside book.json)."""

    id: str = Field(pattern=RELEASE_ID)
    sha: str = Field(pattern=SHA)
    label: str = Field(pattern=LABEL)
    committed_at: str = Field(max_length=40)

    _committed = field_validator("committed_at")(_aware)


# ---- sections ------------------------------------------------------------------------------------
class Package(_Frozen):
    name: str = Field(pattern=r"^jarvis(\.[a-z0-9_]+)*$", max_length=80)
    files: int = Field(ge=0)
    lines: int = Field(ge=0)
    summary: str = Field(default="", max_length=200)  # the first docstring line


class Layer(_Frozen):
    n: int = Field(ge=0, le=8)  # 1-8 the architecture's layers; 0 cross-cutting
    name: str = Field(min_length=1, max_length=60)
    packages: tuple[Package, ...] = ()


class FitRow(_Frozen):
    """One row of a plan's "How it fits the architecture" table."""

    plan: str = Field(max_length=80)
    feature: str = Field(max_length=200)
    where: str = Field(max_length=200)
    phase: str = Field(default="", max_length=40)
    verdict: str = Field(default="", max_length=80)


class Architecture(_Frozen):
    layers: tuple[Layer, ...] = Field(min_length=8, max_length=9)
    fits: tuple[FitRow, ...] = ()

    @model_validator(mode="after")
    def _eight(self) -> Architecture:
        ns = [layer.n for layer in self.layers]
        if len(set(ns)) != len(ns) or not set(range(1, 9)) <= set(ns):
            raise ValueError("layers 1-8 each once (and at most one cross-cutting 0)")
        return self


class StackItem(_Frozen):
    role: str = Field(min_length=1, max_length=60)  # "Language", "Base image", "CI job", ...
    name: str = Field(min_length=1, max_length=120)
    version: str = Field(default="", max_length=60)


class Stack(_Frozen):
    items: tuple[StackItem, ...] = ()


class Library(_Frozen):
    name: str = Field(min_length=1, max_length=120)
    version: str = Field(default="", max_length=60)
    licence: str = Field(default="not stated", max_length=120)
    flag: LicenceFlag = ""  # copyleft and non-commercial are flagged (D2)
    source: Literal["lock", "vendored"] = "lock"


class Integration(_Frozen):
    key: str = Field(pattern=SLUG)
    name: str = Field(min_length=1, max_length=80)
    what: str = Field(default="", max_length=300)  # plain words (buildbook/plain.py)
    settings: tuple[str, ...] = ()  # Settings field NAMES, never values


class Integrations(_Frozen):
    services: tuple[Integration, ...] = ()
    key_purposes: tuple[str, ...] = ()
    alert_kinds: tuple[str, ...] = ()
    probes: tuple[str, ...] = ()


class Step(_Frozen):
    label: str = Field(min_length=1, max_length=160)
    symbol: str = Field(pattern=SYMBOL, max_length=160)  # a real symbol, AST-checked by --check


class Flow(_Frozen):
    id: str = Field(pattern=SLUG)
    title: str = Field(min_length=1, max_length=80)
    steps: tuple[Step, ...] = Field(min_length=1, max_length=20)


class Limitation(_Frozen):
    plan: str = Field(max_length=80)  # the plan's file stem, e.g. "r6-build-book"
    kind: LimitKind
    text: str = Field(min_length=1, max_length=LIMITATION_CHARS)


class CostLine(_Frozen):
    item: str = Field(min_length=1, max_length=120)
    unit: str = Field(default="", max_length=60)  # "per million tokens", "a month"
    inr: float = Field(ge=0)  # rupees only (no other currency in any owner-facing text)
    free: str = Field(default="", max_length=160)  # the free allowance, in plain words


class Costs(_Frozen):
    as_of: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    usd_inr: float = Field(gt=0)  # the rate the rupee figures were worked out at
    lines: tuple[CostLine, ...] = ()


class PlanDecisions(_Frozen):
    plan: str = Field(max_length=80)
    title: str = Field(max_length=300)
    decisions: tuple[str, ...] = ()


# ---- the show and the digest ---------------------------------------------------------------------
class Fact(_Frozen):
    """One labelled fact a scene shows (a layer and its module count, a library and its licence,
    a cost in rupees, a thing not built yet). All facts come from the book, none from the JS."""

    id: str = Field(pattern=r"^[a-z0-9_.-]{1,60}$")
    label: str = Field(min_length=1, max_length=80)
    value: str = Field(default="", max_length=120)
    amount: float | None = None
    flag: FactFlag = ""


class Beat(_Frozen):
    id: str = Field(pattern=r"^s(0[1-9]|1[0-3])b[0-9]{2}$")  # "s03b02": scene 3, beat 2
    text: str = Field(min_length=1, max_length=400)  # the narration line, also its caption
    focus: str = Field(default="", max_length=60)  # the fact lit while it is spoken


class Scene(_Frozen):
    n: int = Field(ge=1, le=len(SCENES))
    id: str = Field(pattern=SLUG)
    title: str = Field(min_length=1, max_length=80)
    beats: tuple[Beat, ...] = Field(min_length=1, max_length=20)
    facts: tuple[Fact, ...] = Field(default=(), max_length=200)

    @model_validator(mode="after")
    def _numbered(self) -> Scene:
        if self.id != SCENES[self.n - 1][0]:
            raise ValueError("scene id does not match its number")
        prefix = f"s{self.n:02d}b"
        if any(not b.id.startswith(prefix) for b in self.beats):
            raise ValueError("a beat id names another scene")
        return self


class Show(_Frozen):
    scenes: tuple[Scene, ...] = Field(min_length=1, max_length=BOOK_SCENES)

    @model_validator(mode="after")
    def _ordered(self) -> Show:
        ns = [s.n for s in self.scenes]
        if ns != sorted(set(ns)) or ns[-1] > BOOK_SCENES:
            raise ValueError("scenes 1-11 in order, each once")
        return self


class DigestChunk(_Frozen):
    id: str = Field(pattern=r"^d[0-9]{3}$")
    section: str = Field(pattern=SLUG)
    title: str = Field(min_length=1, max_length=120)
    text: str = Field(min_length=1, max_length=DIGEST_CHUNK_CHARS)


class Book(_Frozen):
    """`_book/book.json`, schema v1 (D2)."""

    v: Literal[1] = 1
    release: ReleaseRef
    architecture: Architecture
    stack: Stack
    libraries: tuple[Library, ...] = ()
    integrations: Integrations
    workflows: tuple[Flow, ...] = ()
    limitations: tuple[Limitation, ...] = Field(default=(), max_length=MAX_LIMITATIONS)
    costs: Costs
    decisions: tuple[PlanDecisions, ...] = ()
    show: Show
    digest: tuple[DigestChunk, ...] = ()

    def sections(self) -> dict[str, object]:
        """The eight sections in book order, as JSON-ready data."""
        data = self.model_dump(mode="json")
        return {sid: data[sid] for sid in SECTION_IDS}


# ---- sealed releases (B) and sessions (C) --------------------------------------------------------
class SealedFile(_Frozen):
    kind: FileKind
    fid: str = Field(pattern=FILE_ID)
    size: int = Field(ge=0, le=MAX_SOURCE_BYTES)
    sha256: str = Field(pattern=SHA256)
    count: int = Field(ge=1)  # chunks
    dek: str = Field(min_length=1, max_length=400, repr=False)  # wrapped by Keyring.wrap


class SealedRelease(_Frozen):
    id: str = Field(pattern=RELEASE_ID)
    label: str = Field(pattern=LABEL)
    sha: str = Field(pattern=SHA)
    committed_at: str = Field(max_length=40)
    sealed_at: str = Field(max_length=40)
    files: tuple[SealedFile, ...] = Field(min_length=1, max_length=2)

    _times = field_validator("committed_at", "sealed_at")(_aware)

    @property
    def size(self) -> int:
        return sum(f.size for f in self.files)


class GuestLock(_Frozen):
    id: str = Field(pattern=LOCK_ID)
    session_id: str = Field(pattern=SESSION_ID)
    since: str = Field(max_length=40)

    _since = field_validator("since")(_aware)


class SessionView(_Frozen):
    session_id: str = Field(pattern=SESSION_ID)
    audience: Audience
    state: SessionState = "open"
    created_at: str = Field(max_length=40)
    last_seen: str = Field(max_length=40)
    until: str = Field(max_length=40)
    questions: int = Field(default=0, ge=0)
    questions_left: int = Field(default=0, ge=0)

    _times = field_validator("created_at", "last_seen", "until")(_aware)


class TalkReply(_Frozen):
    reply_id: str = Field(pattern=REPLY_ID)
    reply: str = Field(max_length=REPLY_CHARS)
    refused: StrictBool = False
    follow_up: str = Field(default="", max_length=200)
    left: int = Field(ge=0)


class CloseResult(_Frozen):
    closed: StrictBool
    wiped: StrictBool
    notified: StrictBool


__all__ = [
    "BOOK_SCENES",
    "BOOK_SCHEMA",
    "KEEP",
    "SCENES",
    "SECTION_IDS",
    "Architecture",
    "Audience",
    "Beat",
    "Book",
    "CloseResult",
    "CostLine",
    "Costs",
    "DigestChunk",
    "Fact",
    "FileKind",
    "FitRow",
    "Flow",
    "GuestLock",
    "Integration",
    "Integrations",
    "Layer",
    "Library",
    "Limitation",
    "Package",
    "PlanDecisions",
    "Release",
    "ReleaseRef",
    "Scene",
    "SealedFile",
    "SealedRelease",
    "SessionView",
    "Show",
    "Stack",
    "StackItem",
    "Step",
    "TalkReply",
]
