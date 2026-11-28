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
title, publisher, year and address recorded in `SOURCE`: the American Heart Association's 2025
chart "Blood Pressure Categories"); with it empty `category_of` would answer None (no category is
shown). `trend_of` / `trend_line` give his own readings' trend in numbers, and `reading_view` the
two lines the pane shows beside a confirmed reading. Never a diagnosis, never a medicine or a dose:
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
# R8 I1 (the review's safety item): when the camera's lines are not a sure reading, the pane says
# so and asks for the numbers typed or the monitor held up again; it never guesses.
CANT_READ = "I can't read that screen. Please type the numbers, or hold it up and retake."
# R8 I1 (safety, must): above 180/120 the pane shows the American Heart Association's own steps,
# its source named, before anything else. Never a diagnosis, a medicine or a dose.
SEVERE_SYSTOLIC = 180  # a top number above this...
SEVERE_DIASTOLIC = 120  # ...or a bottom number above this: the AHA's steps are shown
SEVERE_STEPS = (
    "Above 180/120, the American Heart Association (Blood Pressure Categories, 2025) says: wait"
    " 5 minutes and measure again. If it is still that high, contact your doctor right away. If"
    " there is chest pain, shortness of breath, back pain, numbness or weakness, a change in"
    " vision or difficulty speaking, call emergency services now (112 in India)."
)


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


# The published table (builder D, 28 Nov 2026): the American Heart Association's chart "Blood
# Pressure Categories" (heart.org/bplevels, (c) 2025, WF-950650 9/25), its rows' names and numbers
# word for word, lowest first. "and" / "or" are the chart's own; its "and/or" rows are "or" here.
# Only the Severe Hypertension row tells the reader to call a health care professional, so only it
# carries "talk to your doctor". The chart's last row, Hypertensive Emergency, has the same numbers
# and is told apart only by symptoms, which JARVIS never asks about or names (the not-medical rule),
# so it is not a row here: such a reading shows as Severe Hypertension, with "talk to your doctor".
SOURCE: Source | None = Source(
    title="Blood Pressure Categories",
    publisher="American Heart Association",
    year=2025,
    url="https://www.heart.org/-/media/files/health-topics/high-blood-pressure/hbp-rainbow-chart-english.pdf",
)
CATEGORIES: tuple[BpCategory, ...] = (
    BpCategory("Normal", 0, 119, 0, 79, "and", False),
    BpCategory("Elevated", 120, 129, 0, 79, "and", False),
    BpCategory("Stage 1 Hypertension (High Blood Pressure)", 130, 139, 80, 89, "or", False),
    BpCategory("Stage 2 Hypertension (High Blood Pressure)", 140, None, 90, None, "or", False),
    BpCategory("Severe Hypertension", 181, None, 121, None, "or", True),
)
TREND_N = 5  # a trend compares his last five readings with the five before them


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


def severe(reading: BpProposal) -> bool:
    """Above 180/120 (either number): the reading the AHA's steps are shown for."""
    return reading.systolic > SEVERE_SYSTOLIC or reading.diastolic > SEVERE_DIASTOLIC


def category_line(row: BpCategory, source: Source) -> str:
    """The one sentence a category is shown in: its name and its source, nothing added."""
    line = f"{row.name} (by {source.publisher}, {source.title}, {source.year})."
    return f"{line} {TALK_TO_DOCTOR}" if row.talk_to_doctor else line


@dataclass(frozen=True)
class BpTrend:
    """His own readings over time: the mean of the last `count` (at most TREND_N) and, once there
    are TREND_N before them, how far the means moved (positive: higher). Numbers only."""

    count: int
    systolic: int
    diastolic: int
    pulse: int
    systolic_change: int | None
    diastolic_change: int | None


def _mean(values: Sequence[int]) -> int:
    return round(sum(values) / len(values))


def trend_of(readings: Sequence[BpReading]) -> BpTrend | None:
    """The trend of his confirmed readings (any order), or None when there are none."""
    ordered = sorted(readings, key=lambda r: r.taken_at)
    last, before = ordered[-TREND_N:], ordered[-2 * TREND_N : -TREND_N]
    if not last:
        return None
    sys_now, dia_now = _mean([r.systolic for r in last]), _mean([r.diastolic for r in last])
    full = len(before) == TREND_N
    return BpTrend(
        count=len(last),
        systolic=sys_now,
        diastolic=dia_now,
        pulse=_mean([r.pulse for r in last]),
        systolic_change=sys_now - _mean([r.systolic for r in before]) if full else None,
        diastolic_change=dia_now - _mean([r.diastolic for r in before]) if full else None,
    )


def _moved(change: int) -> str:
    return (
        "the same as"
        if change == 0
        else f"{abs(change)} {'higher' if change > 0 else 'lower'} than"
    )


def trend_line(t: BpTrend) -> str:
    """The trend in one sentence of numbers, nothing read into them."""
    some = "reading" if t.count == 1 else f"{t.count} readings"
    line = f"Your last {some}: on average {t.systolic}/{t.diastolic}, pulse {t.pulse}."
    if t.systolic_change is None or t.diastolic_change is None:
        return line
    return (
        f"{line} The top number is {_moved(t.systolic_change)} the {TREND_N} before, the bottom"
        f" number {_moved(t.diastolic_change)} them."
    )


def reading_view(reading: BpProposal, earlier: Sequence[BpReading]) -> dict[str, str | None]:
    """What the pane shows beside a confirmed reading: above 180/120 the AHA's own steps first
    (`steps`, R8 I1), then its category line (with its source) and the trend of his readings,
    this one included when it is a stored `BpReading`."""
    row = category_of(reading)
    mine = [*earlier, reading] if isinstance(reading, BpReading) else list(earlier)
    t = trend_of(mine)
    return {
        "steps": SEVERE_STEPS if severe(reading) else None,
        "category": category_line(row, SOURCE) if row is not None and SOURCE is not None else None,
        "trend": trend_line(t) if t is not None else None,
        "note": NOT_MEDICAL,
    }


__all__ = [
    "CANT_READ",
    "CATEGORIES",
    "NOT_MEDICAL",
    "SEVERE_DIASTOLIC",
    "SEVERE_STEPS",
    "SEVERE_SYSTOLIC",
    "SOURCE",
    "TALK_TO_DOCTOR",
    "TREND_N",
    "BpCategory",
    "BpConfirm",
    "BpProposal",
    "BpReading",
    "BpTrend",
    "Source",
    "category_line",
    "category_of",
    "proposal_from_digits",
    "reading_view",
    "severe",
    "trend_line",
    "trend_of",
]
