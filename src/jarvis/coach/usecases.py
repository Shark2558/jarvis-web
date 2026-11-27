# src/jarvis/coach/usecases.py
"""R8 I0 seam S6 (docs/plans/r8-vision.md v8.0.3 sections 2, 4.3, 4.4; frozen: a change needs a
contract line in docs/plans/r8-integration/I0-SEAMS.md): every use case of R8 and R8.1.

Each `UseCase` has its id (the console's `JarvisVision.use` id, `^[a-z][a-z-]{1,20}$`), its
workbook row, its release, its spot (`desk`, `workout`, `table`), the camera source it runs on
(`jarvis.coach.sources`: `home` for the owner's D3 rows, which run on the home laptop), its
engine tasks and rate, whether its tally is health data (ADR-51), where its code lives (a console
module, or a `jarvis.coach.home` rule for a home use case) and its `Tally` model.

A tally is what is KEPT (D12, ADR-47): counts (whole numbers in ranges), seconds, scores 0..100,
labels from the use case's own fixed list, and the session's start and end (unix seconds).
Never a frame, a picture, a point or a box; never free text. `parse_tally(use, raw)` returns the
model or None: **a tally that doesn't fit is dropped, never repaired.** Rows 216, 217, 184, 377
and 183 have no use case (the engine, camera setup, privacy, the no-cloud check, screen time).

`VIEW_KINDS` are the widgets the panes draw from a use case's `summary(state).view` (the same
list as console-vision.js's `VIEW_KINDS`; the panes render them, a use case never touches the
page).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, create_model, model_validator

from jarvis.coach.sources import SourceKind

USE_ID = r"^[a-z][a-z-]{1,20}$"
VIEW_KINDS: tuple[str, ...] = (
    *("big", "line", "tip", "timer", "pacer", "targets", "checklist", "bar", "paused"),
)
Spot = Literal["desk", "workout", "table"]
Release = Literal["R8", "R8.1"]
DAY_S = 86_400

Count = Annotated[int, Field(ge=0, le=10_000, strict=True)]
Small = Annotated[int, Field(ge=0, le=500, strict=True)]
Seconds = Annotated[float, Field(ge=0.0, le=DAY_S)]
Ms = Annotated[int, Field(ge=0, le=60_000, strict=True)]
Score = Annotated[int, Field(ge=0, le=100, strict=True)]
Degrees = Annotated[float, Field(ge=0.0, le=180.0)]
Cm = Annotated[float, Field(ge=0.0, le=200.0)]
Metres = Annotated[float, Field(ge=0.0, le=10_000.0)]
Unix = Annotated[int, Field(ge=0, lt=10**11, strict=True)]
Flag = Annotated[bool, Field(strict=True)]


class Tally(BaseModel):
    """The kept shape every use case's tally extends: its session's start and end."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    started_at: Unix
    ended_at: Unix

    @model_validator(mode="after")
    def _span(self) -> Tally:
        if not 0 <= self.ended_at - self.started_at <= DAY_S:
            raise ValueError("a session ends after it starts, within a day")
        return self


