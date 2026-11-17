# src/jarvis/wardrobe/styling/actions.py
"""R13 `outfit_plan`'s actions (docs/plans/r13-wardrobe.md "Tools", D12): save, lock, change,
reserve, transfer, release, share. Each reads his plans, the wardrobe view and the weather, then
writes ONE change of `wardrobe_plans/{uid}`; a refusal (`PlanRefused`) writes nothing, and a plan
another writer changed meanwhile is refused ("That plan changed meanwhile: try again.", M1).

- save: a plan for a day (and a time, an occasion or a dress code), its picks from the engine's
  primary look (a code he names is his: not tentative; an occasion's is tentative, STY-03); with
  `plan`, that plan again; `setting` marks it indoors or outdoors (STY-07, code review M7);
- lock: a slot's current pick, or a piece he names into its slot, kept from now on (STY-12); with
  `pieces` (one a slot), every slot at once in the ONE change, all or nothing (R13.1 D20);
- change: one slot again, every other pick kept while still eligible (STY-12);
- reserve: a piece (or its pair) into this plan, refused while another plan holds it (STY-14);

R13.1 D20 (plan review H2, the R13 fix): `lock` and `reserve` refuse a piece that isn't ready by
the engine's own rule (`unready`: only Ready; a pair whole; a set part that can't be worn alone
only with its whole set; an In-use piece only as the plan's declared shared base and reusable),
before anything is written: "The navy jacket is in the laundry: it can't be locked into this
plan." The check reads the view the tool itself just read: the guarantee behind any early check.
- transfer: deliberately from another plan (that one then needs a new one, STY-14);
- release: a piece out of the plan (its slot re-suggested), or the whole plan;
- share: a shared base from an earlier plan the same day (STY-13).
"""

from __future__ import annotations

from typing import Any

from jarvis.wardrobe.model import Piece, WardrobeView
from jarvis.wardrobe.styling import reserve, texts
from jarvis.wardrobe.styling.look import sets_of, whole
from jarvis.wardrobe.styling.plans import Plan, PlanPick, PlanRefused, StylingDoc, strict
from jarvis.wardrobe.styling.service import Here, Styling

ACTIONS = ("save", "lock", "change", "reserve", "transfer", "release", "share")
GONE = "That plan isn't there any more."


def _plan(doc: StylingDoc, pid: Any) -> Plan:
    plan = doc.plan(pid) if isinstance(pid, str) else None
    if plan is None:
        raise PlanRefused(GONE)
    return plan


def _slot_of(s: Styling, view: WardrobeView, pid: Any) -> tuple[str, tuple[str, ...]]:
    p = view.pieces.get(pid) if isinstance(pid, str) else None
    slot = s.rules.slot_of(p.type) if p is not None else None
    if p is None or slot is None:
        raise PlanRefused("That piece isn't one that goes in an outfit.")
    return slot, reserve.unit_of(view, p.id)


SETTINGS = {"indoor": False, "outdoor": True}
NOT_READY: dict[str, str] = {
    "in_laundry": "{is} in the laundry", "washing": "{is} in the laundry",
    "drying": "{is} in the laundry", "needs_prep": "needs pressing",
    "with_provider": "{is} at the laundry shop", "needs_repair": "needs a repair",
    "review": "needs a quick check", "in_use": "{is} in use", "archived": "{is} archived",
}  # fmt: skip
CANT_LOCK = "it can't be locked into this plan."


def _the(p: Piece) -> str:
    words = texts.piece_words(p)
    return "The " + (words[2:] if words.startswith("a ") else words)


def _handed(s: Styling, plan: Plan, p: Piece) -> bool:
    """In use for the very plan this one declared its shared base from, and reusable (D3)."""
    shared = plan.shared_from is not None and p.id in plan.shared
    return (
        p.state == "in_use" and shared and p.wear == plan.shared_from and s.rules.reusable_piece(p)
    )


def unready(s: Styling, view: WardrobeView, plan: Plan, unit: tuple[str, ...]) -> str | None:
    """The refusal's words when a piece of `unit` can't go into `plan` now, else None."""
    for pid in unit:
        p = view.pieces.get(pid)
        if p is None:
            return "That piece isn't in your wardrobe any more."
        if not (p.eligible or _handed(s, plan, p)):
            verb = "are" if p.type in texts.PLURAL_TYPES and not p.private else "is"
            state = NOT_READY.get(p.state, "{is} not ready").replace("{is}", verb)
            return f"{_the(p)} {state}: {CANT_LOCK}"
        for sid, parts in sets_of(view, pid):
            if not dict(parts).get(pid, True) and not whole(view, parts):
                return f"{_the(p)} is worn only with its set {sid}, which isn't ready: {CANT_LOCK}"
    return None


async def save(
    s: Styling, uid: str, here: Here, doc: StylingDoc, view: WardrobeView, a: dict[str, Any]
) -> Plan:
    """A new plan, or `plan`'s look made again; `setting` marks it indoors or outdoors (M7)."""
    if a.get("plan"):
        plan = _plan(doc, a["plan"])
    else:
        day = s.day_of(a.get("day"), here.today)
        if day is None:
            raise PlanRefused("A plan's day is today, tomorrow or a date up to 30 days ahead.")
        occ = s.rules.occasion_of(a["occasion"]) if a.get("occasion") else None
        starts, ends = s.at(day, a.get("start"), here.zone), s.at(day, a.get("end"), here.zone)
        code = a.get("code")
        plan = s.new_plan(here, day=day, occasion=occ, code=code, starts=starts, ends=ends)
    if a.get("setting") in SETTINGS:
        plan = plan.model_copy(update={"outdoor": SETTINGS[a["setting"]]})
    return await s.repick(uid, here, doc, view, plan)


