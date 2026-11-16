# src/jarvis/wardrobe/laundry/flows.py
"""R13 Part B's service (`Desk`): every laundry change is ONE commit of A's store
(docs/plans/r13-wardrobe.md D4.4, D11, plan review H4).

`_commit` runs a pure planner inside `WardrobeStore.transact`: it reads B's two documents through
the commit's `tx` (every read first), plans against the view A read in the same transaction,
and hands back the events plus B's own writes (`Commit.extra`: the sealed laundry document and the
queue, staged with B's writer so the fold's entries land on top). A refusal (`Refused`) writes
nothing; a write that fails rolls the index, the logs and B's documents back together. Each event
carries the client's id (`{client_id}-{n}`: a retry is applied once) and the `rev` he saw ("already
done", M3). B records taps at the server's now; a time he states is checked (<= 30 days back,
never ahead; a day is 12:00 his time). The reads (`status`, `history`, the two views) never write.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, time
from typing import Any
from zoneinfo import ZoneInfo

from jarvis.storage.docs import DocTx, Op
from jarvis.wardrobe.http import LaundryView, ReviewView
from jarvis.wardrobe.laundry import (
    blind,
    history,
    holds,
    loads,
    providers,
    resolve,
    review,
    texts,
)
from jarvis.wardrobe.laundry.store import (
    Change,
    LaundryDoc,
    LaundryStore,
    LaundryUnavailable,
    Origin,
    Outcome,
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
from jarvis.wardrobe.states import State

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


class Desk:
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

    # ---- the flows ---------------------------------------------------------------------------
    async def move(
        self,
        uid: str,
        step: str,
        *,
        pieces: Sequence[str] = (),
        query: str | None = None,
        one_of: Sequence[str] = (),
        more: int = 0,
        category: str | None = None,
        place: str | None = None,
        load: str | None = None,
        client_id: str | None = None,
        rev: int | None = None,
        via: str = "panel",
    ) -> Done:
        now = self.ctx.now()

        def plan(view: WardrobeView, laundry: LaundryDoc, queue: ReviewDoc) -> Change:
            ids, cands = holds.known(view, pieces), holds.known(view, one_of)
            if query:
                hit = holds.resolve_query(view, step, query)
                ids, cands = (ids + list(hit), cands) if len(hit) == 1 else (ids, list(hit))
            if place is not None and place not in view.places:
                raise Refused(texts.UNKNOWN_PLACE)
            if step == "basket":
                return holds.plan_basket(
                    view, ids, one_of=cands, more=more, category=category, place=place, now=now
                )
            if cands:
                return review.ask_which(step, cands, load=load, place=place, now=now)
            return loads.plan_step(view, laundry, step, ids, load=load, place=place, now=now)

        return await self._commit(uid, plan, client_id=client_id, rev=rev, via=via)

    async def send_out(
        self,
        uid: str,
        pieces: Sequence[str],
        shop: str,
        *,
        bag: str = "",
        due: date | None = None,
        origin: Origin = "typed",
        client_id: str | None = None,
        via: str = "panel",
    ) -> Done:
        label, ref = providers.clean_shop(shop), providers.clean_bag(bag)
        now, today, _ = await self.today(uid)
        providers.check_due(due, today)

        def plan(view: WardrobeView, laundry: LaundryDoc, queue: ReviewDoc) -> Change:
            return providers.plan_send(
                view,
                laundry,
                holds.known(view, pieces),
                shop=label,
                bag=ref,
                due=due,
                origin=origin,
                now=now,
            )

        return await self._commit(uid, plan, client_id=client_id, via=via)

    async def receive(
        self,
        uid: str,
        batch: str,
        pieces: Sequence[str],
        *,
        to: State = "ready",
        client_id: str | None = None,
        via: str = "panel",
    ) -> Done:
        now = self.ctx.now()

        def plan(view: WardrobeView, laundry: LaundryDoc, queue: ReviewDoc) -> Change:
            return providers.plan_receive(
                view, laundry, batch, holds.known(view, pieces), to=to, now=now
            )

        return await self._commit(uid, plan, client_id=client_id, via=via)

    async def blind(
        self,
        uid: str,
        *,
        places: Sequence[str] = (),
        categories: Sequence[str] = (),
        since: datetime | None = None,
        day: date | None = None,
        via: str = "panel",
    ) -> Done:
        now, _, zone = await self.today(uid)
        if day is not None:
            since = datetime.combine(day, time(12, 0), tzinfo=zone).astimezone(UTC)

        def plan(view: WardrobeView, laundry: LaundryDoc, queue: ReviewDoc) -> Change:
            return blind.plan_blind(
                view, places=places, categories=categories, since=since, now=now
            )

        return await self._commit(uid, plan, via=via)

    async def _originals(self, uid: str, entry_id: str, outcome: Outcome) -> dict[str, Event]:
        """The unverified events a "yes, it happened" records again (read before the commit):
        for each piece whose OWN hold is an unconfirmed change, the events its entry names, else
        its newest one the fold marked `held` (an entry A's sweep repaired names none)."""
        assert self.store.docs is not None
        queue = await self.store.read_review(self.store.docs.get, uid)
        entry = review.find(queue, entry_id)
        if entry is None:
            raise Refused(texts.ENTRY_GONE)
        if outcome != "these":
            return {}
        wardrobe = self.wardrobe()
        view = await wardrobe.view(uid)
        out: dict[str, Event] = {}
        for pid in entry.pieces:
            p = view.pieces.get(pid)
            if p is None or p.state != "review" or p.hold != "unverified":
                continue
            items = await wardrobe.history(uid, pid)
            named = [h.event for h in items if h.event.id in entry.events]
            held = [h.event for h in items if h.mark == "held"]
            pick = named or ([max(held, key=Event.sort_key)] if held else [])
            out.update({e.id: e for e in pick})
        return out

    async def resolve(
        self,
        uid: str,
        entry: str,
        outcome: Outcome,
        *,
        pieces: Sequence[str] = (),
        to: State | None = None,
        place: str | None = None,
        how: str = "tap",
        via: str = "panel",
    ) -> Done:
        self.wardrobe()
        originals = await self._originals(uid, entry, outcome)
        now = self.ctx.now()

        def plan(view: WardrobeView, laundry: LaundryDoc, queue: ReviewDoc) -> Change:
            return resolve.plan_resolve(
                view,
                laundry,
                queue,
                entry,
                outcome,
                pieces=pieces,
                to=to,
                place=place,
                how=how,
                originals=originals,
                now=now,
            )

        return await self._commit(uid, plan, via=via)

    async def correct(self, uid: str, piece: str, event: str | None = None) -> Done:
        """LND-05 through A's `correct`: the event is voided and the piece re-folded."""
        wardrobe = self.wardrobe()
        if (await wardrobe.view(uid)).piece(piece) is None:
            raise Refused(texts.UNKNOWN_PIECE)
        target = history.to_correct(await wardrobe.history(uid, piece), event)
        done = await wardrobe.correct(uid, piece, target)
        return await self._reopen(uid, piece, done) or Done("done", texts.CORRECTED, (piece,), done)

    async def _reopen(self, uid: str, piece: str, done: Committed) -> Done | None:
        """Review H3's stop-gap: a correction that leaves the piece held gets its check in a
        second commit (the atomic fix is I1's: the fold asks for it); A's sweep stays the
        backstop if this one fails."""
        p = done.view.piece(piece)
        if p is None or p.state != "review":
            return None
        now = self.ctx.now()

        def plan(view: WardrobeView, laundry: LaundryDoc, queue: ReviewDoc) -> Change:
            return review.reopen(view, queue, piece, now)

        got = await self._commit(uid, plan)
        return got if got.status == "review" else None

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


__all__ = ["Desk", "Done"]
