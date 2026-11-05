# src/jarvis/vitals/models.py
"""The provider record and its computed views (R4 D2). Immutable; status is computed, never stored
stale (`jarvis.vitals.status`)."""

from __future__ import annotations

import math
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

Kind = Literal["key", "quota", "billing", "storage", "allowance"]
Source = Literal["auto", "manual"]
Status = Literal["ok", "amber", "red", "unknown"]

ID_PATTERN = r"^[a-z0-9][a-z0-9_-]{0,39}$"
LABEL_MAX = 80
NOTE_MAX = 300
UNIT_MAX = 20
LIMIT_MAX = 1e12
MAX_MANUAL = 50  # manual records per owner
RANK: dict[str, int] = {"ok": 0, "amber": 1, "red": 2}


def _iso(d: datetime | None) -> str | None:
    return d.isoformat() if d else None


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


class ProviderView(BaseModel):
    """A provider with its computed status, as the board and the tools show it."""

    model_config = ConfigDict(frozen=True)

    provider: Provider
    status: Status
    percent: float | None = None  # of the limit; can pass 100
    reason: str = ""  # one fixed-template line: why this status

    def to_json(self) -> dict[str, Any]:
        return {
            **self.provider.fields(),
            "status": self.status,
            "percent": self.percent,
            "reason": self.reason,
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

    def attention(self) -> tuple[ProviderView, ...]:
        """Amber and red items, red first."""
        hot = [v for v in self.items if v.status in ("amber", "red")]
        return tuple(sorted(hot, key=lambda v: (-RANK[v.status], v.provider.label)))

    def to_json(self) -> dict[str, Any]:
        return {
            "overall": self.overall,
            "items": [v.to_json() for v in self.items],
            "spend": self.spend.model_dump() if self.spend else None,
        }


__all__ = [
    "ID_PATTERN",
    "MAX_MANUAL",
    "RANK",
    "Board",
    "Kind",
    "Provider",
    "ProviderView",
    "Source",
    "Spend",
    "Status",
]