async def run(s: Styling, uid: str, a: dict[str, Any]) -> tuple[Plan | None, str]:
    """(the plan after the action, or None when the plan was released; what changed)."""
    here, view = await s.where(uid), await s.view(uid)
    if view is None:
        raise PlanRefused("Your wardrobe isn't ready yet: try again in a minute.")
    doc = await s.plans.read(uid)
    action = a.get("action")
    if action == "save":
        plan = await save(s, uid, here, doc, view, a)
        await s.change(uid, lambda d: strict(d, doc.put(plan), {plan.id: doc.plan(plan.id)}))
        return plan, "Saved."
    plan = _plan(doc, a.get("plan"))
    if action == "release" and not a.get("piece"):
        await s.change(uid, lambda d: d.dismiss(plan))  # a calendar one is not made again (H1)
        return None, "That plan is gone."
    final = await _apply(s, uid, here, doc, view, plan, a)
    fresh = final.plan(plan.id)
    assert fresh is not None
    ids = {plan.id, str(a.get("from_plan") or "")} - {""}
    await s.change(uid, lambda d: strict(d, final, {i: doc.plan(i) for i in ids}))
    return fresh, "Done."


async def _apply(
    s: Styling, uid: str, here: Here, doc: StylingDoc, view: WardrobeView, plan: Plan,
    a: dict[str, Any],
) -> StylingDoc:  # fmt: skip
    """His plans after the action, this plan's picks already made again where it changed."""
    action = a.get("action")
    if action == "lock":
        return doc.put(_lock(s, here, doc, view, plan, a))
    if action == "change":
        slot = a.get("slot")
        current = plan.slot(slot) if isinstance(slot, str) else None
        if current is None:
            raise PlanRefused("That slot isn't in this plan.")
        skip = {current.slot: frozenset(current.pieces)}
        return doc.put(await s.repick(uid, here, doc, view, plan, skip=skip))
    changed = _held(s, here, doc, view, plan, a)
    fresh = changed.plan(plan.id)
    assert fresh is not None
    return changed.put(await s.repick(uid, here, changed, view, fresh))


def _held(
    s: Styling, here: Here, doc: StylingDoc, view: WardrobeView, plan: Plan, a: dict[str, Any]
) -> StylingDoc:
    """reserve, transfer, release one piece, share: what this plan holds."""
    action, asked = a.get("action"), str(a.get("piece") or "")
    if action == "reserve":
        slot, unit = _slot_of(s, view, asked)
        first = (asked, *(i for i in unit if i != asked))
        words = unready(s, view, plan, first) or reserve.conflict(doc, plan, first, here.zone)
        if words is not None:
            raise PlanRefused(words)
        return doc.put(reserve.with_pick(plan, PlanPick(slot=slot, pieces=unit, locked=True)))
    if action == "transfer":
        source = _plan(doc, a.get("from_plan"))
        return reserve.transfer(doc, plan, source, asked, view, s.rules)
    if action == "release":
        left, _slot = reserve.without(plan, [asked])
        return doc.put(left)
    if action == "share":
        source = _plan(doc, a.get("from_plan"))
        pieces = [str(x) for x in a.get("pieces") or []]
        return reserve.share(doc, plan, source, pieces, view, s.rules)
    raise PlanRefused("Say save, lock, change, reserve, transfer, release or share.")


def _one(
    s: Styling, here: Here, doc: StylingDoc, view: WardrobeView, plan: Plan, asked: Any
) -> PlanPick:
    """The locked pick for a piece he names: ready by the engine's rule (D20), held by no other
    plan (as `reserve` does: security review L1, STY-14); else `PlanRefused`, nothing written."""
    slot, unit = _slot_of(s, view, asked)
    first = (str(asked), *(i for i in unit if i != asked))
    words = unready(s, view, plan, first) or reserve.conflict(doc, plan, first, here.zone)
    if words is not None:
        raise PlanRefused(words)
    return PlanPick(slot=slot, pieces=unit, locked=True)


def _lock(
    s: Styling, here: Here, doc: StylingDoc, view: WardrobeView, plan: Plan, a: dict[str, Any]
) -> Plan:
    if a.get("piece"):
        return reserve.with_pick(plan, _one(s, here, doc, view, plan, a.get("piece")))
    if a.get("pieces"):  # every slot at once (D20): each checked before any is applied
        picks = [_one(s, here, doc, view, plan, pid) for pid in a["pieces"]]
        slots = [p.slot for p in picks]
        twice = next((x for x in slots if slots.count(x) > 1), None)
        if twice is not None:
            raise PlanRefused(f"One piece a slot: {twice} has two.")
        for pick in picks:
            plan = reserve.with_pick(plan, pick)
        return plan
    current = plan.slot(a["slot"]) if isinstance(a.get("slot"), str) else None
    if current is None:
        raise PlanRefused("That slot isn't in this plan.")
    return reserve.with_pick(plan, current.model_copy(update={"locked": True}))


__all__ = ["ACTIONS", "GONE", "run", "save"]
