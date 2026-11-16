# tests/test_r13_c_wear.py -- R13 Part C's `wear_log` in his own words (docs/plans/r13-wardrobe.md
# D3, D4.1, D20; plan review H1; code review 1 H1, M3, M6, L4; security review 1 L8): a planned
# piece worn by its name is a wear FOR that plan (no false `outfit_changed`), "the meeting outfit"
# is today's plan, "done" for a plan covers the substitute he wore, "I wore ... today / yesterday"
# after the fact is one wear at the stated day, the ledger's verdict is said. Fixed IST clocks.
from __future__ import annotations

from typing import Any

from r13_fakes import UID
from r13_fakes_c import N, World, ist, world

from jarvis.tools.gateway import GatewayOutcome


async def ok(w: World, name: str, **args: Any) -> dict[str, Any]:
    got = await w.call(name, **args)
    assert got.outcome is GatewayOutcome.EXECUTED, (got.outcome, got.error)
    assert isinstance(got.result, dict)
    return got.result


async def _meeting(w: World, day: str = "today") -> dict[str, Any]:
    got = await ok(w, "outfit_plan", action="save", day=day, occasion="meeting", start="10:00",
                   end="12:00")  # fmt: skip
    return got["plan"]  # type: ignore[no-any-return]


def _ids(plan: dict[str, Any]) -> list[str]:
    return [i for p in plan["look"]["pieces"] for i in p["ids"]]


async def _stored(w: World, pid: str) -> Any:
    return (await w.styling.plans.read(UID)).plan(pid)


# ---- code review H1: a planned piece by its name; "the meeting outfit" -------------------------
async def test_wearing_a_planned_shirt_by_its_name_is_a_wear_for_that_plan() -> None:
    w = await world(at=ist(2026, 11, 17, 8, 0))
    plan = await _meeting(w)
    assert N.shirt_white in _ids(plan)
    w.notifier.sent.clear()
    got = await ok(w, "wear_log", action="start", query="the white shirt")
    assert got["pieces"] == [N.shirt_white]
    assert (await w.pieces())[N.shirt_white].wear == plan["id"]
    stored = await _stored(w, plan["id"])
    assert stored.worn is True and stored.needs == ()
    assert w.notifier.sent == []  # no false outfit_changed


async def test_wearing_the_meeting_outfit_wears_todays_plan_as_it_is_now() -> None:
    w = await world(at=ist(2026, 11, 17, 8, 0))
    plan = await _meeting(w)
    w.notifier.sent.clear()
    got = await ok(w, "wear_log", action="start", query="the meeting outfit")
    assert sorted(got["pieces"]) == sorted(_ids(plan))
    pieces = await w.pieces()
    assert all(pieces[i].state == "in_use" and pieces[i].wear == plan["id"] for i in _ids(plan))
    assert (await _stored(w, plan["id"])).worn is True
    assert w.notifier.sent == []


async def test_the_outfit_with_no_plan_today_asks_for_the_pieces() -> None:
    w = await world(at=ist(2026, 11, 17, 8, 0))
    got = await ok(w, "wear_log", action="start", query="the meeting outfit")
    assert got == {
        "refused": True,
        "message": "You have no outfit planned for today: say which pieces you are wearing.",
    }
    assert {p.state for p in (await w.pieces()).values()} == {"ready"}
