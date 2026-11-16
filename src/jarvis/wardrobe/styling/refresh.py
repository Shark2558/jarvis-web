# src/jarvis/wardrobe/styling/refresh.py
"""R13 STY-15, plan review H1 (docs/plans/r13-wardrobe.md D4.5, D12, D19): C's plan refresh, the
first observer A's store tells after each commit (`ChangeObserver`, `services["refresh"]`).

For every upcoming plan (not cancelled, not worn, its window not over) that holds the changed
piece:
- a wear started FOR THAT PLAN is no change: the plan is marked worn, nothing is sent (H1);
- a wear of a piece the plan declared shared from the plan it is worn for (a reusable piece, the
  hand-off of STY-13) is no change: nothing is marked, nothing is sent;
- a reusable piece worn today for another plan is no change for a plan on a later day (the
  rewear rule brings it back);
- a piece back to Ready clears that slot's "needs a new ...";
- anything else that takes the piece out of eligibility (the basket, the laundry shop, a hold, a
  repair, a wear for another plan the same day) marks the plan "needs a new <slot>", finds a
  ready substitute with every other pick kept (`engine.fill_one`) and, with auto-swap on (off
  by default), takes it; and when the plan's event starts within `wardrobe_change_window_h`
  (36 h) it sends ONE `outfit_changed` per plan per 2 hours, claimed before the send, in fixed
  words that never name his label, a title or a private piece.
An observer only reads the ledger and alerts; it writes only C's own plans, each only where it is
still as it was read (a plan changed meanwhile is judged once more, security review M1). It never
raises.
`WEAR_RULE` is read at call time: only the eval's negative control turns it off.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import Literal

from jarvis.logging import get_logger
from jarvis.notify.ports import Signal
from jarvis.wardrobe.model import Piece, WardrobeView
from jarvis.wardrobe.ports import PieceChange
from jarvis.wardrobe.styling import engine, texts
from jarvis.wardrobe.styling.calendar import Calendar
from jarvis.wardrobe.styling.plans import Plan, PlanPick, StylingDoc, cas
from jarvis.wardrobe.styling.reserve import window, with_pick
from jarvis.wardrobe.styling.service import Here, Styling

log = get_logger(__name__)
WEAR_RULE = True  # the eval's control turns it off; nothing else may
GAP = timedelta(hours=2)
Verdict = Literal["own", "handoff", "later", "back", "left"]


@dataclass(frozen=True)
class _Hit:
    plan: Plan
    verdict: Verdict


class PlanRefresh:
    """C's refresh; also how the routes reach the styling service and the calendar."""

    def __init__(self, styling: Styling, calendar: Calendar | None = None) -> None:
        self.styling, self.calendar = styling, calendar

    async def changed(self, change: PieceChange) -> None:
        try:
            await self._changed(change)
        except Exception as exc:  # noqa: BLE001 - an observer never breaks the commit or another
            log.warning("outfits: plan refresh failed", extra={"error": type(exc).__name__})

    def judge(self, plan: Plan, change: PieceChange, piece: Piece, here: Here) -> Verdict:
        s = self.styling
        reusable = s.rules.reusable_piece(piece)
        wear = change.kind in ("wear_started", "wear_done")
        if WEAR_RULE and wear and change.plan == plan.id:
            return "own"
        handed = plan.shared_from is not None and change.plan == plan.shared_from
        if WEAR_RULE and wear and handed and piece.id in plan.shared and reusable:
            return "handoff"
        if piece.eligible:
            return "back"
        if WEAR_RULE and change.kind == "wear_started" and reusable and plan.day > here.today:
            return "later"
        return "left"

    async def _changed(self, change: PieceChange, only: frozenset[str] | None = None) -> None:
        s = self.styling
        if s.off() is not None:
            return
        view = await s.view(change.uid)
        piece = view.pieces.get(change.piece) if view is not None else None
        if view is None or piece is None:
            return
        here, doc = await s.where(change.uid), await s.plans.read(change.uid)
        hits = [
            _Hit(p, self.judge(p, change, piece, here))
            for p in doc.plans
            if change.piece in p.pieces() and p.active and window(p, here.zone)[1] > here.now
            and (only is None or p.id in only)
        ]  # fmt: skip
        todo = [h for h in hits if h.verdict in ("own", "back", "left")]
        if not todo:
            return
        updated, alerts = await self._updates(change.uid, doc, view, piece, todo, here)
        seen = {p.id: doc.plan(p.id) for p in updated}
        ours = doc
        for p in updated:
            ours = ours.put(p)
        after = await s.change(change.uid, lambda d: cas(d, ours, seen))
        stale = frozenset(pid for pid in seen if after.plan(pid) != ours.plan(pid))
        for plan, proposal in alerts:
            if plan.id not in stale:
                await self._alert(change.uid, plan, piece, proposal, here)
        if stale and only is None:  # changed meanwhile (security review M1): judged once more
            await self._changed(change, stale)

    async def _updates(
        self, uid: str, doc: StylingDoc, view: WardrobeView, piece: Piece, hits: list[_Hit],
        here: Here,
    ) -> tuple[list[Plan], list[tuple[Plan, bool]]]:  # fmt: skip
        out, alerts = [], []
        within = timedelta(hours=self.styling.ctx.s.wardrobe_change_window_h)
        for h in hits:
            plan, pick = h.plan, h.plan.pick_of(piece.id)
            if h.verdict == "own":
                out.append(plan.model_copy(update={"worn": True, "updated_at": here.now}))
            elif h.verdict == "back" and pick is not None:
                needs = tuple(n for n in plan.needs if n != pick.slot)
                out.append(plan.model_copy(update={"needs": needs, "updated_at": here.now}))
            elif h.verdict == "left" and pick is not None:
                new, proposal = await self._left(uid, doc, view, plan, pick, here)
                out.append(new)
                if window(plan, here.zone)[0] - here.now <= within:
                    alerts.append((new, proposal is not None))
        return out, alerts

    async def _left(
        self, uid: str, doc: StylingDoc, view: WardrobeView, plan: Plan, pick: PlanPick,
        here: Here,
    ) -> tuple[Plan, engine.Pick | None]:  # fmt: skip
        s = self.styling
        ask, _ = await s.ask(
            uid, here, doc, day=plan.day, code=plan.code, occasion=plan.occasion, plan=plan
        )
        keep = [engine.Pick(p.slot, p.pieces, p.locked) for p in plan.picks if p is not pick]
        proposal = engine.fill_one(view, ask, s.rules, pick.slot, keep)
        needs = tuple(dict.fromkeys((*plan.needs, pick.slot)))
        new = plan.model_copy(update={"needs": needs, "updated_at": here.now})
        if doc.choice.auto_swap and proposal is not None:
            new = with_pick(new, PlanPick(slot=pick.slot, pieces=proposal.pieces))
        return new, proposal

    async def _alert(self, uid: str, plan: Plan, piece: Piece, proposal: bool, here: Here) -> None:
        s = self.styling
        notifier = s.ctx.notifier()
        if notifier is None or not await s.told.every(uid, f"changed_{plan.id}", GAP):
            return
        label = texts.outfit_label(plan.day, here.today, plan.starts, here.zone)
        words = texts.changed_alert(piece, label, proposal=proposal)
        try:
            await notifier.notify(uid, Signal(source="nudge", kind="outfit_changed"), words)
        except Exception as exc:  # noqa: BLE001 - "can't send" is a result, never an error
            log.warning("outfits: outfit_changed not sent", extra={"error": type(exc).__name__})


__all__ = ["GAP", "WEAR_RULE", "PlanRefresh"]
