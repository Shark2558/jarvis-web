# src/jarvis/watch/models.py
"""What the phone's `health` door may hand the server (docs/plans/r7-mobile.md D17;
docs/plans/r7-integration/phone-contract.md section 4), and the day the server keeps.

    {"v":1,"days":[{"date","steps":{"count","writer"}|null,
      "heart":{"min","avg","max","writer"}|null,
      "sleep":[{"start","end","writer","stages":{"awake","light","deep","rem"}|null}]}]}

- Every number is a strict integer in its range: steps 0..200,000; heart rate 20..250 beats a
  minute with lowest <= average <= highest; a stage 0..1,440 minutes and the stages together no
  longer than the session. A session's `start` and `end` carry their own UTC offset (so a night
  across a time-zone change still sums right), end after start, at most a day long; at most 12 a
  day. A writer is an Android package name (or Health Connect's own `android`).
- At most 35 days, each once, each inside the last 35 days of his calendar (and tomorrow, for a
  phone in a zone ahead of his).
- Anything else refuses the WHOLE body with `IntakeRefused.WORDS`: fixed words that never echo a
  value (the phone's day builder is ours: a bad value is a bug to see, never data to guess).

`source_of(writer)` names the source the brief and the Watch tab say: a known watch app is "watch",
every other writer (the phone itself, Google Fit, any other app) is "phone" (D17, D18).
"""

from __future__ import annotations

import datetime as dt
import json
import re
from datetime import date, datetime, timedelta
from typing import Literal, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictInt,
    ValidationError,
    field_validator,
    model_validator,
)

Source = Literal["watch", "phone", "typed"]
MAX_DAYS = 35
MAX_STEPS = 200_000
HEART_LOW, HEART_HIGH = 20, 250
DAY_MINUTES = 24 * 60
MAX_SESSIONS = 12
WRITER_MAX = 128
_WRITER = re.compile(r"^[A-Za-z][A-Za-z0-9_]*(?:\.[A-Za-z0-9_]+)*$")
# The watch apps whose sessions and sums are the watch's own (D17: NoiseFit first; owner question 3)
WATCH_WRITERS: frozenset[str] = frozenset({"com.noisefit"})
TYPED_WRITER = "typed"  # a sleep time he typed (never a writer the phone sends: it is refused)


class IntakeRefused(ValueError):
    WORDS = "The phone's health summary was refused: it is not in the agreed form."

    def __init__(self) -> None:
        super().__init__(self.WORDS)


