# src/jarvis/buildbook/writer/http.py
"""The full book's HTTP contract (R6.3 "The HTTP contract"; R6.3.1 D7, D8: the writer's routes
are gone, the two pages routes stay): `api/book_pages.py` answers exactly these and the console's
reader (`console-book-pages.js`) draws exactly these.

Both routes are the signed-in PRIMARY owner's (L11: another owner e-mail is 403 `not_primary`),
need an OWNER book session's `X-Jarvis-Book` (a guest's is 403 `owner_only`), pass
`book_gate.console_only` (a signed-in browser: never a bearer token), answer `Cache-Control:
no-store`, are rate-limited (`LIMITS`) and answer a refusal as `Refusal` (`{"error": <code>,
"detail": <plain words>}`). A page's JSON is `writer/model.Page` plus `flow`: its flowchart
(`book/flow.FlowSpec` as JSON, `from` by its alias) or null (R6.3.1 D7; part F draws it).
`ROUTES`: (method, path, part, request model, reply model, the statuses it may answer, gate).
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from jarvis.buildbook.facts_model import PAGE_ID, PageKind, PartId
from jarvis.buildbook.model import RELEASE_ID
from jarvis.buildbook.sections import Frozen
from jarvis.buildbook.writer.model import Page, PageMeta

ERRORS = (
    "book_off", "not_primary", "owner_only", "console_only", "no_page", "no_pages",
    "unavailable", "rate_limited",
)  # fmt: skip
LIMITS = {"pages": 60}  # a minute, per owner


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


_E = (401, 403, 429)  # not signed in / not his console, not primary, too many
Gate = Literal["console", "session"]
ROUTES: tuple[tuple[str, str, str, object, object, tuple[int, ...], Gate], ...] = (
    ("GET", "/v1/book/pages", "E", None, PagesView, (*_E, 404, 503), "session"),
    ("GET", "/v1/book/pages/{page_id}", "E", None, Page, (*_E, 404, 503), "session"),
)
PAGES_PREFIX = "/v1/book/pages"

__all__ = [
    "ERRORS",
    "LIMITS",
    "PAGES_PREFIX",
    "ROUTES",
    "BookPart",
    "Chapter",
    "PageRow",
    "PagesView",
    "Refusal",
    "Shown",
]
