# src/jarvis/buildbook/writer/http.py
"""R6.3's HTTP contract (docs/plans/r6-3-book-content.md "The HTTP contract"), written at I0 before
the parts start: B's `api/book_writer.py` and `api/book_pages.py` answer exactly these, C's
console draws exactly these, and `tests/r63_fake_server.py` serves them from fakes until I1. A
change here is a seam change with a line in that part's INTEGRATION file.

Every route is the signed-in PRIMARY owner's (L11: another owner e-mail is 403 `not_primary`),
`Cache-Control: no-store`, CSRF as every cookie write (`X-Requested-With`), rate-limited (`LIMITS`),
and answers a refusal as `Refusal` (`{"error": <code>, "detail": <plain words>}`: the console
branches on the code and shows the words). `console` routes pass `book_gate.console_only` (a
signed-in browser: never a bearer token, never a guest's show-only browser); `session` routes need
an OWNER book session's `X-Jarvis-Book` (a guest's is 403 `owner_only`). Rupees only: no dollar
figure ever leaves the server, and no rupee figure the page sends is trusted (it re-estimates).
`ROUTES`: (method, path, part, request model, reply model, the statuses it may answer, gate).
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from jarvis.buildbook.facts_model import PAGE_ID, PageKind, PartId
from jarvis.buildbook.model import RELEASE_ID
from jarvis.buildbook.sections import Frozen
from jarvis.buildbook.writer.model import (
    ESTIMATE_ID,
    TERMS_ID,
    Caps,
    CheckCode,
    Page,
    PageMeta,
    Pick,
    RunKind,
    RunState,
    UpdateReady,
)

NOT_BUILT = "not_built_yet"  # I0's stub routes: 503 with this code until B fills them
ERRORS = (
    "not_built_yet", "book_off", "not_primary", "owner_only", "console_only", "no_key", "no_ai",
    "no_brain", "not_yes", "yes_needed", "terms_changed", "estimate_changed", "running", "busy",
    "pick_needed", "already_written", "nothing_to_update", "use_first", "bad_cap",
    "unknown_brain", "not_offered", "no_page", "rate_limited",
)  # fmt: skip
LIMITS = {"reads": 30, "writes": 10, "step": 6, "pages": 60}  # a minute, per owner


class Refusal(Frozen):
    error: str = Field(pattern=r"^[a-z_]{2,32}$")
    detail: str = Field(max_length=300)


# ---- requests ------------------------------------------------------------------------------------
class TrialIn(Frozen):
    typed: str = Field(max_length=20)
    estimate_id: str = Field(pattern=ESTIMATE_ID)


class PickIn(Frozen):
    brain: str = Field(min_length=1, max_length=40)
    caps: Caps
    auto_update: bool = False
    typed: str | None = Field(default=None, max_length=20)
    terms_id: str | None = Field(default=None, pattern=TERMS_ID)


class RunIn(Frozen):
    """`POST …/first` and `POST …/update`: his typed YES on the estimate he was shown."""

    typed: str = Field(max_length=20)
    estimate_id: str = Field(pattern=ESTIMATE_ID)


# ---- replies -------------------------------------------------------------------------------------
class YesNeeded(Frozen):
    """422 `yes_needed` on `PUT …/pick`: nothing saved; the console shows `words` above the YES
    box and resends the same pick with `typed: "YES"` and this `terms_id` (H2)."""

    error: Literal["yes_needed"] = "yes_needed"
    detail: str = Field(max_length=300)
    terms_id: str = Field(pattern=TERMS_ID)
    words: tuple[str, ...] = Field(min_length=1, max_length=6)  # the Rs words, plain


class BrainOffer(Frozen):
    id: str = Field(min_length=1, max_length=40)
    label: str = Field(max_length=60)
    trains_on_content: bool
    model_name: str = Field(default="", max_length=80)  # the registry's BALANCED model
    offered: bool
    note: str = Field(default="", max_length=120)  # "not set up on this server", "price unknown…"


class TrialView(Frozen):
    state: RunState | Literal["none"] = "none"
    done: int = Field(default=0, ge=0)
    total: int = Field(default=0, ge=0)
    inr: float = Field(default=0.0, ge=0)
    results: tuple[int, ...] = ()  # the trial pages' nn


class RunView(Frozen):
    kind: RunKind | None = None
    state: RunState | Literal["none"] = "none"
    done: int = Field(default=0, ge=0)
    total: int = Field(default=0, ge=0)
    inr: float = Field(default=0.0, ge=0)
    cap_inr: int = Field(default=0, ge=0)
    why: str = Field(default="", max_length=200)


class MonthView(Frozen):
    book_inr: float = Field(ge=0)
    limit_inr: float | None = None  # None: no monthly limit set (the Book's caps only)
    line_inr: float | None = None  # the % line of his limit


class StorageView(Frozen):
    used_mib: float = Field(ge=0)
    pages_mib: float = Field(ge=0)
    limit_mib: float = Field(ge=0)
    warn: bool  # R6's sealed total + the pages files past 80 % of the limit (D11)


class WriterView(Frozen):
    """`GET /v1/book/writer`."""

    on: bool
    why: Literal["no_key", "no_ai", "no_brain"] | None = None
    brains: tuple[BrainOffer, ...] = ()
    trial: TrialView = TrialView()
    pick: Pick = Pick()
    run: RunView = RunView()
    update_ready: UpdateReady | None = None
    month: MonthView = MonthView(book_inr=0.0)
    storage: StorageView = StorageView(used_mib=0.0, pages_mib=0.0, limit_mib=60.0, warn=False)


class Estimate(Frozen):
    """`GET /v1/book/writer/estimate?run=`: Rs only, "about" by `about_inr` (L4)."""

    id: str = Field(pattern=ESTIMATE_ID)
    run: RunKind
    brain: str = Field(min_length=1, max_length=40)
    pages: int = Field(ge=0)
    low: int = Field(ge=0)
    mid: int = Field(ge=0)
    high: int = Field(ge=0)
    hold: float = Field(ge=0)  # one worst-case call (D8)
    cap: int = Field(ge=0)
    minutes_low: int = Field(ge=0)
    minutes_high: int = Field(ge=0)
    gst_note: str = Field(max_length=120)
    sent_to: tuple[str, ...] = ()  # plain words: who reads what is sent


class TrialRow(Frozen):
    nn: int = Field(ge=1, le=10)
    page: str = Field(pattern=PAGE_ID)
    brain: str = Field(max_length=40)
    state: Literal["first", "redrafted", "refused"]
    checks: tuple[CheckCode, ...] = ()
    inr: float = Field(ge=0)
    seconds: float = Field(ge=0)


class TrialPages(Frozen):
    rows: tuple[TrialRow, ...] = ()


class TrialPageView(Frozen):
    nn: int = Field(ge=1, le=10)
    page: Page
    checks: tuple[CheckCode, ...] = ()


class PageRow(Frozen):
    id: str = Field(pattern=PAGE_ID)
    kind: PageKind
    title: str = Field(max_length=120)
    written: PageMeta | None = None
    changed: bool = False


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


class Deleted(Frozen):
    deleted: int = Field(ge=0)


_E = (401, 403, 429)  # not signed in / not his console, not primary, too many
_W = "/v1/book/writer"
Gate = Literal["console", "session"]
ROUTES: tuple[tuple[str, str, str, object, object, tuple[int, ...], Gate], ...] = (
    ("GET", _W, "B", None, WriterView, (*_E, 503), "console"),
    ("GET", f"{_W}/estimate", "B", None, Estimate, (*_E, 409, 422, 503), "console"),
    ("POST", f"{_W}/trial", "B", TrialIn, RunView, (*_E, 409, 422, 503), "console"),
    ("PUT", f"{_W}/pick", "B", PickIn, Pick, (*_E, 409, 422, 503), "console"),
    ("POST", f"{_W}/first", "B", RunIn, RunView, (*_E, 409, 422, 503), "console"),
    ("POST", f"{_W}/update", "B", RunIn, RunView, (*_E, 409, 422, 503), "console"),
    ("POST", f"{_W}/stop", "B", None, RunView, (*_E, 409, 503), "console"),
    ("POST", f"{_W}/step", "B", None, RunView, (*_E, 409, 503), "console"),
    ("GET", f"{_W}/trial/pages", "B", None, TrialPages, (*_E, 503), "console"),
    ("GET", f"{_W}/trial/pages/{{nn}}", "B", None, TrialPageView, (*_E, 404, 503), "console"),
    ("DELETE", f"{_W}/trial", "B", None, Deleted, (*_E, 409, 503), "console"),
    ("GET", "/v1/book/pages", "B", None, PagesView, (*_E, 404, 503), "session"),
    ("GET", "/v1/book/pages/{page_id}", "B", None, Page, (*_E, 404, 503), "session"),
)
WRITER_PREFIX, PAGES_PREFIX = _W, "/v1/book/pages"
