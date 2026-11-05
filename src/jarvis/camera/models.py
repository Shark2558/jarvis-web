# src/jarvis/camera/models.py
"""Camera settings, the arm record, feed lines and history shapes (R3 D1, D7, D8, D15, D16).

Everything the owner types (camera labels) is cleaned to one short line. Everything the bridge
sends is already restricted by `jarvis.home.ports` (ids `[a-z0-9_]{1,24}`, a fixed label list,
`fp_` person ids); words shown to the owner or the model are rebuilt from these tables, never
passed through from Frigate.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, StrictStr

from jarvis.home.ports import (
    LABELS,
    MAX_CAMERAS,
    MAX_ZONES,
    CameraId,
    PersonId,
    ZoneId,
)
from jarvis.tools.card import one_line

LABEL_MAX = 30
WHAT_VALUES = (*LABELS, "package", "any")
MAX_SPAN_DAYS = 31
MAX_LIMIT = 20
DEFAULT_RETENTION_DAYS = 7
MAX_FEED_PER_DAY = 300
FEED_KEEP_DAYS = 7
ARM_FAIL_AFTER_S = 300.0  # D8: no ack in 5 minutes -> home_arm_failed

SetVia = Literal["console", "chat", "voice", "telegram"]
Mode = Literal["away", "night"]
FeedKind = Literal["intruder", "greeting", "package", "other"]
FeedDecision = Literal["ring", "silent", "held", "dropped"]
ObjectLabel = Literal["person", "car", "motorcycle", "bicycle", "dog", "cat"]


class Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


def clean_label(raw: object, fallback: str = "") -> str:
    """The owner's own label for a camera: one short line (the fallback when it is empty)."""
    text = one_line(raw, LABEL_MAX)
    return text or fallback


def first_upper(text: str) -> str:
    """Capitalise the first letter only (`str.capitalize` would lower the rest)."""
    return text[:1].upper() + text[1:]


def spaced(ident: str) -> str:
    """A camera or zone id in words: `side_gate` -> `side gate` (the id is regex-restricted)."""
    return ident.replace("_", " ")


class CameraConfig(Frozen):
    label: Annotated[StrictStr, Field(min_length=1, max_length=LABEL_MAX)]
    alarm_zones: tuple[ZoneId, ...] = Field(default=(), max_length=MAX_ZONES)
    package_zone: ZoneId | None = None


class PackageMemo(Frozen):
    """The doorstep as last reported (D16), for one camera and zone."""

    state: Literal["package", "empty"]
    changed_at: float
    alerted_at: float | None = None


class CameraStatus(Frozen):
    """What the bridge last told us (heartbeats) and what we last saw; not owner settings."""

    doorstep_model: StrictBool | None = None
    online: dict[CameraId, StrictBool] = Field(default_factory=dict, max_length=MAX_CAMERAS)
    last_event: dict[CameraId, float] = Field(default_factory=dict, max_length=MAX_CAMERAS)
    # "<camera>:<zone>" -> the doorstep memo
    packages: dict[str, PackageMemo] = Field(default_factory=dict, max_length=MAX_CAMERAS * 2)


class CameraSettings(Frozen):
    cameras: dict[CameraId, CameraConfig] = Field(default_factory=dict, max_length=MAX_CAMERAS)
    retention_days: Annotated[StrictInt, Field(ge=1, le=30)] = DEFAULT_RETENTION_DAYS
    greetings: StrictBool = True  # feed lines for consented people while disarmed
    rev: Annotated[StrictInt, Field(ge=0)] = 0
    status: CameraStatus = CameraStatus()

    @property
    def packages_on(self) -> bool:
        return any(c.package_zone for c in self.cameras.values())


class ArmRecord(BaseModel):
    """`home_arm/{uid}` (plain: no personal data). Confirmed = the bridge acked `rev`."""

    model_config = ConfigDict(extra="ignore")

    armed: bool = False
    mode: Mode = "away"
    rev: int = Field(default=0, ge=0)
    set_at: float = 0.0
    set_via: SetVia = "console"
    acked_rev: int = Field(default=0, ge=0)
    pending_since: float | None = None
    failed_rev: int = -1  # the rev whose "couldn't arm" alert was already sent
    dropped_disarmed: int = Field(default=0, ge=0)

    @property
    def confirmed(self) -> bool:
        return self.acked_rev >= self.rev


class FeedItem(Frozen):
    """One line of the home feed. Person ids only: names are resolved when it is viewed."""

    at: float
    kind: FeedKind
    camera: CameraId
    zone: ZoneId | None = None
    label: ObjectLabel | None = None
    person: PersonId | None = None
    score: float | None = Field(default=None, ge=0, le=1)
    decision: FeedDecision = "silent"
    telegram: StrictBool = False
    push: Annotated[StrictInt, Field(ge=0, le=5)] = 0
    photo_sent: StrictBool = False
    delivered: StrictBool = False


class HistoryQuery(BaseModel):
    """What the owner (or the model on his behalf) asked camera history for (D15)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    what: str = "any"
    start: datetime
    end: datetime
    camera: str | None = None
    zone: str | None = None
    who: str | None = None
    limit: int = MAX_LIMIT


class HistoryItem(Frozen):
    at: str
    camera: str
    zone: str | None
    what: str
    who: str | None
    seconds: int | None = None


class HistoryResult(Frozen):
    count: int
    items: tuple[HistoryItem, ...]
    more: bool
    kept_days: int
    note: str = ""


__all__ = [
    "ARM_FAIL_AFTER_S",
    "DEFAULT_RETENTION_DAYS",
    "FEED_KEEP_DAYS",
    "LABEL_MAX",
    "MAX_FEED_PER_DAY",
    "MAX_LIMIT",
    "MAX_SPAN_DAYS",
    "WHAT_VALUES",
    "ArmRecord",
    "CameraConfig",
    "CameraSettings",
    "CameraStatus",
    "FeedDecision",
    "FeedItem",
    "FeedKind",
    "Frozen",
    "HistoryItem",
    "HistoryQuery",
    "HistoryResult",
    "Mode",
    "ObjectLabel",
    "PackageMemo",
    "SetVia",
    "clean_label",
    "first_upper",
    "spaced",
]
