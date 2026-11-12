# src/jarvis/vitals/models.py
"""The provider record and its computed views (R4 D2). Immutable; status is computed, never stored
stale (`jarvis.vitals.status`)."""

from __future__ import annotations

import math
from datetime import datetime, time, tzinfo
from typing import Any, Literal
from zoneinfo import ZoneInfo

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)

from jarvis.vitals.guard import NEVER_PASTE, label_problem, looks_like_a_key

Kind = Literal["key", "quota", "billing", "storage", "allowance"]
Source = Literal["auto", "manual"]
Status = Literal["ok", "amber", "red", "unknown"]
Group = Literal["keys", "allowances", "bills"]  # R5.1: the panel's sections

ID_PATTERN = r"^[a-z0-9][a-z0-9_-]{0,39}$"
LABEL_MAX = 80
NOTE_MAX = 300
UNIT_MAX = 20
LIMIT_MAX = 1e12
MAX_MANUAL = 50  # manual records per owner
RANK: dict[str, int] = {"ok": 0, "amber": 1, "red": 2}
KIND_GROUP: dict[str, Group] = {
    "key": "keys",
    "quota": "allowances",
    "allowance": "allowances",
    "billing": "bills",
    "storage": "bills",
}


DEFAULT_TZ = "Asia/Kolkata"
END_OF_DAY = time(23, 59, 59)
INVALID = "Those values aren't valid"


def _iso(d: datetime | None) -> str | None:
    return d.isoformat() if d else None


def zone_of(name: str) -> ZoneInfo:
    """The zone named by the service's injected `Settings.user_timezone`; the default if the name
    can't be read (a bad zone name must not brick the board). No global settings read (I2 F6)."""
    try:
        return ZoneInfo(name)
    except Exception:  # noqa: BLE001 - a bad zone name must not brick the board
        return ZoneInfo(DEFAULT_TZ)


def aware(d: datetime, tz: tzinfo) -> datetime:
    """A naive value (or a date-only one) means the END of that day in `tz` (the owner's zone,
    passed in), never UTC midnight; an aware value is kept."""
    if d.tzinfo is not None:
        return d
    return datetime.combine(d.date(), END_OF_DAY, tzinfo=tz)


def describe_error(exc: ValidationError) -> str:
    """Plain words naming only OUR field names: never the input, never a caller's key name."""
    errors = exc.errors()
    if any(NEVER_PASTE in str(e.get("msg", "")) for e in errors):
        return NEVER_PASTE
    known = set(Provider.model_fields)
    names = sorted({str(e["loc"][0]) for e in errors if e["loc"] and e["loc"][0] in known})
    other = [str(e.get("msg", "")) for e in errors if not e["loc"]]
    shown = ", ".join(names) or (other[0].removeprefix("Value error, ") if other else "")
    return f"{INVALID} ({shown or 'unknown field'})."


class Provider(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str = Field(pattern=ID_PATTERN)
    label: str = Field(min_length=1, max_length=LABEL_MAX)
    kind: Kind
    source: Source = "manual"
    limit: float | None = Field(default=None, ge=0, le=LIMIT_MAX)
    used: float | None = Field(default=None, ge=0, le=LIMIT_MAX)
    unit: str = Field(default="", max_length=UNIT_MAX)
    reset_at: datetime | None = None
    expires_at: datetime | None = None
    note: str = Field(default="", max_length=NOTE_MAX)

    @field_validator("limit", "used")
    @classmethod
    def _finite(cls, v: float | None) -> float | None:
        if v is not None and not math.isfinite(v):
            raise ValueError("must be a finite number")
        return v

    @field_validator("label", "unit", "note", mode="before")
    @classmethod
    def _tidy(cls, v: Any) -> Any:
        return " ".join(v.split()) if isinstance(v, str) else v

    @field_validator("reset_at", "expires_at")
    @classmethod
    def _end_of_day(cls, v: datetime | None) -> datetime | None:
        """Naive / date-only means the end of that day; the zone is applied at use (`aware`),
        from the service's own settings, so nothing here reads global settings."""
        if v is None or v.tzinfo is not None:
            return v
        return datetime.combine(v.date(), END_OF_DAY)

    @model_validator(mode="after")
    def _guard(self) -> Provider:
        """Manual records only (auto ones are built from code): no key value anywhere, and a
        constrained label. The one guard for every entry path (tool, REST, importer)."""
        if self.source != "manual":
            return self
        if looks_like_a_key([self.label, self.note, self.unit], ident=self.id):
            raise ValueError(NEVER_PASTE)
        problem = label_problem(self.label)
        if problem:
            raise ValueError(problem)
        return self

    def fields(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "label": self.label,
            "kind": self.kind,
            "source": self.source,
            "limit": self.limit,
            "used": self.used,
            "unit": self.unit,
            "reset_at": _iso(self.reset_at),
            "expires_at": _iso(self.expires_at),
            "note": self.note,
        }


def group_of(kind: str) -> Group:
    """The panel section a record sits in by its kind (manual records; auto ones say their own)."""
    return KIND_GROUP.get(kind, "keys")


class ProviderView(BaseModel):
    """A provider with its computed status, as the board and the tools show it.

    `impact` ("If this stops: ...") and `fix` (what to do) are FIXED words from
    `jarvis.vitals.words` (empty for the owner's own records); the systems-check briefing reads
    them with getattr. `group` is the panel section. `checking` (R11.1 D19): JARVIS is reading
    this item's facts right now, so the panel says "Checking..." instead of "Unknown"."""

    model_config = ConfigDict(frozen=True)

    provider: Provider
    status: Status
    percent: float | None = None  # of the limit; can pass 100
    reason: str = ""  # one fixed-template line: why this status
    impact: str = ""
    fix: str = ""
    group: Group = "keys"
    checking: bool = False

    def to_json(self) -> dict[str, Any]:
        return {
            **self.provider.fields(),
            "status": self.status,
            "percent": self.percent,
            "reason": self.reason,
            "impact": self.impact,
            "fix": self.fix,
            "group": self.group,
            "checking": self.checking,
        }


class Spend(BaseModel):
    """This month's AI spend against the owner's limit (rupees)."""

    model_config = ConfigDict(frozen=True)

    used_inr: float
    limit_inr: int | None
    text: str  # "₹120 of ₹500 this month"


class Board(BaseModel):
    model_config = ConfigDict(frozen=True)

    items: tuple[ProviderView, ...]
    spend: Spend | None
    overall: Status
    manual_unavailable: bool = False  # the owner's own records can't be read; the rest still show
    manual_note: str = ""  # a fixed plain line when they can't

    def attention(self) -> tuple[ProviderView, ...]:
        """Amber and red items, red first."""
        hot = [v for v in self.items if v.status in ("amber", "red")]
        return tuple(sorted(hot, key=lambda v: (-RANK[v.status], v.provider.label)))

    def to_json(self) -> dict[str, Any]:
        return {
            "overall": self.overall,
            "items": [v.to_json() for v in self.items],
            "spend": self.spend.model_dump(mode="json") if self.spend else None,
            "manual_unavailable": self.manual_unavailable,
            "manual_note": self.manual_note,
        }


__all__ = [
    "ID_PATTERN",
    "MAX_MANUAL",
    "NEVER_PASTE",
    "RANK",
    "Board",
    "Group",
    "aware",
    "describe_error",
    "group_of",
    "zone_of",
    "Kind",
    "Provider",
    "ProviderView",
    "Source",
    "Spend",
    "Status",
]
