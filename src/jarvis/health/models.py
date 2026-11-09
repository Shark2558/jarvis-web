# src/jarvis/health/models.py
"""Self-health data (R4 D5/D6). Plain frozen values; no model, no I/O."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Status = Literal["ok", "degraded", "down"]
REASON_MAX = 120
KEY_MAX = 40
LABEL_MAX = 60

# How each integration is spoken. Code-side: the spoken line never uses a label read back from
# storage for a key listed here (R4 review py-L1).
LABELS: Mapping[str, str] = {
    "brain": "the AI brain",
    "google": "Google",
    "telegram": "Telegram",
    "home": "the home bridge",
    "docs": "the document store",
    "redis": "Redis",
    "web": "web search",
}


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
    persisted: bool = True  # False: the result could not be saved (the store was down)

    @property
    def faulty_keys(self) -> frozenset[str]:
        return frozenset(r.key for r in self.results if r.status != "ok")


@dataclass(frozen=True)
class HealthState:
    """The stored document: the last report plus what the owner was last TOLD per integration
    (`alerted`) and how many counted checks in a row each status has held and when (`streaks`:
    status, count, first_at, last_counted_at; R5.1 D14)."""

    report: HealthReport
    alerted: Mapping[str, Status]
    streaks: Mapping[str, tuple[Status, int, float | None, float | None]]


__all__ = ["LABELS", "HealthReport", "HealthState", "ProbeOutcome", "ProbeResult", "Status"]
