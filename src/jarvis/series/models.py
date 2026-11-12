# src/jarvis/series/models.py
"""A followed series of calendar sessions (R11.1 O2b; docs/plans/r11-1-observations.md D6;
Layer 7 records).

`Book` is the owner's one document, `{prefix}series/{uid}`: at most `MAX_PLANS` plans of at most
`MAX_SESSIONS` sessions each. A session keeps its calendar event id, a short title (the owner's
calendar already holds it), its times and its state:

    planned   in the calendar, not yet answered
    done      he said it happened
    skipped   he said it did not (a re-plan may be waiting for his approval; every skipped
              session that has no new date yet moves with the next re-plan)
    moved     re-planned to a new time; asked about again after that time
    removed   he deleted its event in Google Calendar: never asked about, never moved

A session also keeps its batch and its number in that batch (`item`), so a list sent again after
he deleted one event by hand fills the same row with the new event (never a second row).

`outside`: the plan was made from other people's words (a file, a mail). Its name and titles then
never appear in an alert or in JARVIS's own sentences ("your plan").
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

State = Literal["planned", "done", "skipped", "moved", "removed"]
OPEN_STATES: frozenset[str] = frozenset({"planned", "moved"})  # still to happen, or to answer
MAX_PLANS = 10
MAX_SESSIONS = 200
TITLE_MAX = 80
NAME_MAX = 60


class ReplanRefused(ValueError):
    """A re-plan that can't be made or would lose a session; the message is plain words."""


def plan_id(name: str) -> str:
    """One plan per name (case and spacing aside): a second batch with the name extends it."""
    key = " ".join(name.split()).casefold()
    return "p" + hashlib.sha256(key.encode()).hexdigest()[:12]


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")


class PlanSession(_Frozen):
    n: int = Field(ge=1, le=999)
    event_id: str = Field(min_length=1, max_length=1024)
    title: str = Field(default="", max_length=TITLE_MAX)
    start: datetime
    end: datetime
    state: State = "planned"
    batch: str = ""
    item: int = Field(default=0, ge=0, le=999)  # its number in `batch` (0: not known)
    answered_at: datetime | None = None


class Plan(_Frozen):
    id: str
    name: str = Field(max_length=NAME_MAX)
    prefix: str = ""
    outside: bool = False
    sessions: list[PlanSession] = Field(default_factory=list, max_length=MAX_SESSIONS)
    created_at: datetime
    updated_at: datetime

    def session(self, n: int) -> PlanSession | None:
        return next((s for s in self.sessions if s.n == n), None)

    @property
    def total(self) -> int:
        return len(self.sessions)

    @property
    def words(self) -> str:
        """How JARVIS names the plan in its own sentences: never outside words."""
        return "your plan" if self.outside or not self.name else f"your {self.name} plan"


class Book(_Frozen):
    plans: list[Plan] = Field(default_factory=list, max_length=MAX_PLANS)

    def plan(self, key: str) -> Plan | None:
        """By id, else by name (as `plan_id` reads names)."""
        wanted = plan_id(key)
        return next((p for p in self.plans if key == p.id or p.id == wanted), None)

    def replaced(self, plan: Plan) -> Book:
        others = [p for p in self.plans if p.id != plan.id]
        return Book(plans=[*others, plan] if plan.sessions else others)


@dataclass(frozen=True)
class Move:
    """One session's new time in a re-plan (`was`: its start before)."""

    n: int
    was: datetime
    start: datetime
    end: datetime


__all__ = [
    "MAX_PLANS",
    "MAX_SESSIONS",
    "NAME_MAX",
    "OPEN_STATES",
    "TITLE_MAX",
    "Book",
    "Move",
    "Plan",
    "PlanSession",
    "ReplanRefused",
    "State",
    "plan_id",
]
