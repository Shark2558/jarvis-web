# src/jarvis/helpers/nudges/models.py
"""Part C's settings (docs/plans/r11-free-helpers.md data model `nudges/{uid}`, D6, owner
decision 9).

One `Nudge` per kind: on (OFF until he switches it on), a window (`start`-`end`, local, end not
included), the days (0 = Monday), every N minutes (stand-up, water) or his times (focus, free time),
the stand-up meeting variant (owner decision 1: off, with the word his meeting's title contains) and
the words his planned activities carry (item 11). `Idea`: one line of his free-time list (item 12).
Everything here is his own words or JARVIS's; nothing is read from outside. Frozen models: a change
returns new settings.
"""

from __future__ import annotations

import re
import secrets
from collections.abc import Mapping
from datetime import time
from types import MappingProxyType
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from jarvis.helpers.kinds import NUDGE_KINDS, NudgeKind

ALL = "*"
Place = Literal["indoor", "outdoor", "any"]
MAX_IDEAS = 50
MAX_TIMES = 6
MAX_WORDS = 10
MAX_IDEA_TEXT = 80
IDEA_MINUTES = (5, 480)
EVERY_MINUTES = (15, 240)
WEEK: tuple[int, ...] = (0, 1, 2, 3, 4, 5, 6)
WORKWEEK: tuple[int, ...] = (0, 1, 2, 3, 4, 5)  # Monday to Saturday (owner decision 9)
_HHMM = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")
_WORD = re.compile(r"^[a-z][a-z \-]{1,29}$")

EVERY_KINDS: frozenset[str] = frozenset({"nudge_standup", "nudge_hydrate"})
TIMES_KINDS: frozenset[str] = frozenset({"nudge_focus", "nudge_free_time"})
NAME: Mapping[str, str] = MappingProxyType(
    {
        "nudge_standup": "standup",
        "nudge_hydrate": "water",
        "nudge_activity": "activity",
        "nudge_free_time": "free_time",
        "nudge_focus": "focus",
    }
)
LABEL: Mapping[str, str] = MappingProxyType(
    {
        "nudge_standup": "Stand up and move",
        "nudge_hydrate": "Drink water",
        "nudge_activity": "A planned activity that didn't happen",
        "nudge_free_time": "Ideas for free time",
        "nudge_focus": "Your top priority",
    }
)
_SAID: Mapping[str, str] = MappingProxyType(
    {
        "standup": "nudge_standup",
        "stand up": "nudge_standup",
        "standing": "nudge_standup",
        "stand up and move": "nudge_standup",
        "move": "nudge_standup",
        "water": "nudge_hydrate",
        "hydrate": "nudge_hydrate",
        "hydration": "nudge_hydrate",
        "drink water": "nudge_hydrate",
        "drinking water": "nudge_hydrate",
        "drinking": "nudge_hydrate",
        "activity": "nudge_activity",
        "activities": "nudge_activity",
        "planned activity": "nudge_activity",
        "walk check": "nudge_activity",
        "free time": "nudge_free_time",
        "free time ideas": "nudge_free_time",
        "freetime": "nudge_free_time",
        "focus": "nudge_focus",
        "top priority": "nudge_focus",
        "priority": "nudge_focus",
        "all": ALL,
        "every": ALL,
        "everything": ALL,
        "nudge": ALL,
        "nudges": ALL,
        "all nudges": ALL,
    }
)
KINDS_HELP = "stand-up, water, activity, free time, focus or all"


def kind_of(said: str) -> str:
    """A nudge kind (or `ALL`) from what he called it ("stand-up", "water", "free time", ...)."""
    if said in NUDGE_KINDS or said == ALL:
        return said
    key = " ".join(re.sub(r"[-_]", " ", str(said).lower()).split())
    key = key.removesuffix(" nudges").removesuffix(" nudge").removesuffix(" reminders")
    key = key.removesuffix(" reminder").strip()
    found = _SAID.get(key) or _SAID.get(key.replace(" ", ""))
    if found is None:
        raise ValueError(f"Which nudge, Sir? Say {KINDS_HELP}.")
    return found


def clock(value: str) -> time:
    m = _HHMM.match(value)
    if m is None:
        raise ValueError("a time is HH:MM, 24-hour (such as 09:30)")
    return time(int(m[1]), int(m[2]))


