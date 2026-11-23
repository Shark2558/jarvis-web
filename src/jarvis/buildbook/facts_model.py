# src/jarvis/buildbook/facts_model.py
"""R6.3 D2, D3 (docs/plans/r6-3-book-content.md): the fact pack's ONE schema, `_book/facts.json`.

Computed at CI by the generator (`gen/facts.py` and `gen/pages_index.py`, part A), shipped in the
image beside `book.json` (its SHA-256 in `release.json` as `facts_sha256`), and read by the tour's
filler (part D), the writer's packs, checks and filler (part B) and, through B's routes, the reader
(part C). Pure data: frozen pydantic models, extra fields refused, no I/O.

- `values`: every NAMED fact a page or the tour may quote, `key -> FactValue` (its value, where it
  was read, and `verified`: False for a hosting or security fact until a live check, D2). Keys:
  the tour's (`FACT_TOUR_KEYS`, dotted), every literal module constant as `path:NAME` (scrubbed
  path, H5), every setting's default as `settings.<name>`, and A's own (`cards.count`, ...).
  A page writes `{{fact:<key>}}`; the tour writes `{{<key>}}` (`TOUR_TIMER_KEYS` are the timer's,
  filled by D, not stored here).
- `index`: what a page may cite (check (1), D10): every tracked path, every top-level function
  and class of `src/` as `path:symbol`, every constant, setting, collection and route. Every path
  is stored SCRUBBED (`Scrubber.clean`, H6), the same form packs, checks and code chips use.
- `routes`, `settings`, `collections`, `modules`, `cards`, `screens`, `services`, `loc`,
  `limitations` (all of them, G4), and `pages`: D3's pages index, every page of the full book
  with its full, scrubbed `refs`.
`canonical_facts` is THE byte form (sorted keys, NFC, compact UTF-8; the generator's `--check`
builds it twice); `load_facts` checks the 2 MiB cap first.
"""

from __future__ import annotations

import json
import unicodedata
from typing import Annotated, Literal

from pydantic import Field, ValidationError

from jarvis.buildbook.model import MIB, ReleaseRef
from jarvis.buildbook.sections import NAME, Frozen, Limitation

FACTS_FILE = "facts.json"
FACTS_JSON_CAP_BYTES = 2 * MIB  # I1: 1 MiB at I0; the joined pack was 1,018,018 bytes (97 %)
FACTS_JSON_WARN_BYTES = FACTS_JSON_CAP_BYTES * 4 // 5  # the generator warns past 80 %
FACT_KEY = r"^[A-Za-z0-9_\[][A-Za-z0-9_./:\[\]-]{0,199}$"
CARD_ID = r"^C[0-9]{2}$"
PAGE_ID = r"^pg_(?:chapter|module|card|screen|service)_[a-z0-9_]{1,40}$"
PageKind = Literal["chapter", "module", "card", "screen", "service"]
PartId = Literal["plain", "modules", "parts", "screens", "services"]
PARTS: tuple[tuple[PartId, str], ...] = (
    ("plain", "JARVIS in plain words"),
    ("modules", "Modules"),
    ("parts", "Parts"),
    ("screens", "Screens"),
    ("services", "Outside services"),
)
# D3's eight chapters of "JARVIS in plain words", as `pg_chapter_<id>`, in this order
CHAPTERS: tuple[tuple[str, str], ...] = (
    ("what", "What JARVIS is"),
    ("example", "The running example"),
    ("data", "Data, hosting, security and recovery"),
    ("answers", "How answers are made"),
    ("setup", "A local setup"),
    ("technology", "The technology inventory"),
    ("costs", "Costs"),
    ("planned", "What's planned"),
)
# The tour's facts table (the plan's "The tour's facts"): A computes every one of these into
# `values`; D fills the approved script from them. `tour.minutes` is the timer's (D), per audience.
FACT_TOUR_KEYS: tuple[str, ...] = (
    "release.label", "release.version", "release.date", "release.new",
    "cards.count", "modules.count", "modules.else_count", "loc.python_code", "layers.count",
    "brain.balanced_model", "undo.keep_days", "keys.purposes", "services.count",
    "approvals.max_new_cards", "memory.facts_per_turn", "memory.learn_a_day",
    "vault.unlock_minutes", "vault.reminder_days_first", "home.offline_minutes",
    "sos.hold_s", "sos.countdown_s", "sos.max_contacts", "sos.emergency",
    "tryon.measures", "seeme.inr_a_picture", "seeme.month_cap_inr", "libs.python_pins",
    "costs.rate", "roadmap.next", "roadmap.after",
)  # fmt: skip
TOUR_TIMER_KEYS: tuple[str, ...] = ("tour.minutes",)
Scalar = str | int | float | bool
FactKey = Annotated[str, Field(pattern=FACT_KEY)]


class FactValue(Frozen):
    value: Scalar
    source: str = Field(min_length=1, max_length=300)  # "src/jarvis/undo/models.py:RETENTION_DAYS"
    verified: bool = True  # D2: a hosting or security fact is False until a live check sets it


