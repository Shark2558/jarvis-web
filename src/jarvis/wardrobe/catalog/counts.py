# src/jarvis/wardrobe/catalog/counts.py
"""What he owns, and what of it is wearable (docs/plans/r13-wardrobe.md D3; INV-04, 11, 12, 14).
Pure, over the index.

- Owned: every piece but an archived or merged-away one; laundry, a missing sock and a piece in
  review stay owned (INV-14). Ready: eligible (`states.eligible`). Review: pending checks, apart.
- A pair counts while both of its pieces are owned, and is complete only while both are
  eligible (INV-11, LND-13: the half that is out is named). A set likewise, saying which parts
  can go alone (INV-12).
- "Scope covered": the places he has never given a baseline scan (INV-02, INV-14).
"""

from __future__ import annotations

from jarvis.wardrobe.http import CountRow, Counts, PairView, SetView
from jarvis.wardrobe.model import CATEGORIES, Piece, WardrobeView
from jarvis.wardrobe.states import State, wearable_pair, wearable_set


def _owned(view: WardrobeView) -> dict[str, Piece]:
    return {p.id: p for p in view.active()}


def _state(owned: dict[str, Piece], pid: str) -> State | None:
    p = owned.get(pid)
    return p.state if p is not None else None


class Tally:
    @staticmethod
    def pair_views(view: WardrobeView) -> tuple[PairView, ...]:
        owned = _owned(view)
        out = []
        for x in view.pairs.values():
            if not all(i in owned for i in x.pieces):
                continue
            states = [_state(owned, i) for i in x.pieces]
            missing = tuple(i for i in x.pieces if _state(owned, i) != "ready")
            out.append(
                PairView(id=x.id, pieces=x.pieces, wearable=wearable_pair(states), missing=missing)
            )
        return tuple(out)

    @staticmethod
    def set_views(view: WardrobeView) -> tuple[SetView, ...]:
        owned = _owned(view)
        out = []
        for s in view.sets.values():
            if not all(x.piece in owned for x in s.parts):
                continue
            whole, alone = wearable_set([(_state(owned, x.piece), x.alone) for x in s.parts])
            out.append(
                SetView(
                    id=s.id, label=s.label, parts=tuple((x.piece, x.alone) for x in s.parts),
                    wearable=whole, alone=tuple(s.parts[i].piece for i in alone),
                )
            )  # fmt: skip
        return tuple(out)

    def of(self, view: WardrobeView, *, type_: str | None = None) -> Counts:
        """The counts; `type_` (a type or a category word) narrows the pieces counted."""
        active = [p for p in view.active() if type_ in (None, p.type, p.category)]
        pairs, sets = self.pair_views(view), self.set_views(view)
        if type_ is not None:
            ids = {p.id for p in active}
            pairs = tuple(x for x in pairs if set(x.pieces) <= ids)
            sets = tuple(x for x in sets if any(i in ids for i, _ in x.parts))
        rows = tuple(
            CountRow(
                category=c,
                owned=sum(p.category == c for p in active),
                ready=sum(p.category == c and p.eligible for p in active),
            )
            for c in CATEGORIES
            if any(p.category == c for p in active)
        )
        return Counts(
            owned=len(active), ready=sum(p.eligible for p in active),
            review=sum(p.state == "review" for p in active),
            pairs_complete=sum(x.wearable for x in pairs), pairs=len(pairs),
            sets_complete=sum(x.wearable for x in sets), sets=len(sets), by_category=rows,
            places_without_baseline=sum(pl.baseline_at is None for pl in view.places.values()),
        )  # fmt: skip


__all__ = ["Tally"]