class Nudge(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    on: bool = False
    start: str = "09:30"
    end: str = "18:30"
    days: tuple[int, ...] = WORKWEEK
    every: int = Field(default=0, ge=0)
    times: tuple[str, ...] = ()
    meeting: bool = False
    word: str = "stand-up"
    words: tuple[str, ...] = ()

    @field_validator("start", "end")
    @classmethod
    def _hhmm(cls, v: str) -> str:
        clock(v)
        return v

    @field_validator("days")
    @classmethod
    def _days(cls, v: tuple[int, ...]) -> tuple[int, ...]:
        if not v or any(d not in WEEK for d in v):
            raise ValueError("days are 0 (Monday) to 6 (Sunday), at least one")
        return tuple(sorted(set(v)))

    @field_validator("every")
    @classmethod
    def _every(cls, v: int) -> int:
        lo, hi = EVERY_MINUTES
        if v and not lo <= v <= hi:
            raise ValueError(f"every {lo} to {hi} minutes")
        return v

    @field_validator("times")
    @classmethod
    def _times(cls, v: tuple[str, ...]) -> tuple[str, ...]:
        if len(v) > MAX_TIMES:
            raise ValueError(f"at most {MAX_TIMES} times a day")
        for t in v:
            clock(t)
        return tuple(sorted(set(v)))

    @field_validator("word")
    @classmethod
    def _word(cls, v: str) -> str:
        return _one_word(v)

    @field_validator("words")
    @classmethod
    def _words(cls, v: tuple[str, ...]) -> tuple[str, ...]:
        if len(v) > MAX_WORDS:
            raise ValueError(f"at most {MAX_WORDS} activity words")
        return tuple(dict.fromkeys(_one_word(w) for w in v))

    @model_validator(mode="after")
    def _window(self) -> Nudge:
        if clock(self.start) >= clock(self.end):
            raise ValueError("the window must start before it ends")
        return self


def _one_word(v: str) -> str:
    w = " ".join(str(v).lower().split())
    if not _WORD.match(w):
        raise ValueError("a word is 2 to 30 letters (spaces and hyphens allowed)")
    return w


DEFAULTS: Mapping[str, Nudge] = MappingProxyType(
    {
        "nudge_standup": Nudge(every=60),
        "nudge_hydrate": Nudge(every=90),
        "nudge_activity": Nudge(
            start="06:00", end="22:00", days=WEEK, words=("walk", "gym", "yoga", "run")
        ),
        "nudge_free_time": Nudge(start="09:00", end="21:00", days=WEEK, times=("18:00",)),
        "nudge_focus": Nudge(times=("10:00", "15:00")),
    }
)


class Idea(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(pattern=r"^[0-9a-f]{8}$")
    text: str = Field(min_length=1, max_length=MAX_IDEA_TEXT)
    minutes: int = Field(ge=IDEA_MINUTES[0], le=IDEA_MINUTES[1])
    place: Place = "any"
    last_done: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")

    @classmethod
    def new(cls, text: str, minutes: int, place: Place = "any") -> Idea:
        clean = " ".join("".join(c if c.isprintable() else " " for c in str(text)).split())
        try:
            return cls(id=secrets.token_hex(4), text=clean, minutes=minutes, place=place)
        except ValidationError as exc:
            raise ValueError(
                f"An idea is 1 to {MAX_IDEA_TEXT} characters, {IDEA_MINUTES[0]} to "
                f"{IDEA_MINUTES[1]} minutes, indoor, outdoor or any."
            ) from exc


class NudgeSettings(BaseModel):
    """`nudges/{uid}`: his nudges (only the kinds he changed are stored) and his free-time list."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    nudges: dict[str, Nudge] = Field(default_factory=dict)
    ideas: tuple[Idea, ...] = Field(default=(), max_length=MAX_IDEAS)
    rev: int = Field(default=0, ge=0)

    @field_validator("nudges")
    @classmethod
    def _kinds(cls, v: dict[str, Nudge]) -> dict[str, Nudge]:
        if any(k not in DEFAULTS for k in v):
            raise ValueError("unknown nudge")
        return v

    def nudge(self, kind: str) -> Nudge:
        return self.nudges.get(kind) or DEFAULTS[kind]

    def changed(self, kind: str, changes: Mapping[str, Any]) -> NudgeSettings:
        if kind not in DEFAULTS:
            raise ValueError(f"Which nudge, Sir? Say {KINDS_HELP}.")
        try:
            new = Nudge.model_validate({**self.nudge(kind).model_dump(), **dict(changes)})
        except ValidationError as exc:
            raise ValueError(_plain(exc)) from exc
        return self.model_copy(update={"nudges": {**self.nudges, kind: new}})

    def with_idea(self, idea: Idea) -> NudgeSettings:
        if len(self.ideas) >= MAX_IDEAS:
            raise ValueError(f"Your free-time list holds {MAX_IDEAS} ideas; remove one first.")
        return self.model_copy(update={"ideas": (*self.ideas, idea)})

    def with_ideas(self, ideas: tuple[Idea, ...]) -> NudgeSettings:
        return self.model_copy(update={"ideas": ideas})

    def on_kinds(self) -> tuple[str, ...]:
        return tuple(k for k in NUDGE_KINDS if self.nudge(k).on)


def _plain(exc: ValidationError) -> str:
    """The first problem in plain words (pydantic's message, without its decoration)."""
    errors = exc.errors()
    msg = str(errors[0]["msg"]) if errors else "That setting isn't allowed."
    return msg.removeprefix("Value error, ")


__all__ = [
    "ALL",
    "DEFAULTS",
    "EVERY_KINDS",
    "KINDS_HELP",
    "LABEL",
    "MAX_IDEAS",
    "NAME",
    "NUDGE_KINDS",
    "TIMES_KINDS",
    "WEEK",
    "WORKWEEK",
    "Idea",
    "Nudge",
    "NudgeKind",
    "NudgeSettings",
    "Place",
    "clock",
    "kind_of",
]