class Segment(BaseModel):
    """One stretch of the day strip (row 182): only its kind, start and end are kept."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["desk", "away", "phone", "eating"]
    start: Unix
    end: Unix


def _labels(*names: str) -> Any:
    return Literal[names]


def _tally(name: str, **fields: Any) -> type[Tally]:
    model: type[Tally] = create_model(name, __base__=Tally, **fields)
    return model


# the use cases' own fixed lists (a label outside them is refused)
SEATED_MOVES = _labels(
    "arm_raise", "shoulder_roll", "torso_twist", "knee_lift", "ankle_pump", "neck_turn"
)
RHYTHMS = _labels("4-4", "4-7-8", "box", "6-a-minute", "5-5")
REHAB = _labels("open_close", "finger_tap", "thumb_to_finger")
STRENGTH = _labels("squat", "push_up", "lunge", "curl", "shoulder_press", "jumping_jack")
YOGA = _labels("mountain", "tree", "warrior_i", "warrior_ii", "triangle", "chair", "cobra", "child",
               "downward_dog", "bridge", "cat_cow", "seated_forward_bend")  # fmt: skip
SIDES = _labels("left", "right")
SUPPORT = _labels("wall", "spotter")

TALLIES: Mapping[str, type[Tally] | None] = MappingProxyType(
    {
        # ---- R8: the desk (home camera for posture, activity, seated, bp-posture: D3) --------
        "posture": _tally(
            "PostureTally",
            slouch_spans=(Small, ...),
            slouch_seconds=(Seconds, ...),
            nudges=(Small, ...),
            upright=(Score, ...),
        ),  # fmt: skip
        "activity": _tally("ActivityTally", segments=(tuple[Segment, ...], Field(max_length=200))),
        "reaction-game": _tally(
            "ReactionTally",
            targets=(Small, ...),
            hits=(Small, ...),
            best_ms=(Ms, ...),
            mean_ms=(Ms, ...),
            score=(Score, ...),
        ),  # fmt: skip
        "seated": _tally(
            "SeatedTally",
            move=(SEATED_MOVES, ...),
            sets=(Small, ...),
            reps=(Small, ...),
            target=(Small, ...),
            finished=(Flag, ...),
        ),  # fmt: skip
        "breath": _tally(
            "BreathTally",
            rhythm=(RHYTHMS, ...),
            minutes=(Seconds, ...),
            breaths=(Small, ...),
            per_minute=(Annotated[float, Field(ge=0, le=60)], ...),
        ),  # fmt: skip
        "water": _tally(
            "WaterTally",
            sips=(Small, ...),
            glasses=(Annotated[int, Field(ge=0, le=30, strict=True)], ...),
        ),
        "bp-posture": _tally(
            "BpPostureTally",
            back=(Flag, ...),
            feet=(Flag, ...),
            legs=(Flag, ...),
            arm=(Flag, ...),
            rested=(Flag, ...),
            still=(Flag, ...),
            score=(Score, ...),
        ),  # fmt: skip
        "hand-rehab": _tally(
            "HandRehabTally", exercise=(REHAB, ...), reps=(Small, ...), range_deg=(Degrees, ...)
        ),  # fmt: skip
        "reach-grasp": _tally(
            "ReachTally", reaches=(Small, ...), mean_ms=(Ms, ...), score=(Score, ...)
        ),
        # ---- R8.1: the workout spot (the tripod phone) and the table ---------------------------
        "reps": _tally(
            "RepsTally",
            exercise=(STRENGTH, ...),
            sets=(Small, ...),
            reps=(Small, ...),
            down_s=(Seconds, ...),
            up_s=(Seconds, ...),
        ),  # fmt: skip
        "warm-up": _tally("WarmUpTally", done=(Small, ...), of=(Small, ...)),
        "band": _tally("BandTally", reps=(Small, ...), prompts=(Small, ...)),
        "form": _tally(
            "FormTally",
            exercise=(STRENGTH, ...),
            reps=(Small, ...),
            clean=(Small, ...),
            tips=(Small, ...),
        ),  # fmt: skip
        "yoga": _tally("YogaTally", pose=(YOGA, ...), holds=(Small, ...), hold_s=(Seconds, ...)),
        "plank": _tally("PlankTally", hold_s=(Seconds, ...), sags=(Small, ...), pikes=(Small, ...)),
        "space-check": None,  # row 223: runs once before a session and keeps nothing
        "balance": _tally(
            "BalanceTally", side=(SIDES, ...), hold_s=(Seconds, ...), sway=(Score, ...)
        ),
        "boxing": _tally(
            "BoxingTally",
            punches=(Count, ...),
            jabs=(Count, ...),
            crosses=(Count, ...),
            hooks=(Count, ...),
            uppercuts=(Count, ...),
            about=(Flag, ...),
        ),  # fmt: skip
        "agility": _tally(
            "AgilityTally",
            marks=(Annotated[int, Field(ge=2, le=12, strict=True)], ...),
            splits=(Small, ...),
            best_s=(Seconds, ...),
            total_s=(Seconds, ...),
        ),  # fmt: skip
        "pilates": _tally("PilatesTally", done=(Small, ...), out_of_order=(Small, ...)),
        "tai-chi": _tally("TaiChiTally", done=(Small, ...), smooth=(Score, ...)),
        "jump": _tally(
            "JumpTally",
            jumps=(Small, ...),
            best_cm=(Cm, ...),
            stiff=(Small, ...),
            knees_in=(Small, ...),
            about=(Flag, ...),
        ),  # fmt: skip
        "dance": _tally(
            "DanceTally",
            routine=(Annotated[int, Field(ge=1, le=20, strict=True)], ...),
            sync=(Score, ...),
        ),  # fmt: skip
        "handstand": _tally(
            "HandstandTally", support=(SUPPORT, ...), hold_s=(Seconds, ...), drifts=(Small, ...)
        ),  # fmt: skip
        "kettlebell": _tally("KettlebellTally", swings=(Count, ...), hinge=(Score, ...)),
        "partner-stretch": _tally(
            "PartnerStretchTally",
            stretches=(Small, ...),
            hold_s=(Seconds, ...),
            range_deg=(Degrees, ...),
        ),  # fmt: skip
        "walk-test": _tally(
            "WalkTestTally",
            course_m=(Annotated[float, Field(ge=1, le=100)], ...),
            laps=(Small, ...),
            turns=(Small, ...),
            metres=(Metres, ...),
        ),  # fmt: skip
        "sit-to-stand": _tally("SitToStandTally", in_30s=(Small, ...), five_s=(Seconds, ...)),
        "meal": _tally(
            "MealTally",
            bites=(Count, ...),
            minutes=(Seconds, ...),
            per_minute=(Annotated[float, Field(ge=0, le=60)], ...),
        ),  # fmt: skip
    }
)


@dataclass(frozen=True)
class UseCase:
    id: str
    row: int
    release: Release
    spot: Spot
    source: SourceKind
    tasks: tuple[str, ...]
    rate: float  # frames a second it asks for (the engine caps it at the task's own)
    health: bool  # ADR-51: sealed health data, its own Privacy rows, never interpreted
    module: str  # a console module (console-coach-<x>.js) or a home rule (jarvis.coach.home.<x>)

    @property
    def tally(self) -> type[Tally] | None:
        return TALLIES[self.id]

    @property
    def keeps(self) -> bool:
        return TALLIES[self.id] is not None


def _uc(uid: str, row: int, release: Release, spot: Spot, source: SourceKind, tasks: str,
        rate: float, health: bool, module: str) -> UseCase:  # fmt: skip
    return UseCase(uid, row, release, spot, source, tuple(tasks.split()), rate, health, module)


def _js(name: str) -> str:
    return f"console-coach-{name}.js"


def _home(name: str) -> str:
    return f"jarvis.coach.home.{name}"


B: SourceKind = "browser"
P: SourceKind = "phone"
H: SourceKind = "home"
USE_CASES: tuple[UseCase, ...] = (
    # R8 (14 rows; 216, 217, 184, 377 and 183 have no use case)
    _uc("posture", 181, "R8", "desk", H, "pose", 1, True, _home("posture")),
    _uc("activity", 182, "R8", "desk", H, "pose objects", 1, False, _home("activity")),
    _uc("reaction-game", 224, "R8", "desk", B, "hands", 15, True, _js("reaction")),
    _uc("seated", 227, "R8", "desk", H, "pose", 15, True, _home("seated")),
    _uc("breath", 238, "R8", "desk", B, "pose", 10, True, _js("breath")),
    _uc("water", 248, "R8", "desk", B, "hands objects", 2, False, _js("water")),
    _uc("bp-posture", 262, "R8", "desk", H, "pose objects", 2, True, _home("bp_posture")),
    _uc("hand-rehab", 268, "R8", "desk", B, "hands", 15, True, _js("handrehab")),
    _uc("reach-grasp", 276, "R8", "desk", B, "hands objects", 15, True, _js("reach")),
    # R8.1 (20 rows): the tripod phone, and the table for 247
    _uc("reps", 132, "R8.1", "workout", P, "pose", 15, True, _js("reps")),
    _uc("warm-up", 218, "R8.1", "workout", P, "pose", 15, True, _js("warmup")),
    _uc("band", 219, "R8.1", "workout", P, "pose", 15, True, _js("band")),
    _uc("form", 220, "R8.1", "workout", P, "pose", 15, True, _js("form")),
    _uc("yoga", 221, "R8.1", "workout", P, "pose", 10, True, _js("yoga")),
    _uc("plank", 222, "R8.1", "workout", P, "pose", 10, True, _js("plank")),
    _uc("space-check", 223, "R8.1", "workout", P, "objects pose", 2, False, _js("space")),
    _uc("balance", 226, "R8.1", "workout", P, "pose", 15, True, _js("balance")),
    _uc("boxing", 228, "R8.1", "workout", P, "pose", 15, True, _js("boxing")),
    _uc("agility", 230, "R8.1", "workout", P, "pose", 15, True, _js("agility")),
    _uc("pilates", 231, "R8.1", "workout", P, "pose", 10, True, _js("pilates")),
    _uc("tai-chi", 232, "R8.1", "workout", P, "pose", 10, True, _js("taichi")),
    _uc("jump", 235, "R8.1", "workout", P, "pose", 15, True, _js("jump")),
    _uc("dance", 236, "R8.1", "workout", P, "pose", 15, True, _js("dance")),
    _uc("handstand", 237, "R8.1", "workout", P, "pose", 10, True, _js("handstand")),
    _uc("kettlebell", 239, "R8.1", "workout", P, "pose", 15, True, _js("kettlebell")),
    _uc("partner-stretch", 240, "R8.1", "workout", P, "pose", 10, True, _js("partner")),
    _uc("walk-test", 263, "R8.1", "workout", P, "pose", 10, True, _js("walk")),
    _uc("sit-to-stand", 269, "R8.1", "workout", P, "pose", 15, True, _js("sitstand")),
    _uc("meal", 247, "R8.1", "table", P, "pose hands", 10, True, _js("meal")),
)
BY_ID: Mapping[str, UseCase] = MappingProxyType({u.id: u for u in USE_CASES})
ROWS_WITHOUT_USE_CASE: tuple[int, ...] = (216, 217, 184, 377, 183)
R8_ROWS: tuple[int, ...] = (216, 217, 184, 377, 181, 182, 183, 224, 227, 238, 248, 262, 268, 276)
R81_ROWS: tuple[int, ...] = tuple(u.row for u in USE_CASES if u.release == "R8.1")


def parse_tally(use: str, raw: object) -> Tally | None:
    """The use case's tally, else None: an unknown use case, one that keeps nothing, or a tally
    that doesn't fit its model (dropped, never repaired)."""
    model = TALLIES.get(use) if isinstance(use, str) else None
    if model is None or not isinstance(raw, dict):
        return None
    try:
        return model.model_validate(raw)
    except ValidationError:
        return None


def listing() -> list[dict[str, Any]]:
    """`GET /v1/coach/usecases`: what the panes need (never a tally)."""
    return [
        {
            "id": u.id,
            "row": u.row,
            "release": u.release,
            "spot": u.spot,
            "source": u.source,
            "tasks": list(u.tasks),
            "rate": u.rate,
            "health": u.health,
            "keeps": u.keeps,
            "module": u.module if u.module.endswith(".js") else "",
        }
        for u in USE_CASES
    ]


__all__ = [
    "BY_ID",
    "R81_ROWS",
    "R8_ROWS",
    "ROWS_WITHOUT_USE_CASE",
    "TALLIES",
    "USE_CASES",
    "USE_ID",
    "VIEW_KINDS",
    "Segment",
    "Tally",
    "UseCase",
    "listing",
    "parse_tally",
]
