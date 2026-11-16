# src/jarvis/wardrobe/laundry/desk.py
"""R13 Part B's service core (`DeskCore`): the one commit and the reads (docs/plans/r13-wardrobe.md
D4.4, D11, plan review H4). The flows that write (`flows.Desk`) build on it.

`_commit` runs a pure planner inside `WardrobeStore.transact`: it reads B's two documents through
the commit's `tx` (every read first), plans against the view A read in the same transaction,
and hands back the events plus B's own writes (`Commit.extra`: the sealed laundry document and the
queue, staged with B's writer so the fold's entries land on top). A refusal (`Refused`) writes
nothing; a write that fails rolls the index, the logs and B's documents back together. Each event
carries the client's id (`{client_id}-{n}`: a retry is applied once) and the `rev` he saw ("already
done", M3). The reads (`status`, `history`, the two views) never write.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any
from zoneinfo import ZoneInfo

from jarvis.storage.docs import DocTx, Op
from jarvis.wardrobe.http import LaundryView, ReviewView
from jarvis.wardrobe.laundry import history, holds, review, texts
from jarvis.wardrobe.laundry.store import (
    Change,
    LaundryDoc,
    LaundryStore,
    LaundryUnavailable,
    ReviewDoc,
)
from jarvis.wardrobe.laundry.writer import LaundryWriter
from jarvis.wardrobe.model import Event, Piece, WardrobeView
from jarvis.wardrobe.ports import (
    Commit,
    Committed,
    HistoryItem,
    Refused,
    WardrobeContext,
    WardrobeStore,
)

Planner = Callable[[WardrobeView, LaundryDoc, ReviewDoc], Change]


@dataclass(frozen=True)
class Done:
    """A flow's answer: `done`, `already` (a second record: nothing changed) or `review` (an
    entry waits for him), its plain words, the pieces named, and what the store committed."""

    status: str
    message: str
    pieces: tuple[str, ...]
    committed: Committed | None
    entry: str | None = None
    load: str | None = None
    batch: str | None = None


def _stamp(
    events: Sequence[Event], client_id: str | None, rev: int | None, via: str
) -> tuple[Event, ...]:
    out = []
    for n, e in enumerate(events):
        update: dict[str, Any] = {"via": via}
        if client_id:
            update["client_id"] = f"{client_id}-{n}"
        if rev is not None:
            update["rev_seen"] = rev
        out.append(e.model_copy(update=update))
    return tuple(out)


class DeskCore:
    def __init__(self, ctx: WardrobeContext, store: LaundryStore, writer: LaundryWriter) -> None:
        self.ctx, self.store, self.writer = ctx, store, writer

    def wardrobe(self) -> WardrobeStore:
        if not self.store.available:
            raise LaundryUnavailable(texts.OFF)
        found = self.ctx.store()
        if found is None:
            raise LaundryUnavailable(texts.NO_WARDROBE)
        return found

    async def today(self, uid: str) -> tuple[datetime, date, ZoneInfo]:
        zone = await self.ctx.zone(uid)
        now = self.ctx.now()
        return now, now.astimezone(zone).date(), zone

    async def read(self, uid: str) -> tuple[WardrobeView, LaundryDoc, ReviewDoc]:
        wardrobe = self.wardrobe()
        assert self.store.docs is not None  # `wardrobe()` checked it
        get = self.store.docs.get
        view = await wardrobe.view(uid)
        return view, await self.store.read_laundry(get, uid), await self.store.read_review(get, uid)

    async def _retried(self, uid: str, pieces: Sequence[str], client_id: str | None) -> Done | None:
        """Review L3: a retry carrying the same client id is "already done", before any state
        check could refuse it with words about the state it already moved to (the first piece's
        history is enough: one call stamps every event `{client_id}-{n}`)."""
        if not client_id or not pieces:
            return None
        items = await self.wardrobe().history(uid, pieces[0])
        if any((h.event.client_id or "").startswith(f"{client_id}-") for h in items):
            return Done("already", texts.ALREADY, tuple(dict.fromkeys(pieces)), None)
        return None

    # ---- the one commit --------------------------------------------------------------------
    def _extra(
        self, uid: str, tx: DocTx, change: Change, laundry: LaundryDoc, queue: ReviewDoc
    ) -> tuple[Op, ...]:
        now = self.ctx.now()
        ops: list[Op] = []
        if change.laundry is not None and change.laundry != laundry:
            ops.append(self.store.laundry_op(uid, change.laundry, now))
        after = change.review or queue
        if change.entries:
            after = review.add(after, change.entries, now)
        if after != queue:
            ops.append(self.writer.put(uid, tx, after))
        return tuple(ops)

    async def _commit(
        self,
        uid: str,
        planner: Planner,
        *,
        client_id: str | None = None,
        rev: int | None = None,
        via: str = "panel",
    ) -> Done:
        wardrobe = self.wardrobe()
        box: dict[str, Change] = {}
        wrote: list[bool] = [False]

        async def fn(view: WardrobeView, tx: DocTx) -> Commit:
            laundry = await self.store.read_laundry(tx.get, uid)
            queue = await self.writer.current(uid, tx)
            change = box["change"] = planner(view, laundry, queue)
            events = _stamp(change.events, client_id, rev, via)
            extra = self._extra(uid, tx, change, laundry, queue)
            wrote[0] = bool(extra)  # B's own documents changed: never "already done"
            return Commit(events=events, extra=extra)

        done = await wardrobe.transact(uid, fn)
        change = box["change"]
        if change.already or (done.already and not wrote[0]):
            return Done("already", texts.ALREADY, change.pieces, done)
        status = "review" if change.entry else "done"
        return Done(
            status, change.words, change.pieces, done, change.entry, change.load, change.batch
        )

    # ---- reads -------------------------------------------------------------------------------
    async def status(self, uid: str) -> dict[str, Any]:
        view, laundry, queue = await self.read(uid)
        _, today, _ = await self.today(uid)
        return history.status(view, laundry, queue, today)

    async def history(
        self, uid: str, *, piece: str | None = None, query: str | None = None
    ) -> dict[str, Any]:
        wardrobe = self.wardrobe()
        view = await wardrobe.view(uid)
        if piece is None:
            found: tuple[Piece, ...] = holds.match(view, query or "")
            if len(found) != 1:
                ids = [p.id for p in found]
                words = texts.ambiguous(len(ids), basket=False) if ids else texts.NO_MATCH
                return {"found": False, "candidates": ids, "message": words}
            piece = found[0].id
        if piece not in view.pieces:
            raise Refused(texts.UNKNOWN_PIECE)
        now, _, zone = await self.today(uid)
        items: Sequence[HistoryItem] = await wardrobe.history(uid, piece)
        return history.piece_history(view, items, piece, now, zone)

    async def laundry_view(self, uid: str) -> LaundryView:
        view, laundry, _ = await self.read(uid)
        _, today, _ = await self.today(uid)
        return history.laundry_view(view, laundry, today, texts.READY)

    async def review_view(self, uid: str) -> ReviewView:
        _, _, queue = await self.read(uid)
        return review.review_view(queue, texts.READY)


__all__ = ["DeskCore", "Done", "Planner"]