class _Frozen(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


def _writer(v: str) -> str:
    if len(v) > WRITER_MAX or not _WRITER.fullmatch(v) or v == TYPED_WRITER:
        raise ValueError("not a package name")
    return v


class Steps(_Frozen):
    count: StrictInt = Field(ge=0, le=MAX_STEPS)
    writer: str

    _w = field_validator("writer")(_writer)


class Heart(_Frozen):
    min: StrictInt = Field(ge=HEART_LOW, le=HEART_HIGH)
    avg: StrictInt = Field(ge=HEART_LOW, le=HEART_HIGH)
    max: StrictInt = Field(ge=HEART_LOW, le=HEART_HIGH)
    writer: str

    _w = field_validator("writer")(_writer)

    @model_validator(mode="after")
    def _ordered(self) -> Self:
        if not self.min <= self.avg <= self.max:
            raise ValueError("lowest, average and highest out of order")
        return self


class Stages(_Frozen):
    awake: StrictInt = Field(ge=0, le=DAY_MINUTES)
    light: StrictInt = Field(ge=0, le=DAY_MINUTES)
    deep: StrictInt = Field(ge=0, le=DAY_MINUTES)
    rem: StrictInt = Field(ge=0, le=DAY_MINUTES)

    @property
    def total(self) -> int:
        return self.awake + self.light + self.deep + self.rem


def _moment(v: str) -> datetime:
    if not isinstance(v, str) or len(v) > 40:
        raise ValueError("not a time")
    at = datetime.fromisoformat(v)
    if at.tzinfo is None or at.utcoffset() is None:
        raise ValueError("a time needs its offset")
    return at


class Session(_Frozen):
    """One sleep session as the phone's day builder kept it (one writer a night)."""

    start: str
    end: str
    writer: str
    stages: Stages | None = None

    @model_validator(mode="after")
    def _sane(self) -> Self:
        if self.writer != TYPED_WRITER:
            _writer(self.writer)
        start, end = _moment(self.start), _moment(self.end)
        span = (end - start).total_seconds() / 60
        if not 0 < span <= DAY_MINUTES:
            raise ValueError("a session ends after it starts, within a day")
        if self.stages is not None and self.stages.total > span + 1:
            raise ValueError("the stages are longer than the session")
        return self

    @property
    def started(self) -> datetime:
        return _moment(self.start)

    @property
    def ended(self) -> datetime:
        return _moment(self.end)

    @property
    def minutes(self) -> int:
        return round((self.ended - self.started).total_seconds() / 60)


class DayIn(_Frozen):
    date: dt.date
    steps: Steps | None = None
    heart: Heart | None = None
    sleep: tuple[Session, ...] = Field(default=(), max_length=MAX_SESSIONS)

    @field_validator("date", mode="before")
    @classmethod
    def _iso(cls, v: object) -> dt.date:
        if not isinstance(v, str) or len(v) != 10:
            raise ValueError("a date is YYYY-MM-DD")
        return dt.date.fromisoformat(v)

    @field_validator("sleep", mode="before")
    @classmethod
    def _list(cls, v: object) -> object:
        return tuple(v) if isinstance(v, list) else v


class HealthBody(_Frozen):
    v: StrictInt = Field(ge=1, le=1)  # a StrictInt: `true` is not 1
    days: tuple[DayIn, ...] = Field(min_length=1, max_length=MAX_DAYS)

    @field_validator("days", mode="before")
    @classmethod
    def _list(cls, v: object) -> object:
        return tuple(v) if isinstance(v, list) else v

    @model_validator(mode="after")
    def _once(self) -> Self:
        if len({d.date for d in self.days}) != len(self.days):
            raise ValueError("a day twice")
        return self


class StoredDay(_Frozen):
    """The day the server keeps, sealed (`watch_days/{uid}_{date}`): the phone's sums and
    sessions with their writers, and a night he typed (kept apart, so a sync never drops it)."""

    steps: Steps | None = None
    heart: Heart | None = None
    sleep: tuple[Session, ...] = ()
    typed: Session | None = None

    @field_validator("sleep", mode="before")
    @classmethod
    def _list(cls, v: object) -> object:
        return tuple(v) if isinstance(v, list) else v


def in_window(day: date, today: date) -> bool:
    """Inside the last 35 days of his calendar, or tomorrow (a phone in a zone ahead)."""
    return today - timedelta(days=MAX_DAYS - 1) <= day <= today + timedelta(days=1)


def parse_health(body: bytes, today: date) -> HealthBody:
    """The `health` door's body, checked whole; `IntakeRefused` (fixed words) otherwise."""
    try:
        raw = json.loads(body.decode("utf-8"))
        # every number is a StrictInt: a float, a bool or a "8000" is refused
        parsed = HealthBody.model_validate(raw) if isinstance(raw, dict) else None
    except (UnicodeDecodeError, ValueError, ValidationError, TypeError):
        raise IntakeRefused() from None
    if parsed is None or not all(in_window(d.date, today) for d in parsed.days):
        raise IntakeRefused()
    return parsed


def source_of(writer: str) -> Literal["watch", "phone"]:
    return "watch" if writer in WATCH_WRITERS else "phone"


__all__ = [
    "DAY_MINUTES",
    "HEART_HIGH",
    "HEART_LOW",
    "MAX_DAYS",
    "MAX_SESSIONS",
    "MAX_STEPS",
    "TYPED_WRITER",
    "WATCH_WRITERS",
    "DayIn",
    "HealthBody",
    "Heart",
    "IntakeRefused",
    "Session",
    "Source",
    "Stages",
    "Steps",
    "StoredDay",
    "in_window",
    "parse_health",
    "source_of",
]
