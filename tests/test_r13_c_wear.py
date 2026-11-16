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


# ---- code review M3: "done" for a plan covers the substitute he wore -----------------------------
async def test_done_for_a_plan_closes_the_substitute_he_actually_wore() -> None:
    w = await world(at=ist(2026, 11, 17, 7, 0))
    plan = await _meeting(w)
    await w.move(N.shirt_white, "deposited")  # auto-swap off: the stored pick stays the white one
    started = await ok(w, "wear_log", action="start", plan=plan["id"])
    assert N.shirt_lb in started["pieces"]
    w.clock.set(ist(2026, 11, 17, 19, 0))
    done = await ok(w, "wear_log", action="done", plan=plan["id"])
    assert N.shirt_lb in done["pieces"] and N.shirt_white not in done["pieces"]
    lb = (await w.pieces())[N.shirt_lb]
    assert (lb.state, lb.wears) == ("in_laundry", 1)


# ---- code review M6: "I wore ... today / yesterday" after the fact -------------------------------
async def _wear_at(w: World, pid: str) -> list[Any]:
    return [h.event for h in await w.store.history(UID, pid) if h.event.kind.startswith("wear_")]


async def test_i_wore_the_light_blue_shirt_today_is_one_wear_after_the_fact() -> None:
    w = await world(at=ist(2026, 11, 17, 20, 0))
    got = await ok(w, "wear_log", action="done", query="the light blue shirt")
    assert got["message"] == "Noted: a light blue shirt, worn today: one wear."
    lb = (await w.pieces())[N.shirt_lb]
    assert (lb.state, lb.wears) == ("in_laundry", 1)
    assert [e.at for e in await _wear_at(w, N.shirt_lb)] == [ist(2026, 11, 17, 12, 0)] * 2


async def test_today_before_noon_is_now_never_ahead() -> None:
    w = await world(at=ist(2026, 11, 17, 9, 30))
    await ok(w, "wear_log", action="done", pieces=[N.trousers], day="today")
    assert [e.at for e in await _wear_at(w, N.trousers)] == [ist(2026, 11, 17, 9, 30)] * 2


async def test_yesterday_at_00_30_ist_is_his_local_yesterday_and_its_plan() -> None:
    w = await world(at=ist(2026, 11, 17, 0, 30))  # 16 Nov 19:00 UTC
    plan = await ok(w, "outfit_plan", action="save", day="2026-11-16", occasion="meeting")
    assert N.shirt_white in _ids(plan["plan"])
    got = await ok(w, "wear_log", action="done", query="the white shirt", day="yesterday")
    assert got["message"] == "Noted: a white shirt, worn yesterday: one wear."
    events = await _wear_at(w, N.shirt_white)
    assert [(e.kind, e.at, e.plan) for e in events] == [
        ("wear_started", ist(2026, 11, 16, 12, 0), plan["plan"]["id"]),
        ("wear_done", ist(2026, 11, 16, 12, 0), plan["plan"]["id"]),
    ]
    assert (await w.pieces())[N.shirt_white].wears == 1


async def test_a_stated_day_is_at_most_30_days_back_never_ahead_and_a_start_is_now() -> None:
    w = await world(at=ist(2026, 11, 17, 20, 0))
    for day in ("2026-10-17", "2026-11-18", "last week"):
        got = await ok(w, "wear_log", action="done", pieces=[N.tee], day=day)
        assert got == {
            "refused": True,
            "message": "A wear's day is today, yesterday or a date up to 30 days back.",
        }, day
    start = await ok(w, "wear_log", action="start", pieces=[N.tee], day="yesterday")
    assert start == {
        "refused": True,
        "message": "A wear starts now: for an earlier day, say you wore it.",
    }
    assert (await w.pieces())[N.tee].wears == 0


# ---- security review L8: the ledger's verdict is said --------------------------------------------
async def test_the_ledgers_refusal_reaches_him_in_its_words(monkeypatch: Any) -> None:
    from jarvis.wardrobe.ports import Refused

    w = await world(at=ist(2026, 11, 17, 8, 0))

    async def refuse(uid: str, fn: Any) -> Any:
        raise Refused("A time can be at most 30 days back and never ahead.")

    monkeypatch.setattr(w.store, "transact", refuse)
    got = await ok(w, "wear_log", action="start", pieces=[N.tee])
    assert got == {
        "refused": True,
        "message": "A time can be at most 30 days back and never ahead.",
    }


async def test_a_start_the_ledger_takes_as_a_duplicate_is_said_as_already_noted(
    monkeypatch: Any,
) -> None:
    import dataclasses

    w = await world(at=ist(2026, 11, 17, 8, 0))
    real = w.store.transact

    async def duplicate(uid: str, fn: Any) -> Any:
        got = await real(uid, fn)
        return dataclasses.replace(got, marks=dict.fromkeys(got.marks, "duplicate"))

    monkeypatch.setattr(w.store, "transact", duplicate)
    again = await ok(w, "wear_log", action="start", pieces=[N.tee])
    assert again["message"] == "Already noted: you're wearing a grey T-shirt."


# ---- code review L4: the forgotten wear's fixed client id ----------------------------------------
async def test_two_sweeps_from_one_view_close_a_forgotten_wear_once() -> None:
    from jarvis.wardrobe.styling import wear
    from jarvis.wardrobe.styling.rules import load_rules

    w = await world(at=ist(2026, 11, 16, 9, 0))
    await ok(w, "wear_log", action="start", pieces=[N.shirt_lb])
    w.clock.set(ist(2026, 11, 17, 4, 0))
    zone, rules = await w.ctx.zone(UID), load_rules()
    first = await wear.closing_events(w.store, UID, now=w.clock(), zone=zone, close="04:00",
                                      rules=rules)  # fmt: skip
    second = await wear.closing_events(w.store, UID, now=w.clock(), zone=zone, close="04:00",
                                       rules=rules)  # fmt: skip
    assert [e.client_id for e in first] == [e.client_id for e in second]
    await wear.commit(w.store, UID, first)
    await wear.commit(w.store, UID, second)
    lb = (await w.pieces())[N.shirt_lb]
    assert (lb.state, lb.wears) == ("in_laundry", 1)
