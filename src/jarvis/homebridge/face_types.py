# src/jarvis/homebridge/face_types.py
"""Plain data for the laptop's face groups (R11.1 O7; plan D15). Ships in the home kit.

`SeenFace` is what a face engine hands the store for one face of one picture; `Placed`,
`GroupRow` and `Counts` are what the store answers. None of them is ever sent to the cloud as it
is: the bridge's signed answers are built from ids and counts only. Standard library only.
"""

from __future__ import annotations

import math
import re
from collections.abc import Sequence
from dataclasses import dataclass

DIM = 128  # SFace's embedding size
MIN_GROUP_PICS = 3
GROUP = re.compile(r"^c_[0-9a-f]{12}$")  # always used with fullmatch as well
PERSON = re.compile(r"^fp_[0-9a-f]{12}$")
JPEG = b"\xff\xd8\xff"


class UnknownGroup(LookupError):
    """There is no such group on this laptop."""


class AlreadyNamed(Exception):
    """The group already carries another person's id."""


@dataclass(frozen=True)
class SeenFace:
    """One face an engine found in a picture. `crop` is a small JPEG; it never leaves the laptop."""

    vector: tuple[float, ...]
    score: float  # the detector's confidence, 0..1
    size: int  # the face's shorter side in the picture, in pixels
    crop: bytes

    @property
    def quality(self) -> float:
        return float(self.score) * float(self.size)


@dataclass(frozen=True)
class Placed:
    group: str
    person: str | None
    cosine: float  # likeness to the group it joined; 0.0 for a group this face started


@dataclass(frozen=True)
class GroupRow:
    id: str
    n: int | None
    person: str | None
    pics: int
    first: float
    last: float


@dataclass(frozen=True)
class Counts:
    groups: int  # unnamed, worth naming
    strays: int  # unnamed, seen in fewer pictures
    named: int


RECOGNISED = 0.9  # the cloud's bar for a name (faces.ports.RECOGNITION_THRESHOLD)
NAME_MARGIN = 0.10  # how much more alike than the grouping threshold a face must be to be named


def confidence(cosine: float, match: float) -> float:
    """The laptop's likeness on the wire's 0..1 scale. The cloud's bar (0.9) is met only
    `NAME_MARGIN` above this laptop's grouping threshold (review C-sec L6): a face just alike
    enough to join a group is grouped, but not reported as the named person."""
    c = max(0.0, min(1.0, float(cosine)))
    bar = min(0.95, match + NAME_MARGIN)
    if c >= bar:
        return round(min(1.0, RECOGNISED + (1 - RECOGNISED) * (c - bar) / (1 - bar)), 4)
    return round(RECOGNISED * c / bar, 4)


def setting_int(text: object, default: int, low: int, high: int) -> int:
    value = str(text or "").strip()
    return int(value) if value.isdigit() and low <= int(value) <= high else default


def setting_float(text: object, default: float, low: float, high: float) -> float:
    try:
        value = float(str(text or ""))
    except ValueError:
        return default
    return value if low <= value <= high else default


def unit(vector: Sequence[float]) -> list[float]:
    if len(vector) != DIM or not all(isinstance(x, float) and math.isfinite(x) for x in vector):
        raise ValueError("a face embedding is 128 finite numbers")
    norm = math.sqrt(sum(x * x for x in vector))
    if norm <= 0:
        raise ValueError("a face embedding can't be all zeros")
    return [x / norm for x in vector]


def dot(a: Sequence[float], b: Sequence[float]) -> float:
    return sum(x * y for x, y in zip(a, b, strict=True))


__all__ = [
    "DIM",
    "GROUP",
    "JPEG",
    "MIN_GROUP_PICS",
    "PERSON",
    "AlreadyNamed",
    "Counts",
    "GroupRow",
    "Placed",
    "SeenFace",
    "UnknownGroup",
    "confidence",
    "dot",
    "setting_float",
    "setting_int",
    "unit",
]
