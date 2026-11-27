# src/jarvis/coach/target.py
"""R8 I0 seam S25 (docs/plans/r8-vision.md v8.0.3 D6): the tracking target.

The owner's words: "Please track all and not only me. When I say jarvis to track me, it should
only track me. If I say track Shruti, it should identify and track that person and by default it
should track all."

    TrackTarget(kind="all")                       everyone in view (the default)
    TrackTarget(kind="me")                        only him
    TrackTarget(kind="person", person="fp_...")   only one person enrolled with consent in Faces

Set by voice (`phrase_target`: "track me", "track everyone", "track <name>") or on screen
(`PUT /v1/coach/target`), kept in `{prefix}coach_target/{uid}` (a kind and an fp_ id, never a
name), pushed to every live look (the console's `JarvisVision.live(..., {target})`, the home
laptop's `CoachState`). A name is turned into an id only through R3's consent registry
(`PeopleLookup.find`): a name nobody enrolled answers `NOT_ENROLLED` ("I don't know Shruti yet:
enrol their face first.") and the target is unchanged. Identifying a named person works on the
home camera (the face library lives on the laptop); on a device camera `not_here` says so.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from datetime import datetime
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from jarvis.storage.docs import Docs, Set
from jarvis.storage.sessions import safe_id

COLLECTION = "coach_target"
TargetKind = Literal["all", "me", "person"]
PERSON_ID = r"^fp_[0-9a-f]{12}$"
NAME_MAX = 40
NOT_ENROLLED = "I don't know {name} yet: enrol their face first."
NOT_HERE = "I can recognise {name} only on the home camera, Sir; here I follow everyone or you."
# the fixed phrases (the console's local router and the server's; no AI needed)
TRACK_ME: tuple[str, ...] = ("track me", "track only me", "just track me", "follow me")
TRACK_ALL: tuple[str, ...] = (
    *("track everyone", "track everybody", "track all", "track all of us", "follow everyone"),
)
_TRACK_NAME = re.compile(r"^(?:track|follow)(?: only)? (?P<name>[a-z][a-z .'-]{0,39})$")
_WAKE = re.compile(r"^(?:hey )?jarvis[,.!]?\s+")


class TrackTarget(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: TargetKind = "all"
    person: str | None = Field(default=None, pattern=PERSON_ID)

    @model_validator(mode="after")
    def _person_only_for_a_person(self) -> TrackTarget:
        if (self.kind == "person") != (self.person is not None):
            raise ValueError("a person target names one enrolled id, and only it does")
        return self


EVERYONE = TrackTarget()


class PeopleLookup(Protocol):
    """R3's consent registry: the fp_ id of an enrolled person by the name he says, else None."""

    async def find(self, uid: str, name: str) -> str | None: ...


def said(text: str) -> str:
    """What he said, folded: lower case, single spaces, no "Jarvis," in front, no full stop."""
    t = " ".join(str(text).lower().replace("’", "'").split()).rstrip(".!?")
    return _WAKE.sub("", t)


def phrase_target(text: str) -> TrackTarget | str | None:
    """`TrackTarget` for "track me" / "track everyone"; the NAME (a str) for "track <name>",
    which `resolve_name` turns into a target; None when it isn't a tracking phrase."""
    t = said(text)
    if t in TRACK_ME:
        return TrackTarget(kind="me")
    if t in TRACK_ALL:
        return EVERYONE
    m = _TRACK_NAME.match(t)
    if m is None:
        return None
    name = m["name"].strip()
    return name if name not in ("me", "everyone", "everybody", "all") else None


async def resolve_name(uid: str, name: str, people: PeopleLookup) -> TrackTarget | str:
    """The target for a spoken name, or the plain reply when nobody by that name is enrolled."""
    shown = " ".join(str(name).split())[:NAME_MAX].title()
    found = await people.find(uid, name)
    if found is None or re.fullmatch(PERSON_ID, found) is None:
        return NOT_ENROLLED.format(name=shown)
    return TrackTarget(kind="person", person=found)


class TargetStore:
    """`{prefix}coach_target/{uid}`: {kind, person, rev, updated_at}; a bad document reads as
    everyone (the default), never as someone else."""

    def __init__(self, docs: Docs, *, prefix: str = "jarvis_", now: Callable[[], datetime]) -> None:
        self._docs, self._prefix, self._now = docs, prefix, now

    def _path(self, uid: str) -> str:
        if not isinstance(uid, str) or not safe_id(uid):
            raise ValueError("invalid user id")
        return f"{self._prefix}{COLLECTION}/{uid}"

    async def get(self, uid: str) -> TrackTarget:
        doc = await self._docs.get(self._path(uid))
        if not doc:
            return EVERYONE
        try:
            return TrackTarget.model_validate(
                {"kind": doc.get("kind"), "person": doc.get("person")}
            )
        except ValidationError:
            return EVERYONE

    async def set(self, uid: str, target: TrackTarget) -> TrackTarget:
        path = self._path(uid)
        doc = {**target.model_dump(), "uid": uid, "updated_at": self._now().isoformat()}
        await self._docs.write([Set(path, doc)])
        return target


__all__ = [
    "COLLECTION",
    "EVERYONE",
    "NOT_ENROLLED",
    "NOT_HERE",
    "TRACK_ALL",
    "TRACK_ME",
    "PeopleLookup",
    "TargetStore",
    "TrackTarget",
    "phrase_target",
    "resolve_name",
    "said",
]
