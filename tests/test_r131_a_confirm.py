# tests/test_r131_a_confirm.py -- R13.1 Part A, D7 and D20 (AVT-09): "Use this look for the plan".
# The server re-checks every piece from a FRESH view BEFORE any tool call and refuses a draft in
# plain words ("The navy jacket is in the laundry: it can't be confirmed for this event."); when
# all are eligible it makes ONE `outfit_plan` `lock` with `pieces` (one a slot, every slot at once)
# through R13's real gateway. The early check is for the words; `outfit_plan`'s own check is the
# guarantee: a piece that goes to the laundry between the two is refused there, the plan unchanged.
from __future__ import annotations

from typing import Any

import pytest
from r131_fakes_a import SHOES, UID, AWorld, T, a_world

from jarvis.tools.gateway import GatewayOutcome, GatewayResult
from jarvis.wardrobe.tryon import confirm
from jarvis.wardrobe.tryon.http import ConfirmIn, ConfirmSlot
from jarvis.wardrobe.tryon.looks import GONE_PLAN, NoLook

IN_LAUNDRY = "The navy jacket is in the laundry: it can't be confirmed for this event."
LOCK_REFUSED = "The navy jacket is in the laundry: it can't be locked into this plan."


class Calls:
    """The one tool call, through the world's real gateway; `before` runs just ahead of it."""

    def __init__(self, a: AWorld, before: Any = None) -> None:
        self.a, self.before, self.args = a, before, []  # type: list[dict[str, Any]]

    async def __call__(self, args: dict[str, Any]) -> GatewayResult:
        self.args.append(args)
        if self.before is not None:
            await self.before()
        return await self.a.w.call("outfit_plan", **args)


def _ask(plan: str, *pairs: tuple[str, str]) -> ConfirmIn:
    return ConfirmIn(plan=plan, slots=tuple(ConfirmSlot(slot=s, piece=p) for s, p in pairs))


LOOK = (("top", T.white), ("bottom", T.trousers), ("outer", T.rain_jacket),
        ("shoes", SHOES[0]), ("shoes", SHOES[1]))  # fmt: skip


async def _plan(a: AWorld) -> Any:
    pid = await a.plan()
    return (await a.styling.plans.read(UID)).plan(pid)


async def test_a_ready_look_is_one_lock_of_every_slot_at_once() -> None:
    a = await a_world()
    plan = await _plan(a)
    calls = Calls(a)
    got = await a.service.confirm(UID, _ask(plan.id, *LOOK), calls)
    assert calls.args == [{"action": "lock", "plan": plan.id,
                           "pieces": [T.white, T.trousers, T.rain_jacket, SHOES[0]]}]  # fmt: skip
    assert got.outcome is GatewayOutcome.EXECUTED and not got.result.get("refused")
    after = (await a.styling.plans.read(UID)).plan(plan.id)
    assert after.slot("outer").pieces == (T.rain_jacket,) and after.slot("outer").locked
    assert set(after.slot("shoes").pieces) == set(SHOES)


async def test_a_jacket_in_the_laundry_is_refused_in_words_before_any_tool_call() -> None:
    a = await a_world()
    plan = await _plan(a)
    await a.move(T.rain_jacket)
    calls = Calls(a)
    with pytest.raises(confirm.Draft) as got:
        await a.service.confirm(UID, _ask(plan.id, *LOOK), calls)
    assert str(got.value) == IN_LAUNDRY
    assert calls.args == []  # no outfit_plan call is made
    assert (await a.styling.plans.read(UID)).plan(plan.id) == plan


async def test_the_race_a_jacket_to_the_laundry_after_the_check_is_refused_by_the_tool() -> None:
    a = await a_world()
    plan = await _plan(a)

    async def to_the_laundry() -> None:
        await a.move(T.rain_jacket)

    calls = Calls(a, before=to_the_laundry)
    got = await a.service.confirm(UID, _ask(plan.id, *LOOK), calls)
    assert len(calls.args) == 1  # the early check passed: the tool's own check refuses it
    assert got.result["refused"] is True and got.result["message"] == LOCK_REFUSED
    assert (await a.styling.plans.read(UID)).plan(plan.id) == plan  # unchanged


async def test_one_shoe_in_the_laundry_names_the_shoe() -> None:
    a = await a_world()
    plan = await _plan(a)
    await a.move(SHOES[1])
    with pytest.raises(confirm.Draft) as got:
        await a.service.confirm(UID, _ask(plan.id, ("shoes", SHOES[0])), Calls(a))
    assert str(got.value) == (
        "The brown dress shoe is in the laundry: it can't be confirmed for this event."
    )


async def test_a_piece_another_plan_holds_is_refused_with_its_event() -> None:
    a = await a_world()
    held = await a.w.call("outfit_plan", action="save", day="tomorrow", start="18:00",
                          end="20:00", occasion="meeting")  # fmt: skip
    picks = held.result["plan"]["look"]["pieces"]
    blazer = next(p["ids"][0] for p in picks if p["slot"] == "outer")
    plan = await _plan(a)
    with pytest.raises(confirm.Draft) as got:
        await a.service.confirm(UID, _ask(plan.id, ("outer", blazer)), Calls(a))
    assert str(got.value) == (
        "The charcoal blazer is reserved for your 18:00 event: it can't be confirmed for this "
        "event."
    )


async def test_a_set_part_without_its_set_is_refused() -> None:
    a = await a_world()
    got = await a.w.call("outfit_plan", action="save", day="tomorrow", code="festive")
    await a.move(T.kurta)
    with pytest.raises(confirm.Draft) as refused:
        await a.service.confirm(UID, _ask(got.result["plan"]["id"], ("bottom", T.pyjama)), Calls(a))
    assert "worn only with its set" in str(refused.value)


@pytest.mark.parametrize("pairs", [
    (("top", "wi_ffffffffffff"),),  # not his
    (("bottom", T.white),),  # not that slot's piece
    (("top", T.white), ("top", T.striped)),  # two in a slot
])  # fmt: skip
async def test_slots_that_cant_be_a_look_are_refused_before_any_call(pairs: Any) -> None:
    a = await a_world()
    plan = await _plan(a)
    calls = Calls(a)
    with pytest.raises(confirm.BadSlots):
        await a.service.confirm(UID, _ask(plan.id, *pairs), calls)
    assert calls.args == []


async def test_a_plan_that_isnt_there_is_refused_before_any_call() -> None:
    a = await a_world()
    calls = Calls(a)
    with pytest.raises(NoLook) as got:
        await a.service.confirm(UID, _ask("op_00000bad", ("top", T.white)), calls)
    assert str(got.value) == GONE_PLAN and calls.args == []
