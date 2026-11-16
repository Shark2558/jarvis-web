# src/jarvis/wardrobe/catalog/work.py
"""One commit's working set (docs/plans/r13-wardrobe.md D4.4, OPS-03), private to the store's
`_fold_in`: the records a commit takes, the re-fold of each piece it touched (marks, the entries
B's writer is asked for, the changes observers hear), the piece cap, and how a storage op is
applied inside the transaction. Pure over its inputs: no I/O, no clock (times are passed in).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime

from jarvis.storage.docs import Create, Delete, DocTx, Op, Set
from jarvis.wardrobe.catalog import fold as folding
from jarvis.wardrobe.model import Event, Piece, WardrobeView
from jarvis.wardrobe.ports import Mark, PieceChange, Refused, ReviewNeeded
from jarvis.wardrobe.states import State

# what only the fold sets: a record from a tool never changes them (the state is never by hand)
FOLD_OWNED: tuple[str, ...] = (
    *("state", "back_to", "place", "place_at", "hold", "expected_back", "wear", "wears"),
    *("last_worn", "events", "created_at"),
)


def too_many(cap: int) -> str:
    return f"Your wardrobe holds at most {cap} pieces: archive or remove a few pieces first."


@dataclass
class Work:
    """One commit's working set (mutable, private to one `_fold_in` call)."""

    pieces: dict[str, Piece]
    logs: dict[str, list[Event]] = field(default_factory=dict)
    new: dict[str, list[Event]] = field(default_factory=dict)
    marks: dict[str, Mark] = field(default_factory=dict)
    needed: list[ReviewNeeded] = field(default_factory=list)
    changes: list[PieceChange] = field(default_factory=list)


def take_records(w: Work, records: Sequence[Piece], now: datetime) -> None:
    for rec in records:
        old = w.pieces.get(rec.id)
        # a new record has no log yet, whatever it says; an old one keeps the fold's fields
        keep = {k: getattr(old, k) for k in FOLD_OWNED} if old is not None else {"events": 0}
        fresh = rec.model_copy(update={**keep, "updated_at": now})
        if old is None and fresh.created_at is None:
            fresh = fresh.model_copy(update={"created_at": now})
        w.pieces[rec.id] = fresh


def _asks(w: Work, pid: str, f: folding.Folded) -> None:
    log_, added = w.logs[pid], w.new[pid]
    for e in added:
        if (need := folding.needs(e, f.marks[e.id], f)) is not None:
            w.needed.append(need)
    fixes = [e for e in added if e.kind == "corrected"]
    if fixes:
        ids = {e.id for e in added}
        w.needed += folding.rescans(pid, folding.fold(x for x in log_ if x.id not in ids).marks, f)
        before = w.pieces[pid]  # a correction that leaves the piece held opens its check (H3)
        if f.state == "review" and f.hold and before.state != "review":
            w.needed.append(
                ReviewNeeded("hold", pid, fixes[-1].id, back_to=f.back_to, reason=f.hold)
            )


def refold(w: Work, uid: str, pid: str, now: datetime, *, as_stored: bool = False) -> None:
    """`as_stored` (a restore): the history's old marks ask for nothing (each was settled long
    ago); only a hold the piece is in NOW asks for its entry (M3 of review A-1)."""
    log_, added = w.logs[pid], w.new[pid]
    f = folding.fold(log_)
    for e in added:
        w.marks[e.id] = f.marks[e.id]
    if not as_stored:
        _asks(w, pid, f)
    elif f.state == "review" and f.hold:
        w.needed.append(ReviewNeeded("hold", pid, back_to=f.back_to, reason=f.hold))
    before = w.pieces[pid]
    after = before.model_copy(
        update={
            "state": f.state or before.state, "back_to": f.back_to,
            "place": f.place or before.place, "place_at": f.place_at or before.place_at,
            "hold": f.hold, "expected_back": f.expected_back, "wear": f.wear,
            "wears": f.wears, "last_worn": f.last_worn, "events": len(log_), "updated_at": now,
        }
    )  # fmt: skip
    w.pieces[pid] = after
    if (before.state, before.place, before.wear) != (after.state, after.place, after.wear):
        last = max(added, key=Event.sort_key)
        prior: State | None = before.state if before.events else None
        w.changes.append(PieceChange(uid, pid, last.kind, prior, after.state, last.plan))


def check_cap(view: WardrobeView, pieces: Mapping[str, Piece], max_pieces: int) -> None:
    def active(ps: Mapping[str, Piece]) -> int:
        return sum(p.state != "archived" and p.merged_into is None for p in ps.values())

    if active(pieces) > max(max_pieces, active(view.pieces)):
        raise Refused(too_many(max_pieces))


def apply_op(tx: DocTx, op: Op) -> None:
    if isinstance(op, Set):
        tx.set(op.path, op.data)
    elif isinstance(op, Create):
        tx.create(op.path, op.data)
    elif isinstance(op, Delete):
        tx.delete(op.path)


__all__ = ["FOLD_OWNED", "Work", "apply_op", "check_cap", "refold", "take_records", "too_many"]
