# src/jarvis/wardrobe/styling/plans.py
"""R13 Part C's records (D12, D13): his plans, his outfit rules and his choices, in ONE sealed
document `wardrobe_plans/{uid}` (`StylingDoc`, through `sealed.SealedDoc`).

- `Plan`: a day (his local day) and, from his calendar, an event's fingerprint and times (never a
  title); its dress code (tentative until he sets it, STY-03); the occasion the rules matched;
  indoor or outdoor (from the location, when he lets JARVIS read it); its picks (each slot's piece
  or pair, `locked` when he locked it, STY-12) which are its reservations (STY-14); a declared
  shared base from an earlier plan the same day (STY-13); the slots that need a new piece after
  a change (STY-15); manual or from the calendar; cancelled (a draft, D13); worn (a wear started
  for it: nothing it holds is a change for it any more, H1).
- `Prefs`: his "never" rules ("never tight at the neck", STY-08), pieces he excluded (for one
  occasion or all), colours he likes or avoids.
- `Choice`: the one calendar he picked (its id, sealed here), the fields JARVIS may read (start
  and end always; title on, location off by default), the evening alert on or off, auto-swap
  (off). No "alert lead": D19 fixes the evening alert at 20:00, so it was dropped before the
  first deploy (code review M8). Plan review note: the plan put these in A's index; Part C
  can't write A's index through the contract, so they live here (INTEGRATION-C, "Needs I1").
At most 60 plans, 14 days back to 30 ahead (older ones are dropped on the next change); at most
20 of them made by his calendar, and an event whose plan he removed is not made again
(`dismissed`, until its day is past): strangers' invites can't take his slots (security H1).
"""

from __future__ import annotations

import re
import secrets
from collections.abc import Mapping
from datetime import UTC, date, datetime, timedelta
from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field

from jarvis.wardrobe.model import COLOURS, PieceId

PLAN_ID = re.compile(r"^op_[0-9a-f]{8}$")
EVENT_KEY = re.compile(r"^[0-9a-f]{16}$")
MAX_PLANS, BACK_DAYS, AHEAD_DAYS = 60, 14, 30
MAX_CAL_PLANS = 20  # plans his calendar makes: the other 40 stay his (security review H1)
MAX_DISMISSED = 200
MAX_NEVER, MAX_EXCLUDED, MAX_COLOURS = 20, 50, 10
Field_ = Literal["title", "location"]


def _match(rx: re.Pattern[str]) -> AfterValidator:
    def check(v: str) -> str:
        if not rx.match(v):
            raise ValueError("not a valid id")
        return v

    return AfterValidator(check)


PlanId = Annotated[str, _match(PLAN_ID)]
EventKey = Annotated[str, _match(EVENT_KEY)]


def _colour(v: str) -> str:
    if v not in COLOURS:
        raise ValueError("not one of the fixed colours")
    return v


Colour = Annotated[str, AfterValidator(_colour)]


def new_plan_id() -> str:
    return f"op_{secrets.token_hex(4)}"


class _M(BaseModel):
    # Sealed records (code review M8, security review M2 and L6): a field a later release adds is
    # ignored, so a rollback still opens the document; a bad value never echoes into an error.
    model_config = ConfigDict(frozen=True, extra="ignore", hide_input_in_errors=True)


class PlanPick(_M):
    slot: str = Field(min_length=1, max_length=12)
    pieces: tuple[PieceId, ...] = Field(min_length=1, max_length=2)
    locked: bool = False


class Plan(_M):
    id: PlanId
    day: date
    event: EventKey | None = None
    starts: datetime | None = None
    ends: datetime | None = None
    code: str = Field(min_length=1, max_length=24)
    tentative: bool = True
    occasion: str | None = Field(default=None, max_length=24)
    outdoor: bool | None = None
    picks: tuple[PlanPick, ...] = Field(default=(), max_length=14)
    shared_from: PlanId | None = None
    shared: tuple[PieceId, ...] = Field(default=(), max_length=12)
    needs: tuple[str, ...] = Field(default=(), max_length=14)
    manual: bool = True
    cancelled: bool = False
    worn: bool = False
    updated: str | None = Field(default=None, max_length=40)  # the event's own `updated` stamp
    created_at: datetime | None = None
    updated_at: datetime | None = None

    def pieces(self) -> tuple[str, ...]:
        return tuple(i for p in self.picks for i in p.pieces)

    def pick_of(self, pid: str) -> PlanPick | None:
        return next((p for p in self.picks if pid in p.pieces), None)

    def slot(self, slot: str) -> PlanPick | None:
        return next((p for p in self.picks if p.slot == slot), None)

    @property
    def active(self) -> bool:
        return not self.cancelled and not self.worn


class Never(_M):
    feature: str = Field(min_length=1, max_length=12)
    value: str = Field(min_length=1, max_length=24)


class Exclusion(_M):
    piece: PieceId
    occasion: str | None = Field(default=None, max_length=24)  # None: every occasion


