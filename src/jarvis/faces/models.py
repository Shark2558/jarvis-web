# src/jarvis/faces/models.py
"""What the Faces registry stores (R3 D13). Plain frozen data, JSON in and out; the store encrypts
it. Names, relations and consent records only: never a picture or an embedding (those stay on the
owner's laptop)."""

from __future__ import annotations

import secrets
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Any

from jarvis.faces.ports import MAX_NAME_CHARS, is_person_id
from jarvis.home.ports import MAX_PEOPLE, MAX_PICTURES

NAME_MAX = MAX_NAME_CHARS  # 40
RELATIONS: tuple[str, ...] = ("family", "friend", "helper", "other")
GIVEN_BY: tuple[str, ...] = ("self", "parent_guardian")
STATES: tuple[str, ...] = ("consented", "enrolled", "deleting")
CONSENT_VERSION = "fc1"
MAX = MAX_PEOPLE  # 30


def new_person_id() -> str:
    return "fp_" + secrets.token_hex(6)


def _iso(value: object, what: str) -> str:
    if not isinstance(value, str):
        raise ValueError(what)
    datetime.fromisoformat(value)
    return value


@dataclass(frozen=True)
class Person:
    id: str
    name: str
    relation: str
    child: bool
    vip: bool
    consent_version: str
    given_by: str
    consent_at: str
    state: str
    created_at: str
    images_at_home: int | None = None
    delete_requested_at: str | None = None

    def __post_init__(self) -> None:
        if not is_person_id(self.id) or not self.name or len(self.name) > NAME_MAX:
            raise ValueError("person")
        if self.relation not in RELATIONS or self.given_by not in GIVEN_BY:
            raise ValueError("person")
        if self.state not in STATES:
            raise ValueError("person")
        if self.child != (self.given_by == "parent_guardian"):
            raise ValueError("a child needs a guardian's consent, an adult their own")

    @property
    def naming(self) -> bool:
        """May the directory name this person? Enrolled, consent on record, not being deleted."""
        return self.state == "enrolled" and bool(self.consent_version) and bool(self.consent_at)

    def with_(self, **changes: Any) -> Person:
        return replace(self, **changes)

    def to_json(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "relation": self.relation,
            "child": self.child,
            "vip": self.vip,
            "consent": {
                "version": self.consent_version,
                "given_by": self.given_by,
                "at": self.consent_at,
            },
            "state": self.state,
            "images_at_home": self.images_at_home,
            "created_at": self.created_at,
            "delete_requested_at": self.delete_requested_at,
        }

    @classmethod
    def from_json(cls, raw: Any) -> Person:
        if not isinstance(raw, dict) or not isinstance(raw.get("consent"), dict):
            raise ValueError("person")
        consent = raw["consent"]
        images = raw.get("images_at_home")
        if images is not None and (
            isinstance(images, bool)
            or not isinstance(images, int)
            or not 0 <= images <= MAX_PICTURES
        ):
            raise ValueError("person")
        gone = raw.get("delete_requested_at")
        if not all(isinstance(raw.get(k), bool) for k in ("child", "vip")):
            raise ValueError("person")
        return cls(
            id=str(raw["id"]),
            name=str(raw["name"]),
            relation=str(raw["relation"]),
            child=raw["child"],
            vip=raw["vip"],
            consent_version=str(consent["version"]),
            given_by=str(consent["given_by"]),
            consent_at=_iso(consent["at"], "person"),
            state=str(raw["state"]),
            created_at=_iso(raw["created_at"], "person"),
            images_at_home=images,
            delete_requested_at=None if gone is None else _iso(gone, "person"),
        )


@dataclass(frozen=True)
class State:
    rev: int = 0
    people: tuple[Person, ...] = ()

    def find(self, person_id: str) -> Person | None:
        return next((p for p in self.people if p.id == person_id), None)

    def live(self) -> tuple[Person, ...]:
        """People whose names JARVIS may still hold (not being deleted)."""
        return tuple(p for p in self.people if p.state != "deleting")

    def deleting(self) -> tuple[Person, ...]:
        return tuple(p for p in self.people if p.state == "deleting")


__all__ = [
    "CONSENT_VERSION",
    "GIVEN_BY",
    "MAX",
    "NAME_MAX",
    "RELATIONS",
    "STATES",
    "Person",
    "State",
    "new_person_id",
]
