# src/jarvis/wardrobe/laundry/review.py
"""R13 Part B: the review queue (docs/plans/r13-wardrobe.md D4.4, D11), pure (answering an entry:
`resolve.py`).

Entries: a pending deposit (no piece id; its plausible candidates held), a hold (an unverified
change, `held`, `missing`, `restored`, `blind`), a conflict (the table refused a step: nothing is
held), a stale check (C's quick check), a "which one?" rescan, and a "check this place" fold.
- `add_needs`: the writer's answer to the fold's `ReviewNeeded`s: a need already covered (its
  event, or its piece already held by an open entry) is merged, never written twice.
- `cap`: past 100 open entries the oldest stale checks fold into one "check this place" entry per
  place (then, if still over, into one for all); a pending deposit or a hold is never dropped.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timedelta
from typing import Any

from jarvis.wardrobe.http import ReviewEntry, ReviewView
from jarvis.wardrobe.laundry import texts
from jarvis.wardrobe.laundry.store import Change, Entry, ReviewDoc, new_entry_id
from jarvis.wardrobe.model import WardrobeView
from jarvis.wardrobe.ports import ReviewNeeded

MAX_OPEN = 100
_HOLDING = frozenset({"hold", "rescan", "pending_deposit"})


def open_entries(doc: ReviewDoc) -> tuple[Entry, ...]:
    return tuple(e for e in doc.entries if e.closed_at is None)


def find(doc: ReviewDoc, entry_id: str) -> Entry | None:
    return next((e for e in open_entries(doc) if e.id == entry_id), None)


def words_of(e: Entry) -> str:
    return texts.entry_words(e.kind, e.reason, candidates=len(e.candidates))


def _covers(e: Entry, need: ReviewNeeded) -> bool:
    if need.event is not None and need.event in e.events:
        return True
    p = need.piece
    if p is None:
        return False
    if need.kind == "hold":
        return e.kind in _HOLDING and p in e.pieces
    if need.kind == "conflict":
        return e.kind == "conflict" and p in e.candidates
    if need.kind == "stale":
        return e.kind in ("stale", "place") and p in e.candidates
    return False


def from_need(need: ReviewNeeded, view: WardrobeView, now: datetime) -> Entry:
    p = need.piece
    one = (p,) if p else ()
    base: dict[str, Any] = {
        "id": new_entry_id(),
        "events": (need.event,) if need.event else (),
        "opened_at": now,
        "back_to": need.back_to,
        "candidates": one,
    }
    if need.kind == "hold":
        return Entry.model_validate(
            {**base, "kind": "hold", "reason": need.reason or "held", "pieces": one}
        )
    if need.kind == "conflict":
        return Entry.model_validate({**base, "kind": "conflict", "reason": "refused"})
    if need.kind == "stale":
        place = view.pieces[p].place if p and p in view.pieces else None
        return Entry.model_validate({**base, "kind": "stale", "reason": "stale", "place": place})
    if need.kind == "pending_deposit":
        cands = tuple(need.candidates) or one
        return Entry.model_validate(
            {
                **base,
                "kind": "pending_deposit",
                "reason": "pending",
                "candidates": cands,
                "count": 1,
            }
        )
    held = one if need.reason == "blind" else ()
    return Entry.model_validate(
        {
            **base,
            "kind": "rescan",
            "reason": need.reason or "rescan",
            "pieces": held,
            "candidates": (*one, *need.candidates),
        }
    )


def covered(doc: ReviewDoc, need: ReviewNeeded) -> bool:
    return any(_covers(e, need) for e in open_entries(doc))


def reopen(view: WardrobeView, doc: ReviewDoc, piece: str, now: datetime) -> Change:
    """Review H3's stop-gap: a correction left this piece held and no open entry answers it
    (the fold asks for none after a `corrected`, until I1): its check, from the piece's own
    hold. Nothing to do ("already") when it isn't held or an entry already holds it."""
    p = view.pieces.get(piece)
    if p is None or p.state != "review" or p.hold is None:
        return Change(already=True)
    need = ReviewNeeded("hold", piece, None, back_to=p.back_to, reason=p.hold)
    if covered(doc, need):
        return Change(already=True)
    entry = from_need(need, view, now)
    return Change(entries=(entry,), words=texts.CORRECTED_HELD, pieces=(piece,), entry=entry.id)


