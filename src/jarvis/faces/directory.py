# src/jarvis/faces/directory.py
"""`Directory.resolve`: the one place a person id becomes a name (R3 D13; a `FaceDirectory`).

A name comes out only when ALL hold: the id is `fp_<12 hex>`; it is in the owner's registry; its
state is `enrolled`; it is not being deleted; consent is on record; the score is at least the
recognition threshold. Anything else (no id, a name typed in Frigate's UI, a deleted person, a low
score, an unreadable registry) is UNKNOWN. Fails closed; never "probably X".
"""

from __future__ import annotations

import math

from jarvis.faces.ports import (
    FAMILY_CHILD,
    RECOGNISED_PERSON,
    RECOGNITION_THRESHOLD,
    UNKNOWN,
    UNKNOWN_PERSON,
    Resolved,
    is_person_id,
)
from jarvis.faces.store import FacesStore, FacesUnavailable


class Directory:
    def __init__(self, store: FacesStore) -> None:
        self._store = store

    async def resolve(self, uid: str, person: str | None, score: float | None) -> Resolved:
        if (
            not is_person_id(person)
            or isinstance(score, bool)
            or not isinstance(score, int | float)
        ):
            return UNKNOWN
        if not math.isfinite(score) or score < RECOGNITION_THRESHOLD:
            return UNKNOWN
        try:
            state = await self._store.load(uid)
        except (FacesUnavailable, ValueError):
            return UNKNOWN
        found = state.find(str(person))
        if found is None or not found.naming:
            return UNKNOWN
        return Resolved(name=found.name, person=found.id, vip=found.vip, child=found.child)


def alert_words(who: Resolved, *, say_names: bool) -> str:
    """How an alert, a push or a spoken line refers to a person (R3 D10, D13). A child is never
    named; an adult only when the owner switched names in alerts on; an unnamed one is "someone
    JARVIS didn't recognise". Use this wherever text leaves the console."""
    if not who.named:
        return UNKNOWN_PERSON
    if who.child:
        return FAMILY_CHILD
    return who.name or RECOGNISED_PERSON if say_names else RECOGNISED_PERSON


__all__ = ["Directory", "alert_words"]
