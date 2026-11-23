# src/jarvis/buildbook/writer/model.py
"""The Build Book's page shapes (R6.3 D3, D14; R6.3.1 D4, docs/plans/r6-3-1-book-at-build.md).
Pure data: frozen pydantic models (extra fields refused), no I/O, nothing from the app.

- A page: six sections (`SECTION_IDS`); the Workshop writes the first five as `## <heading>`
  blocks in `DRAFT_SECTIONS` order (the wire format of `book/pages/<page_id>.md`), `code` is
  generated. Numbers outside the made-up example are `{{fact:<key>}}` placeholders, filled from
  the release's fact pack when the generator compiles the page.
- `PageMeta` (R6.3.1 D8): who wrote a page and when, and the release it was compiled for. A page
  without one is the generator's plain text (`NOT_WRITTEN`).
- `PagesFile` (v2): ONE release's whole full book, every indexed page (written or the generator's
  text), the module titles and the limitations' count, so the reader's index needs nothing else.
  The generator writes it as `pages.json.gz` beside `book.json`; the sealer seals it with the
  release (D7).
- The runtime writer's old Firestore collections (R6.3, removed in R6.3.1 D8): named here only
  for the Privacy row that lets the owner delete what they still hold (D9).
"""

from __future__ import annotations

import re
from datetime import date
from typing import Literal

from pydantic import Field, model_validator

from jarvis.buildbook.facts_model import PAGE_ID, PageKind, PartId
from jarvis.buildbook.model import FLOWS_FILE_CAP_BYTES, PAGES_FILE_CAP_BYTES, RELEASE_ID, VERSION
from jarvis.buildbook.sections import Frozen

# ---- the files the generator writes beside book.json (R6.3.1 D4) --------------------------------
PAGES_FILE, FLOWS_FILE = "pages.json.gz", "flows.json"
PACK_CAP_BYTES = 96_000  # what `writer/packs.build` fits a page's pack into (R6.3 D4)
NOT_WRITTEN = "Not written yet"
EXAMPLE_MARK = "Example (made up)"
WRITTEN_BY_MAX = 60

# ---- the runtime writer's old collections (R6.3; D9: the Privacy row only) ---------------------
WRITER, LEASE, SPEND = "book_writer", "book_write_lease", "book_write_spend"
DRAFTS, TRIAL, PAGES_INDEX, PAGES_CHUNKS = "book_drafts", "book_trial", "book_pages", "book_chunks"
COLLECTIONS = (WRITER, LEASE, SPEND, DRAFTS, TRIAL, PAGES_INDEX)  # root collections


# ---- the page (D3, D10, D14) ---------------------------------------------------------------------
SectionId = Literal["plain", "example", "how", "costs", "fails", "code"]
SECTION_IDS: tuple[SectionId, ...] = ("plain", "example", "how", "costs", "fails", "code")
DRAFT_SECTIONS: tuple[SectionId, ...] = SECTION_IDS[:5]  # what is written; `code` is generated
HEADINGS: dict[SectionId, str] = {
    "plain": "In plain words",
    "example": EXAMPLE_MARK,
    "how": "How it works",
    "costs": "What it costs",
    "fails": "When it fails",
    "code": "Where in the code",
}
SECTION_CAPS: dict[SectionId, int] = {
    "plain": 900,
    "example": 900,
    "how": 2_400,
    "costs": 900,
    "fails": 900,
    "code": 2_400,
}
FACT_PLACEHOLDER = re.compile(r"\{\{fact:([A-Za-z0-9_\[][A-Za-z0-9_./:\[\]-]{0,199})\}\}")
CheckCode = Literal[
    "incomplete", "empty", "tier", "model", "refs", "numbers", "personal", "unverified",
    "invented", "planned", "shape",
]  # fmt: skip


class PageMeta(Frozen):
    """Who wrote a page and for which release (R6.3.1 D8): from its front matter and the
    release the generator compiled it in, never typed by a reader."""

    written_by: str = Field(min_length=1, max_length=WRITTEN_BY_MAX)
    written_on: date
    release: str = Field(pattern=RELEASE_ID)
    version: str | None = Field(default=None, pattern=VERSION)


class PageSection(Frozen):
    id: SectionId
    heading: str = Field(max_length=60)
    text: str = Field(max_length=2_400)
    refs: tuple[str, ...] = ()  # full, scrubbed paths (the reader's code chips)

    @model_validator(mode="after")
    def _capped(self) -> PageSection:
        if len(self.text) > SECTION_CAPS[self.id]:
            raise ValueError("a section is over its cap")
        return self


class Page(Frozen):
    id: str = Field(pattern=PAGE_ID)
    kind: PageKind
    title: str = Field(max_length=120)
    part: PartId
    chapter: str = Field(default="", max_length=60)
    sections: tuple[PageSection, ...]
    meta: PageMeta | None = None  # None: the generator's text ("Not written yet")

    @model_validator(mode="after")
    def _six(self) -> Page:
        if tuple(s.id for s in self.sections) != SECTION_IDS:
            raise ValueError("a page has the six sections, in order")
        return self


# ---- one release's full book (R6.3.1 D4) ---------------------------------------------------------
class PagesFile(Frozen):
    """Every indexed page of one release, in the index's order, gzipped JSON <= 2 MiB."""

    v: Literal[2] = 2
    release: str = Field(pattern=RELEASE_ID)
    pages: tuple[Page, ...] = ()
    modules: dict[str, str] = Field(default_factory=dict)  # module id -> its title (chapters)
    limitations: int = Field(default=0, ge=0)  # the fact pack's count (the reader's "+N more")

    @model_validator(mode="after")
    def _once(self) -> PagesFile:
        ids = [p.id for p in self.pages]
        if len(ids) != len(set(ids)):
            raise ValueError("a page is in the pages file once")
        return self


__all__ = [
    "COLLECTIONS",
    "DRAFTS",
    "DRAFT_SECTIONS",
    "EXAMPLE_MARK",
    "FACT_PLACEHOLDER",
    "FLOWS_FILE",
    "FLOWS_FILE_CAP_BYTES",
    "HEADINGS",
    "LEASE",
    "NOT_WRITTEN",
    "PACK_CAP_BYTES",
    "PAGES_CHUNKS",
    "PAGES_FILE",
    "PAGES_FILE_CAP_BYTES",
    "PAGES_INDEX",
    "SECTION_CAPS",
    "SECTION_IDS",
    "SPEND",
    "TRIAL",
    "WRITER",
    "CheckCode",
    "Page",
    "PageMeta",
    "PageSection",
    "PagesFile",
    "SectionId",
]
