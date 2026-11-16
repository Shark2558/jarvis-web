# src/jarvis/wardrobe/laundry/blind.py
"""R13 Part B: a blind period in its phone form (docs/plans/r13-wardrobe.md D5 OPS-02).

"I moved things without scanning": a tap naming the places or the categories touched, at the times
he states. Every piece at rest there (Ready, In laundry or Needs prep: not in the machine, not out)
gets a `blind` event and is held until a rescan or his correction, so it is verified before it
appears in a ready plan; one "check these" entry covers them all. A piece there that another
check already holds is on the entry too (`waiting`, review M4): when that check lets it go
unverified, it is held again for this one; when he verifies it there (a deposit, a found, a
confirmed change) it leaves the list. The events are recorded at the moment he reports (the hold
is about now; a back-dated hold would make a later verified event a conflict); the start he states
is kept on the entry, at most 30 days back and never ahead (a day without a time is 12:00 his
time, the caller's to make). A camera outage later marks its zones blind the same way. Pure.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timedelta

from jarvis.wardrobe.laundry import holds, texts
from jarvis.wardrobe.laundry.review import open_entries, put
from jarvis.wardrobe.laundry.store import Change, Entry, ReviewDoc, new_entry_id
from jarvis.wardrobe.model import Event, Piece, WardrobeView
from jarvis.wardrobe.ports import Refused
from jarvis.wardrobe.states import State

AT_REST: frozenset[State] = frozenset({"ready", "in_laundry", "needs_prep"})
STATED_WINDOW = timedelta(days=30)
CHUNK = 200  # pieces one blind check (and one commit) holds: Entry's cap, < 500 writes a commit


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


def _blind_checks(doc: ReviewDoc) -> tuple[Entry, ...]:
    return tuple(e for e in open_entries(doc) if e.kind == "rescan" and e.reason == "blind")


def covered(doc: ReviewDoc) -> set[str]:
    """Every piece an open blind check holds or waits for."""
    return {p for e in _blind_checks(doc) for p in (*e.pieces, *e.waiting)}


def plan_blind(
    view: WardrobeView,
    queue: ReviewDoc,
    *,
    places: Sequence[str] = (),
    categories: Sequence[str] = (),
    since: datetime | None = None,
    now: datetime,
) -> Change:
    check_since(since, now)
    found = touched(view, places, categories)
    cover = covered(queue)
    elsewhere = tuple(p.id for p in found if p.state == "review" and p.id not in cover)[:CHUNK]
    affected = [p for p in found if p.state in AT_REST][: CHUNK - len(elsewhere)]
    if not affected and not elsewhere:
        if any(p.state == "review" for p in found):  # a blind check covers every one of them
            return Change(words=texts.ALREADY, already=True)
        raise Refused(texts.NOTHING_AT_REST)
    events = holds.hold_events(affected, "blind", now)
    ids = tuple(p.id for p in affected)
    entry = Entry(
        id=new_entry_id(),
        kind="rescan",
        reason="blind",
        pieces=ids,
        candidates=ids + elsewhere,
        waiting=elsewhere,
        events=tuple(e.id for e in events),
        place=places[0] if len(places) == 1 else None,
        category=categories[0] if len(categories) == 1 else None,  # type: ignore[arg-type]
        since=since,
        opened_at=now,
    )
    return Change(
        events=events,
        entries=(entry,),
        words=texts.blind_noted(len(ids) + len(elsewhere)),
        pieces=ids + elsewhere,
        entry=entry.id,
    )


def _waits_in(doc: ReviewDoc, pid: str, skip: str) -> Entry | None:
    return next((e for e in _blind_checks(doc) if e.id != skip and pid in e.waiting), None)


def rehold(
    view: WardrobeView, doc: ReviewDoc, pid: str, skip: str, now: datetime
) -> tuple[list[Event], ReviewDoc]:
    """Another check lets this piece go unverified to a state at rest while a blind check still
    waits for it: it is held again for that check (after its `released`, same commit)."""
    e, p = _waits_in(doc, pid, skip), view.pieces.get(pid)
    if e is None or p is None:
        return [], doc
    if p.back_to not in AT_REST:  # not at rest (in use, at the shop): not this check's
        return [], settle(doc, pid, skip, now)
    made = list(holds.hold_events([p], "blind", now))
    left = tuple(x for x in e.waiting if x != pid)
    moved = e.model_copy(
        update={
            "waiting": left,
            "pieces": (*e.pieces, pid),
            "events": (*e.events, *(x.id for x in made)),
        }
    )
    return made, put(doc, moved)


def settle(doc: ReviewDoc, pid: str, skip: str, now: datetime) -> ReviewDoc:
    """He verified this piece (a deposit, a found, a confirmed change): no blind check needed."""
    e = _waits_in(doc, pid, skip)
    if e is None:
        return doc
    left = tuple(x for x in e.waiting if x != pid)
    update: dict[str, object] = {"waiting": left}
    if not left and not e.pieces:
        update["closed_at"] = now
    return put(doc, e.model_copy(update=update))


__all__ = [
    "AT_REST",
    "CHUNK",
    "check_since",
    "covered",
    "plan_blind",
    "rehold",
    "settle",
    "touched",
]
