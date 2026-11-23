# src/jarvis/buildbook/writer/model.py
"""R6.3 D3, D5-D8, D11-D13 (docs/plans/r6-3-book-content.md "Data model"): the Book writer's
shapes. Pure data: frozen pydantic models (extra fields refused), no I/O, nothing from the app;
part B stores and seals them, part C draws them (through `writer/http.py`'s views).

- A page (D3): six sections (`SECTION_IDS`); a brain writes the first five as `## <heading>`
  blocks in `DRAFT_SECTIONS` order (the wire format the fakes and B's prompt share), `code` is
  generated. Numbers outside the made-up example are `{{fact:<key>}}` placeholders (D10 (2)).
  `PageMeta` records what answered (D1): the tier is always BALANCED.
- Money (D7, D8): `Caps` with the owner's defaults and bounds (the trial's cap is his answer of
  23 Nov 2026: Rs 100), `Pick` with `confirmed` (what his last typed YES granted, all zero at
  first, H2), the spend ledger with its holds, and `about_inr` (L4: "about" is the mid rounded to
  Rs 10, Rs 5 under Rs 100, in every place).
- The writer's documents: `WriterDoc` (`book_writer/{uid}`), `Lease`, `SpendDoc`, `Draft`,
  `TrialPage`; the release's `PagesFile` and the pages index `PagesIndex` (D11, M4: its own sealed
  index beside R6's, AAD `book/pages/{uid}/v1`, purpose `book_index`; R6's index is never touched).
Ids: `wc_` + 16 hex a call, `we_` + 12 hex an estimate, `wt_` + 12 hex the terms a YES grants.
"""

from __future__ import annotations

import re
from typing import Literal

from pydantic import Field, model_validator

from jarvis.buildbook.facts_model import PAGE_ID, PageKind, PartId
from jarvis.buildbook.model import FILE_ID, RELEASE_ID, SHA256, VERSION, Instant
from jarvis.buildbook.sections import Frozen

# ---- collections (prefix `jarvis_`; flat ids) and sealing ----------------------------------------
WRITER, LEASE, SPEND = "book_writer", "book_write_lease", "book_write_spend"
DRAFTS, TRIAL, PAGES_INDEX, PAGES_CHUNKS = "book_drafts", "book_trial", "book_pages", "book_chunks"
COLLECTIONS = (WRITER, LEASE, SPEND, DRAFTS, TRIAL, PAGES_INDEX)  # root collections (R14's drill)
INDEX_PURPOSE = "book_index"  # the keyring's existing purpose: no new one (fact 16)


def aad_pages_index(uid: str) -> str:
    return f"book/pages/{uid}/v1"


CALL_ID, ESTIMATE_ID, TERMS_ID = r"^wc_[0-9a-f]{16}$", r"^we_[0-9a-f]{12}$", r"^wt_[0-9a-f]{12}$"
JOB_NAME = "book_write"
JOB_BUDGET_S, STEP_BUDGET_S, STEP_CALL_TIMEOUT_S = 45.0, 150.0, 120.0  # D5
MAX_TOKENS, PACK_CAP_BYTES, BYTES_PER_TOKEN_WORST = 4_000, 96_000, 2.5  # D4, D8
SYSTEM_TOKENS = 3_000  # the fixed system prompt, at the cache-write price in a hold (D8)
LEASE_S, SECONDS_KEPT, HOLD_BUSY_S, HOLD_STALE_S = 60, 20, 600, 3_600  # D5, D8
KEEP_DAYS = 30  # trial pages and drafts (owner question 11)
PAGES_FILE_CAP_BYTES = 2 * 1024 * 1024  # gzipped (D11)
TRIAL_PAGES: tuple[str, ...] = (  # D6, owner question 3
    "pg_chapter_example",
    "pg_card_c16",
    "pg_module_wardrobe",
    "pg_screen_vitals",
    "pg_service_telegram",
)
YES = "YES"
GST_NOTE = "Your Anthropic bill may add 18 % GST."
NOT_WRITTEN = "Not written by AI yet"
CHANGED_WAITING = "Changed in this release: waiting for your Update"
EXAMPLE_MARK = "Example (made up)"


def is_yes(typed: object) -> bool:
    """Exactly YES once trimmed ("yes", "Yes", "YES!" refused), the R13.1 rule."""
    return isinstance(typed, str) and typed.strip() == YES


def about_inr(mid: float) -> int:
    """L4: "about" is the mid rounded to the nearest Rs 10 (Rs 5 under Rs 100), everywhere."""
    step = 5 if mid < 100 else 10
    return int(step * round(mid / step))


