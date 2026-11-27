# tests/r63_fakes_d.py -- R6.3 part D's fakes (docs/plans/r6-3-book-content.md "The short tour's
# first script", D9; BRIEF-D). Imported bare (`from r63_fakes_d import ...`).
#
#   approved()        the owner's approved script, read from the PLAN's tables (approval stop 2,
#                     23 Nov 2026, 14:53 IST): scenes with their title, picture and audience, and
#                     every beat's words exactly as the plan writes them (placeholders included)
#   fill(text, vals)  the plan's own placeholders filled (independent of gen/tour.py's filler)
#   PLAN_VALUES       the facts table's "On 47ee8fc it would read" column, in A's forms (until A's
#                     branch joins, part D builds on this hand-made pack)
#   TOUR_FACTS        a FactPack holding exactly PLAN_VALUES (the 30 keys A computes)
#   OLD_BOOK          47ee8fc's real published book (tests/fixtures/r6_3): its show (11 scenes)
#                     is what a tour scene's `{"from_show": n}` copies; it has no tour
#   built(...)        gen/tour.build over TOUR_FACTS and OLD_BOOK.show
#   TourSource        the R6 fixture source, its book carrying a filled tour (the real routes)
from __future__ import annotations

import gzip
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from book_show_fakes import FixtureSource

from jarvis.buildbook.facts_model import FACT_TOUR_KEYS, FactPack, FactValue
from jarvis.buildbook.gen import tour
from jarvis.buildbook.model import Book, load_book
from jarvis.buildbook.tour_model import Tour, TourScript

ROOT = Path(__file__).resolve().parents[1]
PLAN = ROOT / "docs" / "plans" / "r6-3-book-content.md"
OLD_BOOK_GZ = ROOT / "tests" / "fixtures" / "r6_3" / "book-47ee8fc.json.gz"

_HEAD = re.compile(r"^### T(\d{2}) · (.+?) — picture (\d+)(?: \([^)]*\))? · ≈ \d+ s · (.+)$", re.M)
_ROW = re.compile(r"^\| (t\d{2}b\d{2})( · \*\*You only\*\*| · guests)? \| (.+?) \| .+ \|$", re.M)
_KEY = re.compile(r"\{\{([a-z0-9_.]+)\}\}")


@dataclass(frozen=True)
class ApprovedBeat:
    id: str
    audience: str  # both | owner | guest
    text: str


@dataclass(frozen=True)
class ApprovedScene:
    n: int
    title: str
    picture: int
    audience: str  # both | owner
    beats: tuple[ApprovedBeat, ...]


def _section() -> str:
    text = PLAN.read_text(encoding="utf-8")
    start = text.index("## The short tour's first script")
    return text[start : text.index("**Then, unchanged:**", start)]


def approved() -> tuple[ApprovedScene, ...]:
    """Every scene and beat of the approved script, as the plan's tables write them."""
    section = _section()
    heads = list(_HEAD.finditer(section))
    scenes = []
    for i, head in enumerate(heads):
        body = section[head.end() : heads[i + 1].start() if i + 1 < len(heads) else None]
        beats = tuple(
            ApprovedBeat(bid, "owner" if "You only" in mark else "guest" if mark else "both", text)
            for bid, mark, text in _ROW.findall(body)
        )
        who = "owner" if "You only" in head.group(4) else "both"
        scenes.append(
            ApprovedScene(int(head.group(1)), head.group(2), int(head.group(3)), who, beats)
        )
    return tuple(scenes)


def fill(text: str, values: dict[str, Any]) -> str:
    return _KEY.sub(lambda m: str(values[m.group(1)]), text)


PLAN_VALUES: dict[str, Any] = {
    "release.label": "R6.3",
    "release.version": "v6.3.0",
    "release.date": "24 Nov 2026",
    "release.new": "The Build Book: written by AI, short tour and full book",
    "cards.count": 73,
    "modules.count": 18,
    "modules.else_count": 12,  # R18: the Phone calls module is one of the others
    "loc.python_code": "124 thousand",
    "layers.count": 8,
    "brain.balanced_model": "Claude Sonnet 5.5",
    "undo.keep_days": 30,
    "keys.purposes": 26,
    "services.count": 31,
    "approvals.max_new_cards": 5,
    "memory.facts_per_turn": 12,
    "memory.learn_a_day": 20,
    "vault.unlock_minutes": 10,
    "vault.reminder_days_first": 180,
    "home.offline_minutes": 6,
    "sos.hold_s": 2,
    "sos.countdown_s": 5,
    "sos.max_contacts": 5,
    "sos.emergency": 112,
    "tryon.measures": 6,
    "seeme.inr_a_picture": "₹9",
    "seeme.month_cap_inr": "₹300",
    "libs.python_pins": 67,
    "costs.rate": 95.24,
    "roadmap.next": "R6.3.1, the Build Book's pictures and storage",
    "roadmap.after": "R6.4, the Book's new look",
}
assert set(PLAN_VALUES) == set(FACT_TOUR_KEYS)


def pack(values: dict[str, Any] | None = None) -> FactPack:
    vals = PLAN_VALUES if values is None else values
    return FactPack(
        values={k: FactValue(value=v, source="tests/r63_fakes_d.py") for k, v in vals.items()}
    )


TOUR_FACTS = pack()
OLD_BOOK: Book = load_book(gzip.decompress(OLD_BOOK_GZ.read_bytes()))


def built(
    facts: FactPack = TOUR_FACTS, *, script: TourScript | None = None, show: Any = OLD_BOOK.show
) -> Tour | None:
    return tour.build(None, facts, show=show, script=script)  # type: ignore[arg-type]


def with_tour(book: Book, filled: Tour | None) -> Book:
    return book.model_copy(update={"tour": filled})


class TourSource(FixtureSource):
    """The R6 fixture book with this branch's filled tour (or another): the real routes read it."""

    def __init__(self, filled: Tour | None = None) -> None:
        super().__init__()
        self.filled = filled

    def book(self) -> Book:
        return with_tour(super().book(), self.filled or built())


__all__ = [
    "OLD_BOOK",
    "PLAN",
    "PLAN_VALUES",
    "TOUR_FACTS",
    "ApprovedBeat",
    "ApprovedScene",
    "TourSource",
    "approved",
    "built",
    "fill",
    "pack",
    "with_tour",
]
