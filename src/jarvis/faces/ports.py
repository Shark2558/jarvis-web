# src/jarvis/faces/ports.py
"""The faces port (R3 D13, D10, D15).

`FaceDirectory.resolve(uid, person, score) -> Resolved` names a person only when ALL hold: the id
is `fp_<12 hex>`, it is in the owner's consent registry, enrolled, not being deleted, consent is
present and the score is at least `RECOGNITION_THRESHOLD`. Anything else (no sub-label, a name
someone typed in Frigate's UI, a deleted person, a low score) resolves to `UNKNOWN`: callers say
`UNKNOWN_PERSON` in the feed, history and tool results. Never "probably X".

`Resolved.vip` and `.child` can only be True for a named person (recognition only ever raises an
alert's level). In alerts, a child is never named (`FAMILY_CHILD`), and an adult is named only when
the owner switched names in alerts on (`RECOGNISED_PERSON` otherwise; the notifier decides).
`NoFaces` is the directory while Faces is off: it names nobody.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from jarvis.home.ports import PERSON_ID

RECOGNITION_THRESHOLD = 0.9  # Frigate's default recognition_threshold
UNKNOWN_PERSON = "someone JARVIS didn't recognise"
RECOGNISED_PERSON = "a person JARVIS recognised"
FAMILY_CHILD = "a child from your family"
MAX_NAME_CHARS = 40


def is_person_id(value: object) -> bool:
    return isinstance(value, str) and re.fullmatch(PERSON_ID, value) is not None


@dataclass(frozen=True)
class Resolved:
    name: str | None = None
    person: str | None = None  # the id, only when named
    vip: bool = False
    child: bool = False

    def __post_init__(self) -> None:
        if self.name is None:
            if self.person is not None or self.vip or self.child:
                raise ValueError("only a named person has an id, a VIP mark or a child mark")
            return
        if not self.name or len(self.name) > MAX_NAME_CHARS or not is_person_id(self.person):
            raise ValueError("a named person needs a name and an fp_ id")

    @property
    def named(self) -> bool:
        return self.name is not None


UNKNOWN = Resolved()


@runtime_checkable
class FaceDirectory(Protocol):
    async def resolve(self, uid: str, person: str | None, score: float | None) -> Resolved: ...


class NoFaces:
    """Faces is off (or nobody consented yet): nobody is ever named."""

    async def resolve(self, uid: str, person: str | None, score: float | None) -> Resolved:
        return UNKNOWN


__all__ = [
    "FAMILY_CHILD",
    "MAX_NAME_CHARS",
    "RECOGNISED_PERSON",
    "RECOGNITION_THRESHOLD",
    "UNKNOWN",
    "UNKNOWN_PERSON",
    "FaceDirectory",
    "NoFaces",
    "Resolved",
    "is_person_id",
]
