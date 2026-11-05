# src/jarvis/health/models.py
"""Self-health data (R4 D5/D6). Plain frozen values; no model, no I/O."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Status = Literal["ok", "degraded", "down"]
REASON_MAX = 120
KEY_MAX = 40
LABEL_MAX = 60


@dataclass(frozen=True)
class ProbeOutcome:
    """What a probe's check answers: a status and a one-line reason written by JARVIS code."""

    status: Status
    reason: str


class _Frozen(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ProbeResult(_Frozen):
    key: str = Field(min_length=1, max_length=KEY_MAX)
    label: str = Field(min_length=1, max_length=LABEL_MAX)  # how it is spoken: "the home bridge"
    status: Status
    reason: str = Field(max_length=REASON_MAX)
    at: float


class HealthReport(_Frozen):
    overall: Status
    results: tuple[ProbeResult, ...]
    at: float

    @property
    def faulty_keys(self) -> frozenset[str]:
        return frozenset(r.key for r in self.results if r.status != "ok")


__all__ = ["HealthReport", "ProbeOutcome", "ProbeResult", "Status"]
