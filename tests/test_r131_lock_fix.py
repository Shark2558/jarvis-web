# tests/test_r131_lock_fix.py -- the R13 fix shipped in R13.1 (docs/plans/r13-1-try-on.md D20; plan
# review H2): R13's `outfit_plan` refuses a piece that isn't ready. `lock` and `reserve` check every
# piece of the unit by the engine's own rule (only Ready; a pair whole; a set part that can't be
# worn alone only with its whole set; an In-use piece only through the plan's declared shared base)
# and write nothing when one fails; `lock` takes `pieces`, one a slot, all in ONE change or none.
# Written first and run red: before the fix, the laundry blazer was locked into the plan.
from __future__ import annotations

from typing import Any

import pytest
from r13_fakes import UID
from r13_fakes_c import SHOES, N, World, ist, world

from jarvis.tools.gateway import GatewayOutcome

IN_LAUNDRY = "The charcoal blazer is in the laundry: it can't be locked into this plan."


async def ok(w: World, name: str, **args: Any) -> dict[str, Any]:
    got = await w.call(name, **args)
    assert got.outcome is GatewayOutcome.EXECUTED, (got.outcome, got.error)
    return got.result  # type: ignore[no-any-return]


async def _plan(w: World) -> str:
    got = await ok(w, "outfit_plan", action="save", day="tomorrow", occasion="meeting")
    return str(got["plan"]["id"])


def _slot(plan: dict[str, Any], slot: str) -> list[str]:
    return next((p["ids"] for p in plan["look"]["pieces"] if p["slot"] == slot), [])


async def _stored(w: World) -> Any:
    return await w.styling.plans.read(UID)


@pytest.mark.parametrize("action", ["lock", "reserve"])
async def test_a_piece_in_the_laundry_is_refused_and_the_plan_is_unchanged(action: str) -> None:
    w = await world(at=ist(2026, 11, 16, 20, 0))
    pid = await _plan(w)
    await w.move(N.blazer, "deposited")  # the blazer goes to the laundry
    before = await _stored(w)
    got = await ok(w, "outfit_plan", action=action, plan=pid, piece=N.blazer)
    assert got["refused"] is True and got["message"] == IN_LAUNDRY
    assert await _stored(w) == before  # nothing written


async def test_a_ready_piece_still_locks_and_reserves() -> None:
    w = await world(at=ist(2026, 11, 16, 20, 0))
    pid = await _plan(w)
    locked = await ok(w, "outfit_plan", action="lock", plan=pid, piece=N.blazer)
    assert _slot(locked["plan"], "outer") == [N.blazer]
    held = await ok(w, "outfit_plan", action="reserve", plan=pid, piece=N.watch)
    assert _slot(held["plan"], "watch") == [N.watch]


async def test_a_pair_with_one_side_in_the_laundry_is_refused() -> None:
    w = await world(at=ist(2026, 11, 16, 20, 0))
    pid = await _plan(w)
    await w.move(SHOES[1], "deposited")
    got = await ok(w, "outfit_plan", action="lock", plan=pid, piece=SHOES[0])
    assert got["refused"] is True and "can't be locked into this plan" in got["message"]


async def test_a_set_part_that_cant_be_worn_alone_needs_its_whole_set() -> None:
    w = await world(at=ist(2026, 11, 16, 20, 0))
    got = await ok(w, "outfit_plan", action="save", day="tomorrow", code="festive")
    pid = got["plan"]["id"]
    await w.move(N.kurta, "deposited")  # the pyjama can't be worn without its kurta
    refused = await ok(w, "outfit_plan", action="lock", plan=pid, piece=N.pyjama)
    assert refused["refused"] is True and "set" in refused["message"]


async def test_lock_takes_every_slot_at_once_in_one_change(monkeypatch: pytest.MonkeyPatch) -> None:
    w = await world(at=ist(2026, 11, 16, 20, 0))
    pid = await _plan(w)
    writes: list[int] = []
    real = w.styling.change

    async def counted(uid: str, fn: Any) -> Any:
        writes.append(1)
        return await real(uid, fn)

    monkeypatch.setattr(w.styling, "change", counted)
    got = await ok(w, "outfit_plan", action="lock", plan=pid,
                   pieces=[N.shirt_white, N.trousers, N.blazer, SHOES[0]])  # fmt: skip
    assert writes == [1]  # ONE change of wardrobe_plans
    plan = got["plan"]
    assert _slot(plan, "top") == [N.shirt_white] and _slot(plan, "bottom") == [N.trousers]
    assert _slot(plan, "outer") == [N.blazer] and set(_slot(plan, "shoes")) == set(SHOES)
    stored = (await _stored(w)).plan(pid)
    assert all(stored.slot(s).locked for s in ("top", "bottom", "outer", "shoes"))


async def test_lock_with_pieces_is_all_or_nothing() -> None:
    w = await world(at=ist(2026, 11, 16, 20, 0))
    pid = await _plan(w)
    await w.move(N.blazer, "deposited")
    before = await _stored(w)
    got = await ok(w, "outfit_plan", action="lock", plan=pid,
                   pieces=[N.shirt_white, N.trousers, N.blazer])  # fmt: skip
    assert got["refused"] is True and got["message"] == IN_LAUNDRY
    assert await _stored(w) == before  # the shirt and trousers were not locked either


async def test_lock_with_pieces_refuses_two_for_one_slot_and_a_stranger() -> None:
    w = await world(at=ist(2026, 11, 16, 20, 0))
    pid = await _plan(w)
    before = await _stored(w)
    two = await ok(w, "outfit_plan", action="lock", plan=pid, pieces=[N.shirt_white, N.tee])
    assert two["refused"] is True and two["message"] == "One piece a slot: top has two."
    gone = await ok(w, "outfit_plan", action="lock", plan=pid, pieces=["wi_ffffffffffff"])
    assert gone["refused"] is True
    assert await _stored(w) == before


async def test_a_piece_another_plan_holds_is_still_refused_with_pieces() -> None:
    w = await world(at=ist(2026, 11, 16, 20, 0))
    first = await _plan(w)
    await ok(w, "outfit_plan", action="lock", plan=first, piece=N.blazer)
    other = await ok(w, "outfit_plan", action="save", day="tomorrow", start="18:00", end="20:00")
    got = await ok(w, "outfit_plan", action="lock", plan=other["plan"]["id"], pieces=[N.blazer])
    assert got["refused"] is True and "reserved for" in got["message"]
