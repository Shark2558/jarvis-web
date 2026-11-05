# src/jarvis/photos/models.py
"""Plain frozen data for the Google Photos -> faces flow (R4 D8). No picture and no embedding is
ever a field here: pictures pass through memory on their way to the home edge and are dropped."""

from __future__ import annotations

import re
from dataclasses import dataclass

PHOTOS_SCOPE = "https://www.googleapis.com/auth/photospicker.mediaitems.readonly"
CLUSTER_ID = re.compile(r"c_[0-9a-f]{8,16}")
SESSION_ID = re.compile(r"[A-Za-z0-9_-]{1,200}")


@dataclass(frozen=True)
class PickerSession:
    id: str
    picker_uri: str
    ready: bool  # the owner has finished picking
    expires_at: str


@dataclass(frozen=True)
class PickedItem:
    """One photo the owner chose. `base_url` lives in memory for one import and is never stored."""

    id: str
    mime_type: str
    base_url: str


@dataclass(frozen=True)
class FaceHit:
    """A face the home edge found: `person` (an fp_ id) when it matches an enrolled face, else an
    unnamed `cluster` id the edge made up (never a name)."""

    cluster: str
    person: str | None
    score: float


@dataclass(frozen=True)
class RecognisedPerson:
    person_id: str
    name: str
    child: bool


@dataclass(frozen=True)
class ImportResult:
    status: str  # done | waiting | no_session | laptop_offline
    photos: int = 0
    faces_found: int = 0
    recognised: tuple[RecognisedPerson, ...] = ()
    unknown_clusters: tuple[str, ...] = ()
    skipped: int = 0


__all__ = [
    "CLUSTER_ID",
    "PHOTOS_SCOPE",
    "SESSION_ID",
    "FaceHit",
    "ImportResult",
    "PickedItem",
    "PickerSession",
    "RecognisedPerson",
]
