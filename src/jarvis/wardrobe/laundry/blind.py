# src/jarvis/wardrobe/laundry/blind.py
"""R13 Part B: a blind period in its phone form (docs/plans/r13-wardrobe.md D5 OPS-02).

"I moved things without scanning": a tap naming the places or the categories touched, at the times
he states. Every piece at rest there (Ready, In laundry or Needs prep: not in the machine, not out,
not already waiting for a check) gets a `blind` event and is held until a rescan or his correction,
so it is verified before it appears in a ready plan; one "check these" entry covers them all. The
events are recorded at the moment he reports (the hold is about now; a back-dated hold would make a
later verified event a conflict); the start he states is kept on the entry, at most 30 days back
and never ahead (a day without a time is 12:00 his time, the caller's to make). A camera outage
later marks its zones blind the same way. Pure: no I/O.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timedelta

from jarvis.wardrobe.laundry import holds, texts
from jarvis.wardrobe.laundry.store import Change, Entry, new_entry_id
from jarvis.wardrobe.model import Piece, WardrobeView
from jarvis.wardrobe.ports import Refused
from jarvis.wardrobe.states import State

AT_REST: frozenset[State] = frozenset({"ready", "in_laundry", "needs_prep"})
STATED_WINDOW = timedelta(days=30)


def check_since(since: datetime | None, now: datetime) -> None:
    if since is not None and not now - STATED_WINDOW <= since <= now:
        raise Refused(texts.TIME_BAD)


def touched(
    view: WardrobeView, places: Sequence[str], categories: Sequence[str]
) -> tuple[Piece, ...]:
    if not places and not categories:
        raise Refused(texts.BLIND_NOTHING)
    if any(p not in view.places for p in places):
        raise Refused(texts.UNKNOWN_PLACE)
    return tuple(p for p in view.active() if (p.place in places) or (p.category in categories))


def plan_blind(
    view: WardrobeView,
    *,
    places: Sequence[str] = (),
    categories: Sequence[str] = (),
    since: datetime | None = None,
    now: datetime,
) -> Change:
    check_since(since, now)
    found = touched(view, places, categories)
    affected = [p for p in found if p.state in AT_REST]
    if not affected:
        if any(p.state == "review" for p in found):
            return Change(words=texts.ALREADY, already=True)
        raise Refused(texts.NOTHING_AT_REST)
    events = holds.hold_events(affected, "blind", now)
    ids = tuple(p.id for p in affected)
    entry = Entry(
        id=new_entry_id(),
        kind="rescan",
        reason="blind",
        pieces=ids,
        candidates=ids,
        events=tuple(e.id for e in events),
        place=places[0] if len(places) == 1 else None,
        category=categories[0] if len(categories) == 1 else None,  # type: ignore[arg-type]
        since=since,
        opened_at=now,
    )
    return Change(
        events=events,
        entries=(entry,),
        words=texts.blind_noted(len(ids)),
        pieces=ids,
        entry=entry.id,
    )


__all__ = ["AT_REST", "check_since", "plan_blind", "touched"]