class FactIndex(Frozen):
    """Everything a page may cite (D10 check (1)); each tuple sorted, unique, scrubbed."""

    paths: tuple[str, ...] = ()
    symbols: tuple[str, ...] = ()  # "src/jarvis/llm/router.py:ModelRouter"
    constants: tuple[str, ...] = ()  # "src/jarvis/llm/fallback.py:BREAKER_S"
    settings: tuple[str, ...] = ()  # "vault_unlock_minutes"
    collections: tuple[str, ...] = ()  # "book_writer" (no prefix)
    routes: tuple[str, ...] = ()  # "GET /v1/book/pages"


class Route(Frozen):
    method: str = Field(pattern=r"^(?:GET|POST|PUT|PATCH|DELETE|HEAD|OPTIONS|WEBSOCKET)$")
    path: str = Field(min_length=1, max_length=200)
    module: str = Field(max_length=200)  # the scrubbed file that declares it


class Setting(Frozen):
    name: str = Field(pattern=NAME)
    kind: str = Field(max_length=80)  # the annotation, as written
    default: Scalar | None = None
    ge: float | None = None
    le: float | None = None


class ModuleFact(Frozen):
    id: str = Field(pattern=NAME)
    title: str = Field(max_length=80)
    cards: tuple[str, ...]


class CardFact(Frozen):
    id: str = Field(pattern=CARD_ID)
    title: str = Field(max_length=120)
    module: str = Field(pattern=NAME)
    refs: tuple[str, ...] = ()  # "Where in the code", resolved to full scrubbed paths (D3)
    services: tuple[str, ...] = ()  # "Outside services", as the coverage checker names them


class ScreenFact(Frozen):
    id: str = Field(pattern=NAME)  # the panel: `p-<id>` in console.html, or "show"
    title: str = Field(max_length=80)
    refs: tuple[str, ...] = ()  # its console modules and route files


class LineCount(Frozen):
    """D2a: one module's lines of one language in one area (shared code once, under its owner)."""

    module: str = Field(max_length=80)
    area: Literal["source", "tests", "config", "generated"]
    language: str = Field(max_length=20)
    files: int = Field(ge=0)
    code: int = Field(ge=0)
    docstring: int = Field(default=0, ge=0)
    comment: int = Field(ge=0)
    blank: int = Field(ge=0)


class IndexedPage(Frozen):
    """One page of the full book (D3): where it sits and what it may cite."""

    id: str = Field(pattern=PAGE_ID)
    kind: PageKind
    title: str = Field(max_length=120)
    part: PartId
    chapter: str = Field(default="", max_length=60)  # a page's module id (cards), else ""
    refs: tuple[str, ...] = ()  # full, scrubbed paths (a directory expanded to its files)
    sources: tuple[str, ...] = ()  # C-ids and plan paths it is written from


class FactPack(Frozen):
    v: Literal[1] = 1
    release: ReleaseRef | None = None
    values: dict[FactKey, FactValue] = Field(default_factory=dict)
    index: FactIndex = FactIndex()
    routes: tuple[Route, ...] = ()
    settings: tuple[Setting, ...] = ()
    collections: tuple[str, ...] = ()
    modules: tuple[ModuleFact, ...] = ()
    cards: tuple[CardFact, ...] = ()
    screens: tuple[ScreenFact, ...] = ()
    services: tuple[str, ...] = ()
    loc: tuple[LineCount, ...] = ()
    limitations: tuple[Limitation, ...] = ()
    pages: tuple[IndexedPage, ...] = ()

    def value(self, key: str) -> Scalar | None:
        got = self.values.get(key)
        return None if got is None else got.value

    def page(self, page_id: str) -> IndexedPage | None:
        return next((p for p in self.pages if p.id == page_id), None)


def canonical_facts(pack: FactPack) -> bytes:
    """THE bytes of facts.json: sorted keys, compact separators, UTF-8, NFC (like book.json)."""
    text = json.dumps(
        pack.model_dump(mode="json"), sort_keys=True, ensure_ascii=False, separators=(",", ":")
    )
    return unicodedata.normalize("NFC", text).encode("utf-8")


def load_facts(data: bytes) -> FactPack:
    """Parse facts.json. ValueError (never a partial pack): over 2 MiB, not JSON, not v1."""
    if len(data) > FACTS_JSON_CAP_BYTES:
        raise ValueError("facts.json is over its 2 MiB cap")
    try:
        return FactPack.model_validate_json(data)
    except ValidationError as exc:
        raise ValueError(
            f"facts.json is not a v1 fact pack ({exc.error_count()} problems)"
        ) from None


__all__ = [
    "CARD_ID",
    "CHAPTERS",
    "FACTS_FILE",
    "FACTS_JSON_CAP_BYTES",
    "FACTS_JSON_WARN_BYTES",
    "FACT_KEY",
    "FACT_TOUR_KEYS",
    "PAGE_ID",
    "PARTS",
    "TOUR_TIMER_KEYS",
    "CardFact",
    "FactIndex",
    "FactPack",
    "FactValue",
    "IndexedPage",
    "LineCount",
    "ModuleFact",
    "PageKind",
    "PartId",
    "Route",
    "ScreenFact",
    "Setting",
    "canonical_facts",
    "load_facts",
]
