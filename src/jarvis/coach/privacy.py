# src/jarvis/coach/privacy.py
"""R8 I0 seam S8 (docs/plans/r8-vision.md v8.0.3 section 4.4, D6, ADR-51): Privacy's new section
"Health and fitness".

Three rows, one per kind of person whose results are saved (the owner's D6: everyone's):

- `coach_me`      his own results (`who` "me")
- `coach_people`  people he enrolled with consent in Faces (`who` an fp_ id)
- `coach_guests`  guests: "Guest 1", "Guest 2" ... of each session (`who` a gst_ id), and the
                  guests' registry (their labels and merges)

Each row counts, exports (JSON of the tallies, never a sealed blob) and deletes with the passkey
(it can't be brought back). A single person or guest is viewed, exported and deleted one tap away
in Camera -> Results -> People (`GET /v1/coach/people`, `GET /v1/coach/export?who=`, `DELETE
/v1/coach/people/{who}`): the privacy dashboard takes one row per source, so a row per person
would need the dashboard to take many rows from one source (recorded in I0-SEAMS.md, for I1).
Each row says what is never kept: a frame, a picture, a video, a body or hand point, a box.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from jarvis.coach.people import GUEST, ME, PERSON, PeopleStore
from jarvis.coach.store import CoachStore
from jarvis.privacy.sources import OURS_ENC, CallbackSource, Look, Spec

SECTION = "Health and fitness"
ME_ID, PEOPLE_ID, GUESTS_ID = "coach_me", "coach_people", "coach_guests"
OFF_NOTE = "Off: JARVIS has no token key, so no coach result is kept."
NEVER = (
    "Never kept: a camera frame, a picture, a video, a body or hand point, a box. Only counts, "
    "times, scores and labels from fixed lists. One person or guest at a time: Camera, Results, "
    "People."
)
WHAT = (
    "What the coaches counted, timed and scored for {who}: the coach, when, and its numbers "
    "(and blood-pressure readings he confirmed)."
)


def _is_me(who: str) -> bool:
    return who == ME


def _is_person(who: str) -> bool:
    return bool(PERSON.match(who))


def _is_guest(who: str) -> bool:
    return bool(GUEST.match(who))


def _row(
    store: CoachStore,
    rid: str,
    label: str,
    who_words: str,
    pick: Callable[[str], bool],
    people: PeopleStore | None = None,
) -> CallbackSource:
    async def look(uid: str) -> Look:
        if not store.sealed:
            return Look(0, deletable=False, note=OFF_NOTE)
        count = await store.count(uid, who=pick)
        return Look(count, [count], deletable=count > 0)

    async def export(uid: str) -> dict[str, Any]:
        items = (await store.export(uid))["results"]
        out: dict[str, Any] = {"results": [i for i in items if pick(str(i.get("who", "")))]}
        if people is not None and store.sealed:
            out["guests"] = (await people.export(uid))["guests"]
        return out

    async def delete(uid: str) -> int:
        return await store.delete_who(uid, pick)

    spec = Spec(rid, SECTION, label, WHAT.format(who=who_words), "results",
                f"{store.keep_days} days", OURS_ENC, encrypted_by_jarvis=True, delete="passkey",
                note=NEVER)  # fmt: skip
    return CallbackSource(spec, look, export, delete)


def coach_privacy(store: CoachStore, people: PeopleStore) -> tuple[CallbackSource, ...]:
    """The section's three rows, in the order the dashboard shows them."""
    return (
        _row(store, ME_ID, "Your coach results", "you", _is_me),
        _row(
            store,
            PEOPLE_ID,
            "Coach results of people you enrolled",
            "people you enrolled",
            _is_person,
        ),  # fmt: skip
        _row(store, GUESTS_ID, "Coach results of guests", "guests", _is_guest, people),
    )


__all__ = ["GUESTS_ID", "ME_ID", "PEOPLE_ID", "SECTION", "coach_privacy"]
