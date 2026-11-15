# src/jarvis/wardrobe/catalog/fold.py
"""The order rule (docs/plans/r13-wardrobe.md D4, OPS-03, plan review M1-M3): Part A's own fold.

Pure and order-independent: a piece's whole history, sorted by `(at, recorded, id)`, folds to its
state and each event's mark. The marks are computed on every fold and never written back into the
append-only log:

- `voided`: a `corrected` event names it; the fold runs from the valid history (LND-05);
- `superseded`: unverified and older than the piece's newest verified state-setting event (an old
  basket message after a confirmed clean return can't make the shirt dirty again); a superseded
  `wear_done` still counts as a wear;
- `duplicate`: a second record of the current state (and place), never a review entry or a hold;
- `conflict`: the table refuses it (`states.allowed`): an entry, no hold;
- `held`: unverified and it would change availability: a hold (`back_to` kept), never a state;
- `applied`: everything else.

`settle` is the one time rule (D4.1): a device's `at + (now - sent)`, refused if ahead or older
than 24 hours; a time he states, at most 30 days back and never ahead; `recorded` is after every
event before it in the log (arrival breaks a tie). `needs` turns marks into the entries B's writer
adds in the same commit. `tests/test_r13_fold_conformance.py` holds this fold to I0's reference.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from types import MappingProxyType

from jarvis.wardrobe.model import Event
from jarvis.wardrobe.ports import Mark, Refused, ReviewNeeded
from jarvis.wardrobe.states import (
    HOLDING,
    STATE_SETTING,
    State,
    allowed,
    changes_availability,
    target_of,
)

DEVICE_WINDOW = timedelta(hours=24)  # a device's corrected time: never ahead, at most a day old
STATED_WINDOW = timedelta(days=30)  # a time he states: never ahead, at most 30 days back
TICK = timedelta(microseconds=1)
DEVICE_REFUSED = "That scan's time is outside the last 24 hours: scan it again."
STATED_REFUSED = "A time can be at most 30 days back and never ahead."
SortKey = tuple[datetime, datetime, str]


@dataclass(frozen=True)
class Folded:
    """A piece's state after its whole history, and each event's mark."""

    state: State | None = None
    back_to: State | None = None
    place: str | None = None
    place_at: datetime | None = None
    hold: str | None = None
    expected_back: date | None = None
    wear: str | None = None
    wears: int = 0
    last_worn: datetime | None = None
    marks: Mapping[str, Mark] = field(default_factory=lambda: MappingProxyType({}))


@dataclass(slots=True)
class _Acc:
    """The fold's working state (private to one `fold` call; the result is frozen)."""

    state: State | None = None
    back_to: State | None = None
    place: str | None = None
    place_at: datetime | None = None
    hold: str | None = None
    expected_back: date | None = None
    wear: str | None = None
    wears: int = 0
    last_worn: datetime | None = None

    def frozen(self, marks: dict[str, Mark]) -> Folded:
        return Folded(
            self.state, self.back_to, self.place, self.place_at, self.hold,
            self.expected_back, self.wear, self.wears, self.last_worn, MappingProxyType(marks),
        )  # fmt: skip


def _newest_verified(events: Sequence[Event], voided: set[str]) -> SortKey | None:
    keys = [
        e.sort_key()
        for e in events
        if e.verified and e.kind in STATE_SETTING and e.id not in voided
    ]
    return max(keys) if keys else None


def _apply_place(f: _Acc, e: Event) -> bool:
    if e.place is None or e.place == f.place:
        return False
    f.place, f.place_at = e.place, e.at
    return True


def _land(f: _Acc, e: Event, target: State) -> None:
    """Move to `target`, keeping what each kind remembers."""
    before = f.state
    if target == "review":
        if e.kind in HOLDING:
            f.back_to = before if before not in (None, "review") else f.back_to
        elif e.kind == "restored":
            f.back_to = "ready"
        f.hold = e.kind
    else:
        f.hold, f.back_to = None, None
    if e.kind == "wear_started":
        f.wear = e.plan or e.id
    elif e.kind == "wear_done":
        f.wear = None
    if e.kind == "sent_out":
        f.expected_back = e.due
    elif before == "with_provider":
        f.expected_back = None
    f.state = target
    _apply_place(f, e)


