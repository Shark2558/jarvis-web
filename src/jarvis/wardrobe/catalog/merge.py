# src/jarvis/wardrobe/catalog/merge.py
"""Two records of one piece become one (docs/plans/r13-wardrobe.md D16; INV-16).

A merge keeps ONE active id with both histories: the merged-away id gets a `merged` event (an
Archived tombstone) and `merged_into` the kept id; its log pages never move, and `history` reads
the kept piece's log with every log merged into it, in time order. Its QR label, its pairs and its
sets go to the kept piece (a pair or set already holding the kept piece drops the other). Two
labelled copies are two physical pieces: refused ("confirmed separate copies stay two"). Merged
into a private piece, the other's photos and fingerprints go in the same commit (D9). It is a
card every time (`wardrobe_merge`: `ask_when` always, never "Approve all") and can be undone from
Recently deleted for 30 days: the undo only drops the link, and the piece comes back "Missing or
in review". Without the bin nothing is merged (there would be no undo).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from jarvis.storage.docs import DocTx, Op
from jarvis.wardrobe.catalog.events import event
from jarvis.wardrobe.catalog.fold import fold
from jarvis.wardrobe.catalog.store import NOT_IN, CatalogStore
from jarvis.wardrobe.model import Event, Pair, Piece, PieceSet, WardrobeView
from jarvis.wardrobe.ports import Commit, HistoryItem, Refused

# The photo vault's hook (D9): the deletes of a piece's photos and fingerprints, in this commit.
DropOps = Callable[[str, Piece, DocTx], Awaitable[list[Op]]]

TWO_COPIES = "These are two labelled copies: they stay two pieces."
NOT_ONE = "Only two records of the same kind of piece can be merged."


def _moved_links(view: WardrobeView, keep: str, other: str) -> WardrobeView:
    pairs: dict[str, Pair] = {}
    for k, x in view.pairs.items():
        if other not in x.pieces:
            pairs[k] = x
        elif keep not in x.pieces:
            pieces = tuple(keep if i == other else i for i in x.pieces)
            pairs[k] = x.model_copy(update={"pieces": pieces})
    sets: dict[str, PieceSet] = {}
    for k, s in view.sets.items():
        ids = [x.piece for x in s.parts]
        if other not in ids:
            sets[k] = s
        elif keep not in ids:
            parts = tuple(x.model_copy(update={"piece": keep}) if x.piece == other else x
                          for x in s.parts)  # fmt: skip
            sets[k] = s.model_copy(update={"parts": parts})
    labels = {k: (lb.model_copy(update={"piece": keep}) if lb.piece == other else lb)
              for k, lb in view.labels.items()}  # fmt: skip
    return view.model_copy(update={"pairs": pairs, "sets": sets, "labels": labels})


class Merge:
    def __init__(self, store: CatalogStore, *, drop_ops: DropOps | None = None) -> None:
        self.store, self._drop_ops = store, drop_ops

    async def merge(self, uid: str, keep: str, other: str) -> None:
        now = self.store.now()

        async def fn(view: WardrobeView, tx: DocTx) -> Commit:
            a, b = view.piece(keep), view.piece(other)
            if a is None or b is None or keep == other:
                raise Refused(NOT_IN)
            if "archived" in (a.state, b.state) or a.merged_into or b.merged_into:
                raise Refused(NOT_IN)
            if a.category != b.category:
                raise Refused(NOT_ONE)
            if a.label_code and b.label_code:
                raise Refused(TWO_COPIES)
            private = a.private or b.private  # one piece now: private if either was (review M2)
            kept = a.model_copy(update={"label_code": a.label_code or b.label_code,
                                        "private": private})  # fmt: skip
            gone = b.model_copy(update={"merged_into": keep, "label_code": None})
            extra: list[Op] = []
            if private and self._drop_ops is not None:
                for side in (a, b):  # no photo or print stays on a private piece, either side
                    if side.photos or side.fp_model:
                        extra += await self._drop_ops(uid, side, tx)
                kept = kept.model_copy(update={"photos": (), "fp_model": None})
                gone = gone.model_copy(update={"photos": (), "fp_model": None})
            e = event(other, "merged", now, via="merge")
            return Commit(events=(e,), records=(kept, gone), extra=tuple(extra))

        def links(fresh: WardrobeView) -> WardrobeView:
            return _moved_links(fresh, keep, other)

        await self.store.transact(uid, fn, index=links)

    async def unmerge(self, uid: str, other: str) -> None:
        """The bin's undo: drop the link; the piece comes back for a quick check."""
        now = self.store.now()

        async def fn(view: WardrobeView, tx: DocTx) -> Commit:
            p = view.piece(other)
            if p is None:
                raise Refused(NOT_IN)
            back = p.model_copy(update={"merged_into": None})
            return Commit(events=(event(other, "restored", now, via="bin"),), records=(back,))

        await self.store.transact(uid, fn)

    async def history(self, uid: str, pid: str) -> tuple[HistoryItem, ...]:
        """The kept piece's history with every log merged into it, in time order."""
        view = await self.store.view(uid)
        if view.piece(pid) is None:
            return ()
        ids, todo = [pid], [pid]
        while todo:
            into = todo.pop()
            found = [p.id for p in view.pieces.values() if p.merged_into == into]
            ids += found
            todo += found
        items: list[HistoryItem] = []
        for i in ids:
            events: list[Event] = await self.store.events(uid, i, view=view)
            marks = fold(events).marks
            items += [HistoryItem(e, marks[e.id]) for e in events]
        return tuple(sorted(items, key=lambda h: h.event.sort_key()))


__all__ = ["NOT_ONE", "TWO_COPIES", "Merge"]
