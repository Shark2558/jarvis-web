# src/jarvis/coach/bp.py
"""R8 I0 seam S26 (docs/plans/r8-vision.md v8.0.3 D7; row 262): the blood-pressure reading.

The owner's words: "Reading needs to be identified by the camera automatically and used and
confirm." So:

1. The webcam reads the monitor's seven-segment display on the device (the engine's `digits`
   task: its lines top to bottom). `proposal_from_digits` turns the three lines into a
   `BpProposal` (systolic, diastolic, pulse) or None when they can't be one (never a guess).
2. The pane shows the proposal; he **confirms or corrects** it (`BpConfirm`). Nothing is stored
   before that: an unconfirmed proposal never reaches the server's store.
3. A confirmed `BpReading` is sealed with the other coach results (`coach`, ADR-51) and used: a
   trend (his own readings over time) and the standard published category **with its source
   named**, and "talk to your doctor" where that category says so.

`CATEGORIES` is the published table, filled by builder D **from the named source only** (its
title, publisher, year and address recorded in `SOURCE`); it ships empty at I0, and with it empty
`category_of` answers None (no category is shown). Never a diagnosis, never a medicine or a dose:
the category's own name and its source, nothing JARVIS adds (tests/test_r8_not_medical.py).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Systolic = Annotated[int, Field(ge=60, le=260, strict=True)]
Diastolic = Annotated[int, Field(ge=30, le=160, strict=True)]
Pulse = Annotated[int, Field(ge=30, le=220, strict=True)]
READ_MIN_SCORE = 0.8  # a line read with less confidence is not proposed
TALK_TO_DOCTOR = "Talk to your doctor about this reading."
NOT_MEDICAL = "Practice only, not medical advice."


class BpProposal(BaseModel):
    """What the camera read, shown to him; never stored."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    systolic: Systolic
    diastolic: Diastolic
    pulse: Pulse

    @model_validator(mode="after")
    def _order(self) -> BpProposal:
        if self.diastolic >= self.systolic:
            raise ValueError("the top number is the larger one")
        return self


class BpReading(BpProposal):
    """A reading he confirmed (from the camera) or typed: the only kind that is stored."""

    taken_at: Annotated[int, Field(ge=0, lt=10**11, strict=True)]
    source: Literal["camera", "typed"]


class BpConfirm(BaseModel):
    """`POST /v1/coach/bp/readings`: his answer to a proposal (or a typed reading)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    confirmed: Literal[True]  # an unconfirmed reading is never sent
    reading: BpReading
    corrected: bool = False  # he changed what the camera read


@dataclass(frozen=True)
class BpCategory:
    """One row of the published table (builder D fills it from `SOURCE`, word for word)."""

    name: str
    systolic_from: int
    systolic_to: int | None
    diastolic_from: int
    diastolic_to: int | None
    match: Literal["and", "or"]
    talk_to_doctor: bool


@dataclass(frozen=True)
class Source:
    title: str
    publisher: str
    year: int
    url: str


SOURCE: Source | None = None  # builder D: the guideline the table is copied from
CATEGORIES: tuple[BpCategory, ...] = ()


def proposal_from_digits(lines: Sequence[tuple[int, float]]) -> BpProposal | None:
    """Three lines (value, score) top to bottom -> a proposal, else None (never a guess)."""
    if len(lines) != 3 or any(score < READ_MIN_SCORE for _, score in lines):
        return None
    try:
        return BpProposal(systolic=lines[0][0], diastolic=lines[1][0], pulse=lines[2][0])
    except ValueError:
        return None


def _within(v: int, lo: int, hi: int | None) -> bool:
    return v >= lo and (hi is None or v <= hi)


def category_of(reading: BpProposal) -> BpCategory | None:
    """The table's highest matching row (its order is the source's, lowest first); None while
    the table is empty or nothing matches."""
    found = None
    for row in CATEGORIES:
        sys_ok = _within(reading.systolic, row.systolic_from, row.systolic_to)
        dia_ok = _within(reading.diastolic, row.diastolic_from, row.diastolic_to)
        if (sys_ok and dia_ok) if row.match == "and" else (sys_ok or dia_ok):
            found = row
    return found


def category_line(row: BpCategory, source: Source) -> str:
    """The one sentence a category is shown in: its name and its source, nothing added."""
    line = f"{row.name} (by {source.publisher}, {source.title}, {source.year})."
    return f"{line} {TALK_TO_DOCTOR}" if row.talk_to_doctor else line


__all__ = [
    "CATEGORIES",
    "NOT_MEDICAL",
    "SOURCE",
    "TALK_TO_DOCTOR",
    "BpCategory",
    "BpConfirm",
    "BpProposal",
    "BpReading",
    "Source",
    "category_line",
    "category_of",
    "proposal_from_digits",
]
