# src/jarvis/wardrobe/laundry/flows.py
"""R13 Part B's flows that write (`Desk`, on `desk.DeskCore`): every laundry change is ONE
commit of A's store (docs/plans/r13-wardrobe.md D4.4, D11, plan review H4).

Each flow hands a pure planner to `DeskCore._commit` (basket and steps, outside batches, a blind
period, answering a check, striking out a step). B records taps at the server's now; a time he
states is checked (<= 30 days back, never ahead; a day is 12:00 his time).
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, date, datetime, time

from jarvis.wardrobe.laundry import (
    blind,
    corrections,
    history,
    holds,
    loads,
    providers,
    resolve,
    review,
    texts,
)
from jarvis.wardrobe.laundry.desk import DeskCore, Done
from jarvis.wardrobe.laundry.store import Change, LaundryDoc, Origin, Outcome, ReviewDoc
from jarvis.wardrobe.model import Event, WardrobeView
from jarvis.wardrobe.ports import Committed, Refused
from jarvis.wardrobe.states import State


class Desk(DeskCore):
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
                one = len(hit) == 1  # L2: a piece named by id and by his words counts once
                ids, cands = (
                    (list(dict.fromkeys(ids + list(hit))), cands) if one else (ids, list(hit))
                )
            if place is not None and place not in view.places:
                raise Refused(texts.UNKNOWN_PLACE)
            if step == "basket":
                return holds.plan_basket(
                    view, ids, one_of=cands, more=more, category=category, place=place, now=now
                )
            if cands:
                return review.ask_which(step, cands, load=load, place=place, now=now)
            return loads.plan_step(view, laundry, step, ids, load=load, place=place, now=now)

        if retried := await self._retried(uid, pieces, client_id):
            return retried
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
        if retried := await self._retried(uid, pieces, client_id):
            return retried
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

        if retried := await self._retried(uid, pieces, client_id):
            return retried
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
        """OPS-02. A day without a time is 12:00 his time, or now for today before noon (L4).
        Past `blind.CHUNK` pieces, each commit holds at most that many with its own check
        (Entry and Firestore's 500 writes a commit, L5); a later chunk holds nothing twice."""
        now, today, zone = await self.today(uid)
        if day is not None:
            noon = datetime.combine(day, time(12, 0), tzinfo=zone).astimezone(UTC)
            since = min(noon, now) if day == today else noon

        def plan(view: WardrobeView, laundry: LaundryDoc, queue: ReviewDoc) -> Change:
            return blind.plan_blind(
                view, queue, places=places, categories=categories, since=since, now=now
            )

        first = last = await self._commit(uid, plan, via=via)
        held = len(first.pieces) if first.status == "review" else 0
        for _ in range(-(-self.ctx.s.wardrobe_max_pieces // blind.CHUNK)):
            if last.status != "review" or len(last.pieces) < blind.CHUNK:
                break
            last = await self._commit(uid, plan, via=via)
            held += len(last.pieces) if last.status == "review" else 0
        if held <= len(first.pieces):
            return first
        words = texts.blind_noted(held)
        return Done("review", words, first.pieces, first.committed, first.entry)

    async def _originals(self, uid: str, entry_id: str, outcome: Outcome) -> dict[str, Event]:
        """The unverified events a "yes, it happened" records again (read before the commit):
        for each piece whose OWN hold is an unconfirmed change, the events its entry names, else
        its newest one the fold marked `held` (an entry A's sweep repaired names none)."""
        assert self.store.docs is not None
        queue = await self.store.read_review(self.store.docs.get, uid)
        entry = review.find_open(queue, entry_id)
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
        """LND-05: the step is voided (the `corrected` event A's `correct` builds) and B's own
        loads, batches and checks follow it in the SAME commit (review M1)."""
        wardrobe = self.wardrobe()
        if (await wardrobe.view(uid)).piece(piece) is None:
            raise Refused(texts.UNKNOWN_PIECE)
        target = history.to_correct(await wardrobe.history(uid, piece), event)
        now = self.ctx.now()

        def plan(view: WardrobeView, laundry: LaundryDoc, queue: ReviewDoc) -> Change:
            return corrections.plan_correct(view, laundry, queue, target, now)

        done = await self._commit(uid, plan)
        assert done.committed is not None  # a commit ran
        return await self._reopen(uid, piece, done.committed) or done

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


__all__ = ["Desk", "Done"]