class Prefs(_M):
    never: tuple[Never, ...] = Field(default=(), max_length=MAX_NEVER)
    excluded: tuple[Exclusion, ...] = Field(default=(), max_length=MAX_EXCLUDED)
    likes: tuple[Colour, ...] = Field(default=(), max_length=MAX_COLOURS)
    avoids: tuple[Colour, ...] = Field(default=(), max_length=MAX_COLOURS)


class Choice(_M):
    calendar: str | None = Field(default=None, max_length=300)  # from HIS list only, sealed
    fields: tuple[Field_, ...] = ("title",)
    plan_alerts: bool = True
    auto_swap: bool = False


class Dismissed(_M):
    """A calendar event whose plan he removed: never made again (kept until its day is past)."""

    k: EventKey
    day: date


class StylingDoc(_M):
    plans: tuple[Plan, ...] = Field(default=(), max_length=MAX_PLANS)
    prefs: Prefs = Field(default_factory=Prefs)
    choice: Choice = Field(default_factory=Choice)
    cal_read_at: datetime | None = None
    cal_failed_at: datetime | None = None
    dismissed: tuple[Dismissed, ...] = Field(default=(), max_length=MAX_DISMISSED)

    def plan(self, pid: str) -> Plan | None:
        return next((p for p in self.plans if p.id == pid), None)

    def by_event(self, key: str) -> Plan | None:
        return next((p for p in self.plans if p.event == key), None)

    def on(self, day: date) -> tuple[Plan, ...]:
        found = (p for p in self.plans if p.day == day and not p.cancelled)
        return tuple(sorted(found, key=_order))

    def put(self, plan: Plan) -> StylingDoc:
        """This doc with `plan` added or replaced (a new one past the cap: `PlanRefused`)."""
        others = tuple(p for p in self.plans if p.id != plan.id)
        if len(others) >= MAX_PLANS:
            raise PlanRefused("You have 60 plans: remove an old one first.")
        return self.model_copy(update={"plans": tuple(sorted((*others, plan), key=_order))})

    def drop(self, pid: str) -> StylingDoc:
        return self.model_copy(update={"plans": tuple(p for p in self.plans if p.id != pid)})

    def dismiss(self, plan: Plan) -> StylingDoc:
        """This doc without `plan`; a calendar plan's event is remembered (security review H1)."""
        out = self.drop(plan.id)
        if plan.event is None:
            return out
        gone = (*self.dismissed, Dismissed(k=plan.event, day=plan.day))[-MAX_DISMISSED:]
        return out.model_copy(update={"dismissed": gone})

    def made(self) -> int:
        """How many plans his calendar made (a draft too: they take his slots until pruned)."""
        return sum(1 for p in self.plans if not p.manual)

    def pruned(self, today: date) -> StylingDoc:
        """Plans older than 14 days go; a cancelled calendar draft once its day is past; a
        dismissed event once its day is past (security review H1)."""
        keep = tuple(
            p for p in self.plans
            if p.day >= today - timedelta(days=BACK_DAYS)
            and not (not p.manual and p.cancelled and p.day < today)
        )  # fmt: skip
        gone = tuple(d for d in self.dismissed if d.day >= today)
        return self.model_copy(update={"plans": keep, "dismissed": gone})


class PlanRefused(ValueError):  # noqa: N818 - a refusal in plain words
    """A plan change refused in plain words; nothing is written."""


_EARLIEST = datetime.min.replace(tzinfo=UTC)


def _order(p: Plan) -> tuple[date, bool, datetime, str]:
    """By day, the untimed plan of a day first, then by start, then by id."""
    return (p.day, p.starts is not None, p.starts or _EARLIEST, p.id)


CHANGED = "That plan changed meanwhile: try again."


def cas(current: StylingDoc, ours: StylingDoc, seen: Mapping[str, Plan | None]) -> StylingDoc:
    """Our version of each plan in `seen` onto `current`, only where `current` still holds the
    plan as we read it (frozen records compare by value; security review M1)."""
    for pid, before in seen.items():
        mine = ours.plan(pid)
        if mine is not None and current.plan(pid) == before:
            current = current.put(mine)
    return current


def strict(current: StylingDoc, ours: StylingDoc, seen: Mapping[str, Plan | None]) -> StylingDoc:
    """As `cas`, but a plan changed meanwhile refuses the whole change in plain words."""
    if any(current.plan(pid) != before for pid, before in seen.items()):
        raise PlanRefused(CHANGED)
    return cas(current, ours, seen)


def in_range(day: date, today: date) -> bool:
    return today - timedelta(days=BACK_DAYS) <= day <= today + timedelta(days=AHEAD_DAYS)


__all__ = [
    "AHEAD_DAYS",
    "CHANGED",
    "BACK_DAYS",
    "MAX_CAL_PLANS",
    "MAX_PLANS",
    "PLAN_ID",
    "Choice",
    "Dismissed",
    "Exclusion",
    "Never",
    "Plan",
    "PlanId",
    "PlanPick",
    "PlanRefused",
    "Prefs",
    "StylingDoc",
    "cas",
    "in_range",
    "new_plan_id",
    "strict",
]
