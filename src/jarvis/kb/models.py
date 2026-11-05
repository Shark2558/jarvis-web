# src/jarvis/kb/models.py
"""Notes, voice memos and links: the knowledge base's data model (R2 D10; Layer 3/7).

A `Note` is one item of the owner's: a typed note, a memo (a reviewed transcript, never audio) or
a link, with tags, an optional note about the link and, once the owner has pressed "Fetch page
text", an excerpt of the page (`PageExcerpt`: other people's words).

Trust by origin (slice 11 D8 style). The verdict is recorded when the item is written, from the
server's own knowledge of the round, never from a client:
  - `typed`    the console form or a typed chat turn            vouches
  - `memo`     a transcript the owner reviewed before Save       vouches
  - `imported` the owner's own export                            vouches
  - `voice`    written in a spoken chat turn                     never vouches
  - `outside`  written in a content-tainted round, or from a card proposed in one
  and any note that carries page text never vouches, whatever its origin.
A note that does not vouch taints the round when it is read back (`jarvis.kb.tools`).

`clean_fields` is the one place a write is cleaned and checked, for the console, the tools and the
import alike: lengths, tags, the link, and the memory sensitive filter on every owner-written
field. Errors are `NotesError` (a status, a code, plain words); none quotes the offending text.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal
from urllib.parse import unquote_plus, urlsplit

from pydantic import BaseModel, ConfigDict, Field

from jarvis.recall.sensitive import sensitive_reason
from jarvis.recall.text import clean_block, clean_keywords, clean_text
from jarvis.web.guard import query_problem
from jarvis.web.sources import MAX_URL_CHARS, domain_of, normalize_url

MAX_TITLE = 120
MAX_TEXT = 4_000
MAX_TAGS = 8
MAX_TAG_CHARS = 30
MAX_OWNER_NOTE = 1_000
MAX_PAGE_TITLE = 200
MAX_EXCERPT = 6_000
MAX_LIVE = 2_000
MAX_HITS = 8
SNIPPET_CHARS = 300
PAGE_SIZE = 20
IMPORT_MAX_BYTES = 2_000_000
DERIVED_TITLE = 60

NOTE_ID = re.compile(r"n_[0-9a-f]{12}")
Kind = Literal["note", "memo", "link"]
Origin = Literal["typed", "memo", "imported", "voice", "outside"]
KINDS: tuple[str, ...] = ("note", "memo", "link")
ORIGINS: tuple[str, ...] = ("typed", "memo", "imported", "voice", "outside")
VOUCH_ORIGINS = frozenset({"typed", "memo", "imported"})
_WORSE = {"typed": 0, "memo": 0, "imported": 0, "voice": 1, "outside": 2}

MSG_SENSITIVE = "IDs go in the Vault; JARVIS doesn't keep passwords or card numbers."
MSG_FULL = f"You have {MAX_LIVE:,} notes, the most JARVIS keeps. Delete some, then try again."
MSG_UNAVAILABLE = "Your notes can't be read just now. Try again in a minute."
MSG_NOT_FOUND = "There is no such note."
MSG_BAD_URL = "That isn't a web address JARVIS can keep. Use a full https:// link."


class NotesError(ValueError):
    """A refusal in plain words: `status` and `code` become the API answer; `detail` never quotes
    what the owner wrote."""

    def __init__(self, status: int, code: str, detail: str, reason: str | None = None) -> None:
        super().__init__(detail)
        self.status = status
        self.code = code
        self.detail = detail
        self.reason = reason


def invalid(detail: str) -> NotesError:
    return NotesError(422, "input_rejected", detail)


def not_found() -> NotesError:
    return NotesError(404, "not_found", MSG_NOT_FOUND)


def unavailable() -> NotesError:
    return NotesError(503, "notes_unavailable", MSG_UNAVAILABLE)


class PageExcerpt(BaseModel):
    """The text of a saved web page: other people's words, fenced wherever it is shown."""

    model_config = ConfigDict(frozen=True)

    title: str = Field(max_length=MAX_PAGE_TITLE)
    excerpt: str = Field(max_length=MAX_EXCERPT)
    fetched_at: datetime


