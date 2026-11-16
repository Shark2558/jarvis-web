# src/jarvis/wardrobe/laundry/writer.py
"""R13 Part B's `review_writer` service (docs/plans/r13-wardrobe.md D4.4, plan review H4).

The wiring binds it into A's store (`WardrobeStore.bind(review_writer=...)`): inside A's commit,
after the fold, A asks `entries(uid, view, tx, needed)` for every `ReviewNeeded` (a hold, a
conflict, a pending deposit) and writes the answer in the SAME commit, so a hold never lives
without the entry that resolves it. It reads B's queue through the commit's `tx` (before any
write) and answers ONE `Set` of the whole sealed document (or nothing, when every need is already
covered).

Two calls in one commit see each other: each answer is staged on that `tx` object (held weakly,
so it goes when the commit is over), and the next call in the same commit (B's own flow, C's
stale check through this same method, then the fold's needs) starts from it, so the last `Set` A
writes is the superset. That rests on two lines of A's
contract (ports: "writes the index, the log pages, `extra` and the entries LAST"): A passes the
same `tx` to `fn` and to the writer, and writes `extra` before the writer's entries.

Without a key it raises `LaundryUnavailable`: the commit rolls back, nothing is kept in clear.
`desk` is Part B's service for its own routes and tools (set by `part.build`).
"""

from __future__ import annotations

import weakref
from collections.abc import Callable, Sequence
from datetime import datetime
from typing import TYPE_CHECKING

from jarvis.storage.docs import DocTx, Op, Set
from jarvis.wardrobe.laundry import review
from jarvis.wardrobe.laundry.store import LaundryStore, ReviewDoc
from jarvis.wardrobe.model import WardrobeView
from jarvis.wardrobe.ports import ReviewNeeded

if TYPE_CHECKING:
    from jarvis.wardrobe.laundry.flows import Desk


class LaundryWriter:
    def __init__(self, store: LaundryStore, now: Callable[[], datetime]) -> None:
        self._store, self._now = store, now
        # keyed by the commit's own `tx` object, held weakly: a commit's staging goes with it
        # (review L7), and a retried transaction's new `tx` starts from a fresh read
        self._staged: weakref.WeakKeyDictionary[DocTx, dict[str, ReviewDoc]] = (
            weakref.WeakKeyDictionary()
        )
        self.desk: Desk | None = None

    def _slot(self, tx: DocTx) -> dict[str, ReviewDoc] | None:
        return self._staged.get(tx)

    def _stage(self, tx: DocTx, uid: str, doc: ReviewDoc) -> None:
        self._staged.setdefault(tx, {})[uid] = doc

    async def current(self, uid: str, tx: DocTx) -> ReviewDoc:
        """His queue as this commit sees it: staged by an earlier call in it, else read."""
        slot = self._slot(tx)
        if slot is not None and uid in slot:
            return slot[uid]
        return await self._store.read_review(tx.get, uid)

    def put(self, uid: str, tx: DocTx, doc: ReviewDoc) -> Set:
        """B's own new queue for this commit (staged for any later call in it)."""
        self._stage(tx, uid, doc)
        return self._store.review_op(uid, doc, self._now())

    async def entries(
        self, uid: str, view: WardrobeView, tx: DocTx, needed: Sequence[ReviewNeeded]
    ) -> Sequence[Op]:
        before = await self.current(uid, tx)
        after = review.add_needs(before, needed, view, self._now())
        if after == before:
            return ()
        return (self.put(uid, tx, after),)


__all__ = ["LaundryWriter"]