def _move(f: _Acc, e: Event) -> Mark:
    target = target_of(e.kind, f.state, to=e.to, back_to=f.back_to)
    hand_off = e.kind == "wear_started" and f.state == "in_use" and (e.plan or e.id) != f.wear
    if target is not None and target == f.state and not hand_off:
        return "applied" if _apply_place(f, e) else "duplicate"
    if target is None or not allowed(e.kind, f.state):
        return "conflict"
    if not e.verified and changes_availability(f.state, target):
        f.back_to = f.state if f.state not in (None, "review") else f.back_to
        f.state, f.hold = "review", "unverified"
        return "held"
    _land(f, e, target)
    return "applied"


def _step(f: _Acc, e: Event, newest: SortKey | None) -> Mark:
    if e.kind == "corrected":
        return "applied"
    older = not e.verified and newest is not None and e.sort_key() < newest
    mark: Mark = "superseded" if older else _move(f, e)
    if e.kind == "wear_done" and mark in ("applied", "superseded"):  # still a wear (D4.3)
        f.wears += 1
        f.last_worn = max(f.last_worn or e.at, e.at)
    return mark


def fold(history: Iterable[Event]) -> Folded:
    """Pure and order-independent: the piece's whole history, sorted by (at, recorded, id)."""
    events = sorted(history, key=Event.sort_key)
    voided = {e.voids for e in events if e.kind == "corrected" and e.voids}
    newest = _newest_verified(events, voided)
    acc, marks = _Acc(), {}
    for e in events:
        marks[e.id] = "voided" if e.id in voided else _step(acc, e, newest)
    return acc.frozen(marks)


def settle(e: Event, now: datetime, log: Sequence[Event]) -> Event:
    """D4.1: the stored time of `e` (a device's clock corrected by `sent`), refused in plain
    words outside its window; `recorded` after every event already in the piece's log."""
    if e.sent is not None:
        at = e.at + (now - e.sent)
        if at > now or at < now - DEVICE_WINDOW:
            raise Refused(DEVICE_REFUSED)
    else:
        at = e.at
        if at > now or at < now - STATED_WINDOW:
            raise Refused(STATED_REFUSED)
    last = max((x.recorded for x in log), default=None)
    recorded = now if last is None else max(now, last + TICK)
    return e.model_copy(update={"at": at, "recorded": recorded})


def needs(e: Event, mark: Mark, f: Folded) -> ReviewNeeded | None:
    """The entry an event's mark asks for (B's writer adds it in the same commit)."""
    if mark == "conflict":
        return ReviewNeeded("conflict", e.piece, e.id, reason="refused")
    if mark == "held":
        return ReviewNeeded("hold", e.piece, e.id, back_to=f.back_to, reason="unverified")
    if mark == "applied" and e.kind in (*HOLDING, "restored"):
        return ReviewNeeded("hold", e.piece, e.id, back_to=f.back_to, reason=e.kind)
    return None


def rescans(piece: str, before: Mapping[str, Mark], after: Folded) -> tuple[ReviewNeeded, ...]:
    """D4.3: after a correction, later events that now conflict ask for ONE rescan of the piece
    (never a guess at which of them is right)."""
    newly = [i for i, m in after.marks.items() if m == "conflict" and before.get(i) != "conflict"]
    if not newly:
        return ()
    return (ReviewNeeded("rescan", piece, newly[0], reason="corrected"),)


__all__ = [
    "DEVICE_REFUSED",
    "DEVICE_WINDOW",
    "STATED_REFUSED",
    "STATED_WINDOW",
    "Folded",
    "fold",
    "needs",
    "rescans",
    "settle",
]