class Note(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    kind: Kind
    title: str
    text: str = ""
    tags: tuple[str, ...] = ()
    origin: Origin
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None = None
    url: str | None = None
    owner_note: str = ""
    page: PageExcerpt | None = None

    @property
    def live(self) -> bool:
        return self.deleted_at is None


class NoteView(BaseModel):
    """One note as the console sees it (GET /v1/notes). Free text, shown with textContent only."""

    id: str
    kind: Kind
    title: str
    text: str
    tags: list[str]
    origin: Origin
    created_at: datetime
    updated_at: datetime
    url: str | None
    host: str | None
    owner_note: str
    page: PageExcerpt | None
    trusted: bool
    snippet: str | None = None

    @classmethod
    def of(cls, note: Note, snippet: str | None = None) -> NoteView:
        return cls(
            id=note.id,
            kind=note.kind,
            title=note.title,
            text=note.text,
            tags=list(note.tags),
            origin=note.origin,
            created_at=note.created_at,
            updated_at=note.updated_at,
            url=note.url,
            host=domain_of(note.url) if note.url else None,
            owner_note=note.owner_note,
            page=note.page,
            trusted=vouches(note),
            snippet=snippet,
        )


class NotesPage(BaseModel):
    items: list[NoteView]
    total: int
    page: int
    pages: int
    counts: dict[str, int]
    available: bool = True


class ImportResult(BaseModel):
    added: int
    skipped: int


def vouches(note: Note) -> bool:
    """Is every word in this note the owner's? (D10: origin, and no page text.)"""
    return note.origin in VOUCH_ORIGINS and note.page is None


def worse_origin(a: str, b: str) -> Origin:
    """The less trusted of two origins: an edit from outside never makes a note more trusted."""
    pick = a if _WORSE.get(a, 2) >= _WORSE.get(b, 2) else b
    return pick  # type: ignore[return-value]


def normalise_link(raw: object) -> str:
    """The canonical https form of a link, or `bad_url`: http, javascript:, data:, user info, IP
    literals and over-long addresses are refused."""
    url = normalize_url(raw)
    if url is None or len(url) > MAX_URL_CHARS:
        raise NotesError(422, "bad_url", MSG_BAD_URL)
    return url


def private_part(url: str) -> str | None:
    """What private data the link's host, path or query holds ("an email address", ...), or None.
    The host counts: a planted `aadhaar-123456789012.evil.example` must not be kept or fetched."""
    parts = urlsplit(url)
    return query_problem(unquote_plus(f"{parts.hostname or ''} {parts.path} {parts.query}"))


def host_of(url: str) -> str:
    """The host to show (punycode stays punycode, so a look-alike name can't pass as another)."""
    return domain_of(url)


def _link_title(url: str) -> str:
    rest = url.removeprefix("https://")
    host, _, path = rest.partition("/")
    host = host.removeprefix("www.")
    return f"{host}/{path}".rstrip("/")[:MAX_TITLE]


@dataclass(frozen=True)
class Fields:
    title: str
    text: str
    tags: tuple[str, ...]
    url: str | None
    owner_note: str


def _block(value: object, limit: int, what: str) -> str:
    if value is not None and not isinstance(value, str):
        raise invalid(f"The {what} must be text.")
    text = clean_block(value, limit)
    if len(text) > limit:
        raise invalid(f"The {what} is too long (at most {limit:,} characters).")
    return text


def check_sensitive(*parts: str) -> None:
    if any(sensitive_reason(p) for p in parts if p):
        raise NotesError(422, "sensitive", MSG_SENSITIVE)


def clean_fields(
    *,
    kind: str,
    text: object = "",
    title: object = None,
    tags: Any = None,
    url: object = None,
    owner_note: object = "",
) -> Fields:
    """Clean and check what the owner (or a tool for him) wrote. Raises `NotesError`."""
    if kind not in KINDS:
        raise invalid("The kind must be note, memo or link.")
    body = _block(text, MAX_TEXT, "note")
    note_text = _block(owner_note, MAX_OWNER_NOTE, "note about the link")
    if kind != "link" and not body:
        raise invalid("There is nothing to save: write something first.")
    if tags is not None and (
        not isinstance(tags, list | tuple) or not all(isinstance(t, str) for t in tags)
    ):
        raise invalid("Tags must be a list of words.")
    clean_tags = clean_keywords(tags)
    link = None
    if kind == "link":
        link = normalise_link(url)
        if private_part(link) is not None:
            raise NotesError(
                422, "bad_url", "That link holds private details, so it was not kept.", "private"
            )
    elif url not in (None, ""):
        raise invalid("Only a link has a web address.")
    if title is not None and not isinstance(title, str):
        raise invalid("The title must be text.")
    first = clean_text(title, MAX_TITLE) if title else ""
    if not first:
        first = _link_title(link) if link else clean_text(body.split("\n", 1)[0], DERIVED_TITLE)
    check_sensitive(first, body, note_text, *clean_tags)
    if not first:
        raise invalid("There is nothing to save: write something first.")
    return Fields(first, body, clean_tags, link, note_text)


__all__ = [
    "DERIVED_TITLE",
    "IMPORT_MAX_BYTES",
    "KINDS",
    "MAX_EXCERPT",
    "MAX_HITS",
    "MAX_LIVE",
    "MAX_OWNER_NOTE",
    "MAX_PAGE_TITLE",
    "MAX_TAGS",
    "MAX_TAG_CHARS",
    "MAX_TEXT",
    "MAX_TITLE",
    "MSG_FULL",
    "MSG_NOT_FOUND",
    "MSG_SENSITIVE",
    "NOTE_ID",
    "ORIGINS",
    "PAGE_SIZE",
    "SNIPPET_CHARS",
    "VOUCH_ORIGINS",
    "Fields",
    "Kind",
    "ImportResult",
    "Note",
    "NoteView",
    "NotesError",
    "NotesPage",
    "Origin",
    "PageExcerpt",
    "check_sensitive",
    "clean_fields",
    "host_of",
    "invalid",
    "normalise_link",
    "not_found",
    "unavailable",
    "vouches",
    "worse_origin",
]