# ---- the page (D3, D10, D14) ---------------------------------------------------------------------
SectionId = Literal["plain", "example", "how", "costs", "fails", "code"]
SECTION_IDS: tuple[SectionId, ...] = ("plain", "example", "how", "costs", "fails", "code")
DRAFT_SECTIONS: tuple[SectionId, ...] = SECTION_IDS[:5]  # what a brain writes; `code` is generated
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
    """What wrote a page (D1): from the `Written` result, never typed."""

    brain: str = Field(min_length=1, max_length=40)
    brain_label: str = Field(max_length=60)
    tier: Literal["balanced"] = "balanced"
    model: str = Field(min_length=1, max_length=80)
    provider: str = Field(max_length=40)
    release: str = Field(pattern=RELEASE_ID)
    version: str | None = Field(default=None, pattern=VERSION)
    written_at: Instant
    attempt: int = Field(ge=1, le=2)  # 2: the one redraft
    tokens_in: int = Field(ge=0)
    tokens_out: int = Field(ge=0)
    inr: float = Field(ge=0)


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
    meta: PageMeta | None = None  # None: the generator's text ("Not written by AI yet")
    changed: bool = False  # D11: changed in this release, waiting for his Update

    @model_validator(mode="after")
    def _six(self) -> Page:
        if tuple(s.id for s in self.sections) != SECTION_IDS:
            raise ValueError("a page has the six sections, in order")
        return self


# ---- money: caps, the pick and its grants (D7, D8, H2) -------------------------------------------
CAP_BOUNDS: dict[str, tuple[int, int]] = {
    "trial": (0, 200),
    "first": (0, 5_000),
    "release": (0, 2_000),
    "month": (0, 5_000),
    "limit_pct": (10, 100),
}


class Caps(Frozen):
    """Rupees (and the % line of his monthly limit). The defaults are proposals he confirms."""

    trial: int = Field(default=100, ge=0, le=200)  # his answer of 23 Nov 2026 (plan: Rs 60)
    first: int = Field(default=1_500, ge=0, le=5_000)
    release: int = Field(default=500, ge=0, le=2_000)
    month: int = Field(default=1_000, ge=0, le=5_000)
    limit_pct: int = Field(default=80, ge=10, le=100)


ZERO_CAPS = Caps(trial=0, first=0, release=0, month=0, limit_pct=10)


class Confirmed(Frozen):
    """What his last typed YES granted (H2): every non-zero cap above this is a raise."""

    brain: str | None = None
    caps: Caps = ZERO_CAPS
    auto_update: bool = False
    terms_id: str | None = Field(default=None, pattern=TERMS_ID)
    at: Instant | None = None


class Pick(Frozen):
    brain: str | None = None
    caps: Caps = Caps()
    auto_update: bool = False  # "update by itself within the release cap": off (question 7)
    picked_at: Instant | None = None
    confirmed: Confirmed = Confirmed()


class Consent(Frozen):
    at: Instant
    estimate_id: str = Field(pattern=ESTIMATE_ID)
    release: str = Field(pattern=RELEASE_ID)


RunKind = Literal["trial", "first", "update"]
RunState = Literal["queued", "running", "paused", "done", "stopped"]


class Run(Frozen):
    kind: RunKind
    release: str = Field(pattern=RELEASE_ID)
    estimate_id: str = Field(pattern=ESTIMATE_ID)
    state: RunState = "queued"
    why: str = Field(default="", max_length=200)  # plain words, never a vendor's
    total: int = Field(default=0, ge=0)
    done: int = Field(default=0, ge=0)
    failed: int = Field(default=0, ge=0)
    started_at: Instant | None = None
    ended_at: Instant | None = None


class UpdateReady(Frozen):
    release: str = Field(pattern=RELEASE_ID)
    estimate_id: str = Field(pattern=ESTIMATE_ID)
    pages: tuple[str, ...] = ()
    inr_mid: int = Field(ge=0)


# ---- the writer's documents (flat ids; each carries `owner` and `updated_at`) ------------------
class WriterDoc(Frozen):
    """`book_writer/{uid}`: ids, enums and numbers only (never page text or the creator name)."""

    owner: str = Field(min_length=1, max_length=128)
    pick: Pick = Pick()
    consents: dict[Literal["trial", "first"], Consent] = Field(default_factory=dict)
    run: Run | None = None
    update_ready: UpdateReady | None = None
    told: dict[str, tuple[Literal["pages", "update", "storage", "failed"], ...]] = Field(
        default_factory=dict
    )  # D11: the writer's own notice claims, per release
    seconds: dict[str, tuple[float, ...]] = Field(default_factory=dict)  # D5: last 20 a brain
    rev: int = Field(default=0, ge=0)
    updated_at: Instant | None = None


