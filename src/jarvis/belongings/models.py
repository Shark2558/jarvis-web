# src/jarvis/belongings/models.py
"""What "Where did I keep it?" stores (R2 D11). Plain frozen data, JSON in and out; the store
encrypts it. Limits are the plan's: name 60, place 200, note 200, 4 aliases, 500 live things, 50
moves of history, 12 holders of 40 characters."""

from __future__ import annotations

import re
from dataclasses import dataclass, field, replace
from typing import Any, Literal

NAME_MAX = 60
PLACE_MAX = 200
NOTE_MAX = 200
ALIAS_MAX = 4
MAX_LIVE = 500
MAX_HISTORY = 50
MAX_HOLDERS = 12
HOLDER_MAX = 40
THING_ID = re.compile(r"t_[0-9a-f]{12}")
HOLDER_ID = re.compile(r"h_[0-9a-f]{8}")

Origin = Literal["typed", "voice", "outside"]
ORIGINS: tuple[str, ...] = ("typed", "voice", "outside")


@dataclass(frozen=True)
class Holder:
    id: str
    label: str


@dataclass(frozen=True)
class Thing:
    id: str
    name: str
    key: str
    place: str
    updated_at: str  # ISO 8601, UTC
    origin: str = "typed"
    aliases: tuple[str, ...] = ()
    note: str = ""
    holder_id: str | None = None
    deleted_at: str | None = None
    moves: int = 0  # how many earlier places are in its history (<= MAX_HISTORY)

    @property
    def live(self) -> bool:
        return self.deleted_at is None

    def to_json(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "key": self.key,
            "aliases": list(self.aliases),
            "place": self.place,
            "note": self.note,
            "holder_id": self.holder_id,
            "origin": self.origin,
            "updated_at": self.updated_at,
            "deleted_at": self.deleted_at,
            "moves": self.moves,
        }

    @classmethod
    def from_json(cls, raw: Any) -> Thing:
        if not isinstance(raw, dict):
            raise ValueError("thing")
        tid, name, key, place = raw.get("id"), raw.get("name"), raw.get("key"), raw.get("place")
        if not isinstance(tid, str) or not THING_ID.fullmatch(tid):
            raise ValueError("thing id")
        if not (isinstance(name, str) and isinstance(key, str) and isinstance(place, str)):
            raise ValueError("thing text")
        aliases = raw.get("aliases", [])
        if not isinstance(aliases, list) or not all(isinstance(a, str) for a in aliases):
            raise ValueError("aliases")
        holder = raw.get("holder_id")
        origin = raw.get("origin", "typed")
        when, gone, note = raw.get("updated_at"), raw.get("deleted_at"), raw.get("note", "")
        if holder is not None and not (isinstance(holder, str) and HOLDER_ID.fullmatch(holder)):
            raise ValueError("holder")
        if origin not in ORIGINS or not isinstance(when, str) or not isinstance(note, str):
            raise ValueError("thing fields")
        if gone is not None and not isinstance(gone, str):
            raise ValueError("deleted_at")
        moves = raw.get("moves", 0)
        if not isinstance(moves, int) or isinstance(moves, bool) or moves < 0:
            raise ValueError("moves")
        return cls(
            tid,
            name,
            key,
            place,
            when,
            origin,
            tuple(aliases),
            note,
            holder,
            gone,
            moves,
        )

    def moved(self, **changes: Any) -> Thing:
        return replace(self, **changes)


@dataclass(frozen=True)
class Move:
    """One earlier place: where it was, from when to when, and how that line was noted."""

    place: str
    from_at: str
    to_at: str
    origin: str = "typed"

    def to_json(self) -> dict[str, str]:
        return {
            "place": self.place,
            "from_at": self.from_at,
            "to_at": self.to_at,
            "origin": self.origin,
        }

    @classmethod
    def from_json(cls, raw: Any) -> Move:
        if not isinstance(raw, dict):
            raise ValueError("move")
        vals = [raw.get(k) for k in ("place", "from_at", "to_at")]
        if not all(isinstance(v, str) for v in vals) or raw.get("origin", "typed") not in ORIGINS:
            raise ValueError("move fields")
        return cls(vals[0], vals[1], vals[2], raw.get("origin", "typed"))  # type: ignore[arg-type]


@dataclass(frozen=True)
class State:
    rev: int = 0
    holders: tuple[Holder, ...] = ()
    things: tuple[Thing, ...] = field(default_factory=tuple)

    def live(self) -> list[Thing]:
        return [t for t in self.things if t.live]

    def get(self, thing_id: str) -> Thing | None:
        return next((t for t in self.things if t.id == thing_id), None)

    def with_thing(self, thing: Thing) -> State:
        found = any(t.id == thing.id for t in self.things)
        things = tuple(thing if t.id == thing.id else t for t in self.things)
        return replace(self, things=things if found else (*things, thing))

    def without(self, thing_id: str) -> State:
        return replace(self, things=tuple(t for t in self.things if t.id != thing_id))

    def holder_label(self, holder_id: str | None) -> str | None:
        return next((h.label for h in self.holders if h.id == holder_id), None)


__all__ = [
    "ALIAS_MAX",
    "HOLDER_MAX",
    "MAX_HISTORY",
    "MAX_HOLDERS",
    "MAX_LIVE",
    "NAME_MAX",
    "NOTE_MAX",
    "ORIGINS",
    "PLACE_MAX",
    "THING_ID",
    "Holder",
    "Move",
    "Origin",
    "State",
    "Thing",
]
