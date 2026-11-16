# tests/test_r13_c_refresh.py -- R13 Part C's plan refresh (docs/plans/r13-wardrobe.md D4.5, D12,
# D19; plan review H1): STY-15 (a planned white shirt dropped in the basket leaves tomorrow's look,
# a ready alternative is shown, one `outfit_changed` in fixed words; wearing the planned outfit
# sends nothing and marks nothing), the 36-hour window, once a plan per 2 hours, auto-swap, a
# private piece never named, a piece back to Ready, an observer that never raises. Fixed clocks.
from __future__ import annotations

from typing import Any

import pytest
from r13_fakes import UID
from r13_fakes_c import N, World, ist, world

from jarvis.tools.gateway import GatewayOutcome
from jarvis.wardrobe.ports import PieceChange
from jarvis.wardrobe.styling import refresh


async def ok(w: World, name: str, **args: Any) -> dict[str, Any]:
    got = await w.call(name, **args)
    assert got.outcome is GatewayOutcome.EXECUTED, (got.outcome, got.error)
    return got.result  # type: ignore[no-any-return]


async def _meeting(w: World, day: str = "tomorrow") -> dict[str, Any]:
    got = await ok(w, "outfit_plan", action="save", day=day, occasion="meeting", start="10:00",
                   end="12:00")  # fmt: skip
    return got["plan"]  # type: ignore[no-any-return]


def _ids(plan: dict[str, Any]) -> set[str]:
    return {i for p in plan["look"]["pieces"] for i in p["ids"]}


async def _plan(w: World, pid: str) -> dict[str, Any]:
    plans = (await ok(w, "outfit_plans", days=14))["plans"]
    return next(p for p in plans if p["id"] == pid)


async def test_sty15_a_planned_shirt_in_the_basket_leaves_the_look_for_a_ready_one() -> None:
    w = await world(at=ist(2026, 11, 16, 18, 0))
    plan = await _meeting(w)
    assert N.shirt_white in _ids(plan)
    await w.move(N.shirt_white, "deposited")
    now = await _plan(w, plan["id"])
    assert N.shirt_white not in _ids(now)
    top = next(p for p in now["look"]["pieces"] if p["slot"] == "top")
    assert top["ids"] == [N.shirt_lb]  # the ready alternative
    assert now["needs"] == ["needs a new top"]
    assert w.notifier.sent == [
        (
            "outfit_changed",
            "A white shirt in tomorrow's 10:00 outfit went to the laundry. A ready one is "
            "suggested in Helpers, Wardrobe.",
        )
    ]
    assert any(N.shirt_white in c and "In laundry" in c for c in now["look"]["compromises"])


async def test_sty15_wearing_the_planned_outfit_sends_nothing_and_marks_nothing() -> None:
    w = await world(at=ist(2026, 11, 17, 8, 0))
    plan = await _meeting(w, "today")
    await ok(w, "wear_log", action="start", plan=plan["id"])
    w.clock.advance(hours=5)
    await ok(w, "wear_log", action="done", plan=plan["id"])
    after = await _plan(w, plan["id"])
    assert after["needs"] == [] and after["worn"] is True
    assert w.notifier.sent == []


async def test_the_wear_rule_off_is_what_the_eval_control_breaks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(refresh, "WEAR_RULE", False)
    w = await world(at=ist(2026, 11, 17, 8, 0))
    plan = await _meeting(w, "today")
    await ok(w, "wear_log", action="start", plan=plan["id"])
    assert [k for k, _ in w.notifier.sent] == ["outfit_changed"]  # the control: a false alert


async def test_a_change_beyond_36_hours_marks_the_plan_but_sends_nothing() -> None:
    w = await world(at=ist(2026, 11, 16, 8, 0))
    plan = await _meeting(w, "2026-11-18")  # 50 hours ahead
    await w.move(N.shirt_white, "deposited")
    assert (await _plan(w, plan["id"]))["needs"] == ["needs a new top"]
    assert w.notifier.sent == []


async def test_once_a_plan_per_two_hours() -> None:
    w = await world(at=ist(2026, 11, 16, 18, 0))
    plan = await _meeting(w)
    await w.move(N.shirt_white, "deposited")
    await w.move(N.trousers, "deposited")
    assert w.notifier.kinds() == ["outfit_changed"]
    w.clock.advance(hours=2)
    await w.move(N.watch, "deposited")
    assert w.notifier.kinds() == ["outfit_changed", "outfit_changed"]
    assert {"needs a new top", "needs a new bottom", "needs a new watch"} <= set(
        (await _plan(w, plan["id"]))["needs"]
    )


async def test_a_private_piece_is_never_named_in_the_alert() -> None:
    w = await world(at=ist(2026, 11, 16, 18, 0))
    await _meeting(w)
    await w.move(N.under, "deposited")
    assert w.notifier.sent[0][1] == (
        "A private basic in tomorrow's 10:00 outfit went to the laundry. None is ready: look in "
        "Helpers, Wardrobe."
    )


async def test_auto_swap_on_takes_the_ready_substitute() -> None:
    w = await world(at=ist(2026, 11, 16, 18, 0))
    plan = await _meeting(w)
    swap = {"auto_swap": True}
    await w.styling.change(
        UID, lambda d: d.model_copy(update={"choice": d.choice.model_copy(update=swap)})
    )
    await w.move(N.shirt_white, "deposited")
    doc = await w.styling.plans.read(UID)
    stored = doc.plan(plan["id"])
    assert stored is not None and stored.slot("top").pieces == (N.shirt_lb,)  # type: ignore[union-attr]


async def test_a_piece_back_to_ready_clears_its_need() -> None:
    w = await world(at=ist(2026, 11, 16, 8, 0))
    plan = await _meeting(w, "2026-11-18")
    await w.move(N.watch, "deposited")
    assert (await _plan(w, plan["id"]))["needs"] == ["needs a new watch"]
    await w.move(N.watch, "returned")
    assert (await _plan(w, plan["id"]))["needs"] == []


async def test_a_reusable_piece_worn_today_is_no_change_for_tomorrows_plan() -> None:
    w = await world(at=ist(2026, 11, 16, 8, 0))
    plan = await _meeting(w)
    await ok(w, "wear_log", action="start", pieces=[N.watch])
    assert (await _plan(w, plan["id"]))["needs"] == []
    assert w.notifier.sent == []


async def test_a_broken_refresh_never_raises_into_the_store(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    w = await world(at=ist(2026, 11, 16, 18, 0))
    await _meeting(w)

    async def broken(uid: str) -> Any:
        raise RuntimeError("the plans can't be read")

    monkeypatch.setattr(w.styling.plans, "read", broken)
    await w.refresh.changed(PieceChange(UID, N.shirt_white, "deposited", "ready", "in_laundry"))
    await w.move(N.shirt_white, "deposited")  # the commit stands
    assert (await w.pieces())[N.shirt_white].state == "in_laundry"
    assert w.notifier.sent == []