class Lease(Frozen):
    owner: str = Field(min_length=1, max_length=128)
    holder: str = Field(min_length=1, max_length=64)
    until: Instant
    updated_at: Instant | None = None


class Hold(Frozen):
    inr: float = Field(ge=0)
    at: Instant
    run: RunKind
    page: str = Field(pattern=PAGE_ID)


class SpendDoc(Frozen):
    """`book_write_spend/{uid}_{YYYY-MM}` (his IST month; numbers only, kept 13 months)."""

    owner: str = Field(min_length=1, max_length=128)
    spent_inr: float = Field(default=0.0, ge=0)
    held_inr: float = Field(default=0.0, ge=0)
    holds: dict[str, Hold] = Field(default_factory=dict)  # call id -> its hold
    runs: dict[str, float] = Field(default_factory=dict)  # "trial", "first", "update_<rid>"
    calls: int = Field(default=0, ge=0)
    refused: int = Field(default=0, ge=0)
    updated_at: Instant | None = None


DraftState = Literal["ok", "failed"]


class Draft(Frozen):
    """`book_drafts/{uid}_{rid}_{page}`: one page's draft; text and template in the sealed blob."""

    owner: str = Field(min_length=1, max_length=128)
    page: str = Field(pattern=PAGE_ID)
    attempt: int = Field(ge=1, le=2)
    state: DraftState
    checks: tuple[CheckCode, ...] = ()  # the checks it failed (empty: passed)
    meta: PageMeta
    blob: str = Field(min_length=1, repr=False)
    fid: str = Field(pattern=FILE_ID)
    updated_at: Instant | None = None


class TrialPage(Frozen):
    """`book_trial/{uid}_{nn}`, nn 01-10: one trial page, never sealed into a release (D6)."""

    owner: str = Field(min_length=1, max_length=128)
    nn: int = Field(ge=1, le=10)
    brain: str = Field(min_length=1, max_length=40)
    page: str = Field(pattern=PAGE_ID)
    attempt: int = Field(ge=1, le=2)
    checks: tuple[CheckCode, ...] = ()
    meta: PageMeta | None = None  # None: refused before anything was written
    seconds: float = Field(default=0.0, ge=0)
    inr: float = Field(default=0.0, ge=0)
    blob: str = Field(default="", repr=False)
    updated_at: Instant | None = None


# ---- the release's pages file and the pages index (D11, M4) -------------------------------------
class Skipped(Frozen):
    page: str = Field(pattern=PAGE_ID)
    why: str = Field(max_length=120)  # a check code, "cap", "stopped", "new_release", ...


class PagesFile(Frozen):
    """One release's AI pages, gzipped JSON <= 2 MiB, sealed with R6's chunk envelope."""

    v: Literal[1] = 1
    release: str = Field(pattern=RELEASE_ID)
    pages: tuple[Page, ...] = ()  # filled text
    templates: tuple[Page, ...] = ()  # the AI text with its placeholders (the free carry, D11)
    skipped: tuple[Skipped, ...] = ()


class PagesEntry(Frozen):
    release: str = Field(pattern=RELEASE_ID)
    fid: str = Field(pattern=FILE_ID)
    size: int = Field(ge=0, le=PAGES_FILE_CAP_BYTES)
    sha256: str = Field(pattern=SHA256)
    count: int = Field(ge=1, le=64)  # 512 KiB chunks
    dek: str = Field(min_length=1, max_length=512, repr=False)
    sealed_at: Instant
    written: int = Field(default=0, ge=0)
    changed: int = Field(default=0, ge=0)
    skipped: int = Field(default=0, ge=0)


class PagesPart(Frozen):
    """A pages file's chunks outside any entry: in flight (`pending`) or to delete (`orphans`)."""

    fid: str = Field(pattern=FILE_ID)
    count: int = Field(ge=1, le=64)
    since: Instant


class PagesIndex(Frozen):
    v: Literal[1] = 1
    files: tuple[PagesEntry, ...] = ()  # one a release: attach or replace (H3)
    pending: tuple[PagesPart, ...] = ()
    orphans: tuple[PagesPart, ...] = ()

    @model_validator(mode="after")
    def _one_a_release(self) -> PagesIndex:
        ids = [f.release for f in self.files]
        if len(ids) != len(set(ids)):
            raise ValueError("one pages file a release")
        return self

    def find(self, rid: str) -> PagesEntry | None:
        return next((f for f in self.files if f.release == rid), None)
