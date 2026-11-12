# src/jarvis/photos/models.py
"""Plain frozen data for the Google Photos -> faces flow (R4 D8). No picture and no embedding is
ever a field here: pictures pass through memory on their way to the home edge and are dropped."""

from __future__ import annotations

import re
from dataclasses import dataclass

PHOTOS_SCOPE = "https://www.googleapis.com/auth/photospicker.mediaitems.readonly"
# Review C-sec H3: anchored, so a pydantic `pattern` (a search) can only take a WHOLE id, and
# bounded (`CLUSTER_ID_MAX`); every Python use is `fullmatch` as well.
CLUSTER_ID = re.compile(r"^c_[0-9a-f]{8,16}$")
CLUSTER_ID_MAX = len("c_") + 16
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
    """One step of an import, or where it stands (R11.1 O6: an import is a background job).

    status: done | reading (more to do) | waiting (still picking) | no_session | expired (the
    Google session ended part-way: pick again) | laptop_offline | kit_old | reader_off |
    edge_error | timed_out. `photos`, `faces_found`, `skipped` and `recognised` cover the whole
    import so far; `unknown_clusters` are the unnamed ids seen in this step."""

    status: str
    photos: int = 0
    faces_found: int = 0
    recognised: tuple[RecognisedPerson, ...] = ()
    unknown_clusters: tuple[str, ...] = ()
    skipped: int = 0
    picker_uri: str = ""  # on `waiting`: the link again, in case the first was lost
    total: int = 0  # photos picked (0 until Google's list has been read)
    unknown: int = 0  # faces not recognised so far (they may form groups on the laptop)
    over: int = 0  # picked beyond the owner's limit, not imported
    line: str = ""  # the progress in plain words, for the panel and the chat


@dataclass(frozen=True)
class ImportLimits:
    """`photos_max_picked` and `photos_import_batch` (config.py), as the import uses them."""

    max_picked: int = 2000
    batch: int = 10


@dataclass(frozen=True)
class GroupAtHome:
    """An unnamed group of faces on the laptop: its id, short number and counts. Never a face."""

    id: str
    n: int
    photos: int
    first: int
    last: int


@dataclass(frozen=True)
class GroupsAtHome:
    groups: tuple[GroupAtHome, ...] = ()
    more: int = 0
    strays: int = 0
    named: int = 0
    engine_ready: bool = False
    folder: str = "off"  # off | on | unreadable
    read: int = 0
    keep_days: int = 90
    skipped: int = 0  # files of the watched folder that could not be read (a count)
    store_ok: bool = True  # False: the laptop's face store can't be opened right now


@dataclass(frozen=True)
class Forgot:
    forgotten: int
    left: int  # unnamed groups and stray faces still on the laptop


__all__ = [
    "CLUSTER_ID",
    "CLUSTER_ID_MAX",
    "PHOTOS_SCOPE",
    "SESSION_ID",
    "FaceHit",
    "Forgot",
    "GroupAtHome",
    "GroupsAtHome",
    "ImportLimits",
    "ImportResult",
    "PickedItem",
    "PickerSession",
    "RecognisedPerson",
]
