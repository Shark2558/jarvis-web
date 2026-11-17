# src/jarvis/wardrobe/tryon/versions.py
"""R13.1 D4 (AVT-02's store half, AVT-03): his measurements and their versions. Pure: documents
in, documents out; the time is passed in (no clock here).

- `draft(doc, typed, at)`: a draft from what he typed, over the draft or the current one. What he
  typed (now or before) stays typed; every other measurement is estimated from his height (his
  typed height, else the sample's) with preview v2's proportions (`model.estimated`), so the
  figure is "Estimated from your measurements". A value outside its range is `OutOfRange`, in
  `model.range_words`' words.
- `use(doc)`: "Use these measurements": the draft becomes current and the old current the first
  earlier one (at most five kept). `drop(doc)`: "Keep the current": the draft goes.
- Saved selections (his plans' piece ids, his saved comparisons) and his figure choices are never
  touched by a version (AVT-03).
- `body_view(b)` / `versions_view(doc)`: what the routes serve; every `BodyView` carries
  `model.morph_weights` (the engine contract's `body.weights`: the one rule, never a copy).
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime

from jarvis.wardrobe.tryon.http import BodyVersions, BodyView
from jarvis.wardrobe.tryon.model import (
    EARLIER_MAX,
    ESTIMATED,
    MEASURES,
    NO_FIGURE,
    SAMPLE,
    Body,
    Measure,
    estimated,
    in_range,
    morph_weights,
    range_words,
)
from jarvis.wardrobe.tryon.store import TryonDoc

NOTHING = "Type at least one measurement, in whole centimetres."
NO_DRAFT_USE = "There are no new measurements to use."
NO_DRAFT_DROP = "There are no new measurements to drop."


class OutOfRange(ValueError):
    """A value outside its range, in words ("The figure can be 150 to 195 cm tall")."""

    def __init__(self, measure: Measure) -> None:
        super().__init__(range_words(measure))
        self.measure = measure


class NothingTyped(ValueError):
    def __init__(self) -> None:
        super().__init__(NOTHING)


class NoDraft(LookupError):
    """Use or drop with no draft to use or drop."""


def typed_values(raw: Mapping[str, object]) -> dict[Measure, int]:
    """The measurements he typed (None: not typed), each in its range, in `MEASURES` order."""
    unknown = set(raw) - set(MEASURES)
    if unknown:
        raise ValueError("not one of the six measurements")
    out: dict[Measure, int] = {}
    for m in MEASURES:
        value = raw.get(m)
        if value is None:
            continue
        if not isinstance(value, int) or not in_range(m, value):
            raise OutOfRange(m)
        out[m] = value
    if not out:
        raise NothingTyped
    return out


def draft(doc: TryonDoc, raw: Mapping[str, object], at: datetime) -> TryonDoc:
    """The document with a new draft from what he typed (the current one stays in use)."""
    typed = typed_values(raw)
    base = doc.draft or doc.current
    mine: dict[Measure, int] = {m: getattr(base, m) for m in base.typed} if base else {}
    mine.update(typed)
    values: dict[Measure, int] = {**estimated(mine.get("height", SAMPLE["height"])), **mine}
    body = Body(**values, typed=tuple(m for m in MEASURES if m in mine), at=at)
    return doc.model_copy(update={"draft": body})


def use(doc: TryonDoc) -> TryonDoc:
    if doc.draft is None:
        raise NoDraft(NO_DRAFT_USE)
    earlier = ((doc.current,) if doc.current is not None else ()) + doc.earlier
    return doc.model_copy(
        update={"current": doc.draft, "draft": None, "earlier": earlier[:EARLIER_MAX]}
    )


def drop(doc: TryonDoc) -> TryonDoc:
    if doc.draft is None:
        raise NoDraft(NO_DRAFT_DROP)
    return doc.model_copy(update={"draft": None})


def body_view(b: Body) -> BodyView:
    values = b.values()
    return BodyView(**values, typed=b.typed, at=b.at, weights=morph_weights(values))


def versions_view(doc: TryonDoc) -> BodyVersions:
    return BodyVersions(
        current=body_view(doc.current) if doc.current is not None else None,
        draft=body_view(doc.draft) if doc.draft is not None else None,
        earlier=tuple(body_view(b) for b in doc.earlier),
    )


def figure_words(doc: TryonDoc) -> str:
    """ "Estimated from your measurements" once there is a figure, else "No figure yet: ..."."""
    return ESTIMATED if (doc.current or doc.draft) is not None else NO_FIGURE


__all__ = [
    "NOTHING",
    "NO_DRAFT_DROP",
    "NO_DRAFT_USE",
    "NoDraft",
    "NothingTyped",
    "OutOfRange",
    "body_view",
    "draft",
    "drop",
    "figure_words",
    "typed_values",
    "use",
    "versions_view",
]