def put(doc: ReviewDoc, entry: Entry) -> ReviewDoc:
    entries = [entry if e.id == entry.id else e for e in doc.entries]
    if all(e.id != entry.id for e in doc.entries):
        entries.append(entry)
    return doc.model_copy(update={"entries": tuple(entries)})


def add_needs(
    doc: ReviewDoc, needs: Sequence[ReviewNeeded], view: WardrobeView, now: datetime
) -> ReviewDoc:
    out = doc
    for need in needs:
        cover = next((e for e in open_entries(out) if _covers(e, need)), None)
        if cover is None:
            out = put(out, from_need(need, view, now))
        elif need.event is not None and need.event not in cover.events:
            out = put(out, cover.model_copy(update={"events": (*cover.events, need.event)}))
    return cap(out, now)


def add(doc: ReviewDoc, entries: Sequence[Entry], now: datetime) -> ReviewDoc:
    out = doc
    for e in entries:
        out = put(out, e)
    return cap(out, now)


def _fold(doc: ReviewDoc, group: Sequence[Entry], place: str | None, now: datetime) -> ReviewDoc:
    gone = {e.id for e in group}
    into = next(
        (
            e
            for e in open_entries(doc)
            if e.kind == "place" and e.place == place and e.id not in gone
        ),
        None,
    )
    cands = tuple(
        dict.fromkeys(
            (*(into.candidates if into else ()), *(c for e in group for c in e.candidates))
        )
    )
    folded = (
        into
        or Entry(
            id=new_entry_id(),
            kind="place",
            reason="stale",
            place=place,
            opened_at=min(e.opened_at for e in group),
        )
    ).model_copy(update={"candidates": cands})
    kept = tuple(e for e in doc.entries if e.id not in gone)
    return put(doc.model_copy(update={"entries": kept}), folded)


def cap(doc: ReviewDoc, now: datetime) -> ReviewDoc:
    out = doc
    while len(open_entries(out)) > MAX_OPEN:
        stale = sorted(
            (e for e in open_entries(out) if e.kind == "stale"), key=lambda e: e.opened_at
        )
        if not stale:
            break
        place = stale[0].place
        group = [e for e in stale if e.place == place]
        if len(group) == 1 and not any(
            e.kind == "place" and e.place == place for e in open_entries(out)
        ):
            group = stale  # each place has one: fold every stale check into one
            place = None
        out = _fold(out, group, place, now)
    return out


def prune(doc: ReviewDoc, now: datetime, *, keep_days: int) -> ReviewDoc:
    keep = timedelta(days=keep_days)
    kept = tuple(e for e in doc.entries if e.closed_at is None or now - e.closed_at <= keep)
    return doc.model_copy(update={"entries": kept})


def entry_view(e: Entry) -> ReviewEntry:
    return ReviewEntry(
        id=e.id,
        kind=e.kind,
        pieces=e.pieces,
        candidates=e.candidates,
        words=words_of(e),
        opened_at=e.opened_at,
    )


def review_view(doc: ReviewDoc, ready: str) -> ReviewView:
    shown = sorted(open_entries(doc), key=lambda e: e.opened_at)
    return ReviewView(
        ready=ready, entries=tuple(entry_view(e) for e in shown[:MAX_OPEN]), open=len(shown)
    )


def ask_which(
    step: str, candidates: Sequence[str], *, load: str | None, place: str | None, now: datetime
) -> Change:
    """A name that fits several pieces, for a step after the basket: ask, hold nothing."""
    entry = Entry(
        id=new_entry_id(),
        kind="rescan",
        reason="which",
        candidates=tuple(candidates),
        step=step,
        load=load,
        place=place,
        opened_at=now,
    )
    words = texts.ambiguous(len(candidates), basket=False)
    return Change(entries=(entry,), words=words, pieces=tuple(candidates), entry=entry.id)


__all__ = [
    "MAX_OPEN",
    "add",
    "add_needs",
    "ask_which",
    "cap",
    "covered",
    "entry_view",
    "find",
    "from_need",
    "open_entries",
    "prune",
    "put",
    "reopen",
    "review_view",
    "words_of",
]
