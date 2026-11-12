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
GROUP = re.compile(r"c_[0-9a-f]{12}")
PERSON = re.compile(r"fp_[0-9a-f]{12}")
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
    "dot",
    "unit",
]
