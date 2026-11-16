# tests/test_r13_c_actions.py -- R13 `outfit_plan`'s other actions (docs/plans/r13-wardrobe.md
# "Tools", D12, STY-12, STY-14): lock a slot (kept while still available) or a piece he names,
# release a piece or the whole plan, and each refusal in plain words writing nothing.
from __future__ import annotations

from typing import Any

from r13_fakes import UID
from r13_fakes_c import N, World, ist, world

from jarvis.tools.gateway import GatewayOutcome


async def ok(w: World, name: str, **args: Any) -> dict[str, Any]:
    got = await w.call(name, **args)
    assert got.outcome is GatewayOutcome.EXECUTED, (got.outcome, got.error)
    return got.result  # type: ignore[no-any-return]


async def _plan(w: World, **args: Any) -> dict[str, Any]:
    got = await ok(w, "outfit_plan", action="save", day="tomorrow", **args)
    return got["plan"]  # type: ignore[no-any-return]


def _slot(plan: dict[str, Any], slot: str) -> list[str]:
    return next((p["ids"] for p in plan["look"]["pieces"] if p["slot"] == slot), [])


async def test_a_locked_slot_stays_when_the_engine_would_choose_another() -> None:
    w = await world(at=ist(2026, 11, 16, 20, 0))
    plan = await _plan(w, occasion="meeting")
    locked = await ok(w, "outfit_plan", action="lock", plan=plan["id"], piece=N.shirt_lb)
    assert _slot(locked["plan"], "top") == [N.shirt_lb]
    doc = await w.styling.plans.read(UID)
    stored = doc.plan(plan["id"])
    assert stored is not None and stored.slot("top").locked  # type: ignore[union-attr]
    again = await ok(w, "outfit_plan", action="lock", plan=plan["id"], slot="watch")
    assert _slot(again["plan"], "watch") == [N.watch]


async def test_releasing_a_piece_resuggests_its_slot_and_releasing_the_plan_drops_it() -> None:
    w = await world(at=ist(2026, 11, 16, 20, 0))
    plan = await _plan(w, occasion="meeting")
    belt = _slot(plan, "belt")
    got = await ok(w, "outfit_plan", action="release", plan=plan["id"], piece=belt[0])
    assert _slot(got["plan"], "belt") == belt  # re-suggested: still the best one
    gone = await ok(w, "outfit_plan", action="release", plan=plan["id"])
    assert gone == {"message": "That plan is gone."}
    assert (await w.styling.plans.read(UID)).plans == ()


async def test_refusals_are_plain_words_and_write_nothing() -> None:
    w = await world(at=ist(2026, 11, 16, 20, 0))
    plan = await _plan(w)
    before = await w.styling.plans.read(UID)
    for args in (
        {"action": "change", "plan": plan["id"], "slot": "tie"},
        {"action": "lock", "plan": "op_00000000", "slot": "top"},
        {"action": "reserve", "plan": plan["id"], "piece": "wi_ffffffffffff"},
        {"action": "transfer", "plan": plan["id"], "from_plan": "op_00000000", "piece": N.tee},
        {"action": "save", "day": "2027-03-01"},
        {"action": "save", "day": "tomorrow", "start": "10:00"},
        {"action": "save", "day": "tomorrow", "start": "25:00", "end": "26:00"},
        {"action": "save", "day": "tomorrow", "code": "black_tie"},
    ):
        got = await ok(w, "outfit_plan", **args)
        assert got["refused"] is True and got["message"], args
    assert await w.styling.plans.read(UID) == before


async def test_a_shared_base_comes_from_an_earlier_plan_the_same_day() -> None:
    w = await world(at=ist(2026, 11, 17, 8, 0))
    late = await ok(w, "outfit_plan", action="save", day="today", start="19:00", end="21:00")
    early = await ok(w, "outfit_plan", action="save", day="today", start="09:00", end="10:00")
    got = await ok(w, "outfit_plan", action="share", plan=early["plan"]["id"],
                   from_plan=late["plan"]["id"], pieces=[N.watch])  # fmt: skip
    words = "A shared base comes from an earlier plan the same day."
    assert got == {"refused": True, "message": words}


async def test_transferring_a_piece_purged_since_it_was_planned_is_refused_in_words() -> None:
    from jarvis.wardrobe.styling.plans import PlanPick

    w = await world(at=ist(2026, 11, 16, 20, 0))
    first = await _plan(w, occasion="meeting", start="10:00", end="12:00")
    second = await _plan(w, start="15:00", end="16:00")
    gone = "wi_ffffffffffff"  # purged since: no longer in his wardrobe
    doc = await w.styling.plans.read(UID)
    held = doc.plan(first["id"]).model_copy(  # type: ignore[union-attr]
        update={"picks": (PlanPick(slot="cap", pieces=(gone,)),)}
    )
    await w.styling.change(UID, lambda d: d.put(held))
    got = await ok(w, "outfit_plan", action="transfer", plan=second["id"], from_plan=first["id"],
                   piece=gone)  # fmt: skip
    assert got == {"refused": True, "message": "That piece isn't in your wardrobe any more."}
