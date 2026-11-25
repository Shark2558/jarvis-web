# src/jarvis/buildbook/writer/http.py
"""The full book's HTTP contract (R6.3 "The HTTP contract"; R6.3.1 D7, D8: the writer's routes
are gone, the two pages routes stay): `api/book_pages.py` answers exactly these and the full
book's page, `/book/read` (R6.4: `console-book-read-*.js`), draws exactly these.

Both routes are the signed-in PRIMARY owner's (L11: another owner e-mail is 403 `not_primary`),
need an OWNER book session's `X-Jarvis-Book` (a guest's is 403 `owner_only`), pass
`book_gate.console_only` (a signed-in browser: never a bearer token), answer `Cache-Control:
no-store`, are rate-limited (`LIMITS`) and answer a refusal as `Refusal` (`{"error": <code>,
"detail": <plain words>}`). A page's JSON is `writer/model.Page` plus `flow`: its flowchart
(`book/flow.FlowSpec` as JSON, `from` by its alias) or null (R6.3.1 D7; part F draws it).
`ROUTES`: (method, path, part, request model, reply model, the statuses it may answer, gate).

R6.4 D4-D6 (docs/plans/r6-4-book-look.md), behind the same gates: `GET /v1/book/chapters` (the
release's chapters and, I1, its label, `ChaptersView`), `GET /v1/book/chapters/{chapter_id}` (one
chapter with its spoken lines, `ChapterView`; 404 `no_chapter`) and `GET /v1/book/pages/search?q=`
(`SearchView`; 422 `bad_query` unless `q` is 2 to 60 characters once trimmed; its own limit,
`LIMITS["search"]`).
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from jarvis.buildbook.book.chapters import CHAPTER_ID, ChapterKind
from jarvis.buildbook.facts_model import PAGE_ID, PageKind, PartId
from jarvis.buildbook.model import RELEASE_ID
from jarvis.buildbook.sections import RELEASE_LABEL, Frozen
from jarvis.buildbook.writer.model import ChapterLine, Page, PageMeta, ScriptMeta

ERRORS = (
    "book_off", "not_primary", "owner_only", "console_only", "no_page", "no_pages",
    "unavailable", "rate_limited", "no_chapter", "bad_query",
)  # fmt: skip
LIMITS = {"pages": 60, "search": 60}  # a minute, per owner (R6.4: the search's own)


class Refusal(Frozen):
    error: str = Field(pattern=r"^[a-z_]{2,32}$")
    detail: str = Field(max_length=300)


class PageRow(Frozen):
    id: str = Field(pattern=PAGE_ID)
    kind: PageKind
    title: str = Field(max_length=120)
    written: PageMeta | None = None


class Chapter(Frozen):
    id: str = Field(max_length=60)
    title: str = Field(max_length=120)
    pages: tuple[PageRow, ...] = ()


class BookPart(Frozen):
    id: PartId
    title: str = Field(max_length=60)
    chapters: tuple[Chapter, ...] = ()


class Shown(Frozen):
    shown: int = Field(ge=0)
    total: int = Field(ge=0)


class PagesView(Frozen):
    """`GET /v1/book/pages?release=` (owner session)."""

    release: str = Field(pattern=RELEASE_ID)
    parts: tuple[BookPart, ...] = ()
    limitations: Shown = Shown(shown=0, total=0)  # G4: "+N more in the full book"


# ---- R6.4 D4-D6: the chapters and the search ------------------------------------------------
class ChapterRow(Frozen):
    id: str = Field(pattern=CHAPTER_ID)
    title: str = Field(max_length=120)
    kind: ChapterKind
    pages: tuple[str, ...] = ()  # page ids, in the order they are told
    minutes: int = Field(default=0, ge=0)  # the narration's, at 150 words a minute; 0: not narrated
    narrated: bool = False
    lines: int = Field(default=0, ge=0)  # R6.4 I1: its spoken lines (Continue: "line 23 of 80")


class ChaptersView(Frozen):
    """`GET /v1/book/chapters?release=` (owner session). R6.4 I1: `label`, the sealed release's
    ("R6.4"), for the reader's chip; None when the view was built without one."""

    release: str = Field(pattern=RELEASE_ID)
    label: str | None = Field(default=None, pattern=RELEASE_LABEL)
    chapters: tuple[ChapterRow, ...] = ()


class ChapterPage(Frozen):
    id: str = Field(pattern=PAGE_ID)
    title: str = Field(max_length=120)


class ChapterView(Frozen):
    """`GET /v1/book/chapters/{chapter_id}?release=`: the chapter's pages and spoken lines (none
    when it isn't narrated in that release)."""

    release: str = Field(pattern=RELEASE_ID)
    id: str = Field(pattern=CHAPTER_ID)
    title: str = Field(max_length=120)
    kind: ChapterKind
    pages: tuple[ChapterPage, ...] = ()
    lines: tuple[ChapterLine, ...] = ()
    minutes: int = Field(default=0, ge=0)
    narrated: bool = False
    written: ScriptMeta | None = None


class SearchHit(Frozen):
    id: str = Field(pattern=PAGE_ID)
    title: str = Field(max_length=120)
    kind: PageKind
    snippet: str = Field(max_length=200)  # plain text; the reader marks `marks`
    marks: tuple[tuple[int, int], ...] = ()  # [start, end) in UTF-16 code units of `snippet`


class SearchView(Frozen):
    """`GET /v1/book/pages/search?q=&release=` (owner session, its own limit)."""

    release: str = Field(pattern=RELEASE_ID)
    q: str = Field(max_length=60)
    results: tuple[SearchHit, ...] = Field(default=(), max_length=20)
    total: int = Field(default=0, ge=0)  # every page that matched (results shows the first 20)


_E = (401, 403, 429)  # not signed in / not his console, not primary, too many
Gate = Literal["console", "session"]
ROUTES: tuple[tuple[str, str, str, object, object, tuple[int, ...], Gate], ...] = (
    ("GET", "/v1/book/pages", "E", None, PagesView, (*_E, 404, 503), "session"),
    # R6.4 D4: before `/{page_id}`, so "search" is never read as a page id
    ("GET", "/v1/book/pages/search", "I0", None, SearchView, (*_E, 404, 422, 503), "session"),
    ("GET", "/v1/book/pages/{page_id}", "E", None, Page, (*_E, 404, 503), "session"),
    ("GET", "/v1/book/chapters", "I0", None, ChaptersView, (*_E, 404, 503), "session"),
    ("GET", "/v1/book/chapters/{chapter_id}", "I0", None, ChapterView, (*_E, 404, 503), "session"),
)
PAGES_PREFIX = "/v1/book/pages"
CHAPTERS_PREFIX = "/v1/book/chapters"

__all__ = [
    "CHAPTERS_PREFIX",
    "ERRORS",
    "LIMITS",
    "PAGES_PREFIX",
    "ROUTES",
    "BookPart",
    "Chapter",
    "ChapterPage",
    "ChapterRow",
    "ChapterView",
    "ChaptersView",
    "SearchHit",
    "SearchView",
    "PageRow",
    "PagesView",
    "Refusal",
    "Shown",
]
