# tests/test_r13_c_tools.py -- R13 Part C's five tools through a real gateway (docs/plans/
# r13-wardrobe.md "Tools", D10, D12, D15, D18): `outfit_suggest`, `outfit_plans`, `outfit_plan`,
# `outfit_prefs`, `wear_log`. Acceptance checks STY-01, STY-03, STY-12, STY-13, STY-14 and STY-17 by
# tool; the model's view (fixed words and ids, a private piece "a private basic"), at most 20
# pieces a result, the trust rule, the risks and Activity's fixed words. Fixed clocks only.
from __future__ import annotations

from typing import Any

import pytest
from r13_fakes_c import SHOES, N, World, ist, world

from jarvis.core.guardrails import ActionRisk
from jarvis.tools.gateway import GatewayOutcome

R1, R2 = ActionRisk.READ_ONLY, ActionRisk.REVERSIBLE


async def ok(w: World, name: str, **args: Any) -> dict[str, Any]:
    got = await w.call(name, **args)
    assert got.outcome is GatewayOutcome.EXECUTED, (got.outcome, got.error)
    assert isinstance(got.result, dict)
    return got.result


def _ids(look: dict[str, Any]) -> list[str]:
    return [i for p in look["pieces"] for i in p["ids"]]


async def _plan(w: World, **args: Any) -> str:
    got = await ok(w, "outfit_plan", action="save", **args)
    return str(got["plan"]["id"])


# ---- the tools themselves ----------------------------------------------------------------------
async def test_five_tools_with_their_risks_rows_flags_and_fixed_activity_words() -> None:
    w = await world()
    by = {t.name: t for t in w.part.tools}
    assert set(by) == {"outfit_suggest", "outfit_plans", "outfit_plan", "outfit_prefs", "wear_log"}
    assert [by[n].risk for n in ("outfit_suggest", "outfit_plans")] == [R1, R1]
    assert [by[n].risk for n in ("outfit_plan", "outfit_prefs", "wear_log")] == [R2, R2, R2]
    assert by["wear_log"].spoken_ok and not by["outfit_plan"].spoken_ok
    assert all(not t.trusted_output and t.activity_words for t in by.values())
    assert by["outfit_suggest"].may_vouch and by["outfit_plans"].may_vouch


async def test_off_without_a_key_says_so_and_writes_nothing() -> None:
    w = await world(keyring=None)
    got = await ok(w, "outfit_plan", action="save", day="tomorrow")
    assert got["refused"] is True and "token key" in got["message"]
    assert not [p for p in w.docs._data if "wardrobe_plans" in p]  # noqa: SLF001


# ---- STY-01 "tomorrow" in his zone ---------------------------------------------------------------
@pytest.mark.parametrize(
    ("at", "words"),
    [
        (ist(2026, 11, 16, 23, 30), "Tomorrow, Tuesday 17 November"),
        (ist(2026, 11, 17, 0, 30), "Tomorrow, Wednesday 18 November"),
    ],
)
async def test_sty01_what_to_wear_tomorrow_is_the_next_local_day_with_its_occasion(
    at: Any, words: str
) -> None:
    w = await world(at=at, place=False)
    got = await ok(w, "outfit_suggest", day="tomorrow")
    assert got["message"] == (
        f"{words}: casual, no event planned. Weather unknown: I assumed indoors. Wear: a navy "
        "shirt, blue jeans, a pair of white sneakers, a pair of grey socks, a grey watch and a "
        "private basic."
    )
    assert got["looks"][0]["occasion"] == "no event planned"


async def test_sty01_a_planned_meeting_is_what_tomorrow_answers_with() -> None:
    w = await world(at=ist(2026, 11, 16, 21, 0), place=False)
    await _plan(w, day="tomorrow", occasion="client meeting", start="10:00", end="12:00")
    got = await ok(w, "outfit_suggest", day="tomorrow")
    look = got["looks"][0]
    assert look["occasion"] == "your 10:00 event (a meeting)"
    assert look["code"] == "business_formal"
    assert got["message"].startswith(
        "Tomorrow, Tuesday 17 November: business formal for your 10:00 event (a meeting)."
    )


# ---- the model's view, sizes and trust -----------------------------------------------------------
async def test_a_result_shows_fixed_words_and_ids_never_his_label_and_vouches() -> None:
    w = await world(at=ist(2026, 11, 16, 20, 0))
    got = await w.call("outfit_suggest", day="tomorrow", occasion="meeting")
    assert got.outcome is GatewayOutcome.EXECUTED and got.trusted is True
    text = str(got.result)
    for label in ("Light blue office shirt", "White formal shirt", "Charcoal trousers", "Brown"):
        assert label not in text
    under = next(p for p in got.result["looks"][0]["pieces"] if p["slot"] == "underwear")
    assert under == {"slot": "underwear", "ids": [N.under], "words": "a private basic"}
    count = sum(len(_ids(x)) for x in (*got.result["looks"], *got.result["alternatives"]))
    assert count <= 20


async def test_outfit_plans_lists_the_plans_ahead_with_their_looks() -> None:
    w = await world(at=ist(2026, 11, 16, 20, 0))
    first = await _plan(w, day="tomorrow", occasion="meeting", start="10:00", end="12:00")
    second = await _plan(w, day="2026-11-20", occasion="Diwali")
    got = await ok(w, "outfit_plans")
    assert [p["id"] for p in got["plans"]] == [first, second]
    assert got["plans"][1]["code"] == "festive"
    assert sum(len(_ids(p["look"])) for p in got["plans"]) <= 20


# ---- STY-03 the dress code is his; the calendar is never written --------------------------------
async def test_sty03_changing_catch_up_to_business_formal_gives_a_business_formal_look() -> None:
    w = await world(at=ist(2026, 11, 16, 20, 0))
    plan = await _plan(w, day="tomorrow", occasion="Catch-up", start="16:00", end="17:00")
    before = await ok(w, "outfit_plans")
    assert before["plans"][0]["code"] == "smart_casual" and before["plans"][0]["tentative"]
    await ok(w, "outfit_prefs", action="code", plan=plan, code="business_formal")
    after = (await ok(w, "outfit_plans"))["plans"][0]
    assert after["code"] == "business_formal" and after["tentative"] is False
    top = next(p for p in after["look"]["pieces"] if p["slot"] == "top")
    assert top["ids"] in ([N.shirt_white], [N.shirt_lb])
    assert all(method == "GET" for method, _, _ in w.google.calls)  # nothing written to Google


# ---- STY-12 change one; STY-14 reservations ------------------------------------------------------
async def test_sty12_changing_the_shoes_keeps_shirt_trousers_and_watch() -> None:
    w = await world(at=ist(2026, 11, 16, 20, 0))
    await w.edit(N.snk_l, formality=4)
    await w.edit(N.snk_r, formality=4)
    plan = await _plan(w, day="tomorrow", code="business_casual")
    before = {
        p["slot"]: p["ids"] for p in (await ok(w, "outfit_plans"))["plans"][0]["look"]["pieces"]
    }
    got = await ok(w, "outfit_plan", action="change", plan=plan, slot="shoes")
    after = {p["slot"]: p["ids"] for p in got["plan"]["look"]["pieces"]}
    assert after["shoes"] != before["shoes"]
    for slot in ("top", "bottom", "watch"):
        assert after[slot] == before[slot], slot


async def test_sty14_reserved_shoes_appear_for_their_event_and_conflict_for_a_second_plan() -> None:
    w = await world(at=ist(2026, 11, 16, 20, 0))
    first = await _plan(w, day="tomorrow", occasion="meeting", start="10:00", end="12:00")
    plans = (await ok(w, "outfit_plans"))["plans"]
    shoes = next(p["ids"] for p in plans[0]["look"]["pieces"] if p["slot"] == "shoes")
    assert shoes == list(SHOES)
    second = await _plan(w, day="tomorrow", occasion="board review", start="11:00", end="13:00")
    look = (await ok(w, "outfit_plans"))["plans"][1]["look"]
    assert N.shoe_l not in _ids(look)
    assert any("reserved for your 10:00 event" in g for g in look["gaps"])
    got = await ok(w, "outfit_plan", action="reserve", plan=second, piece=N.shoe_l)
    assert got["refused"] is True
    assert got["message"] == (
        f"{N.shoe_l} is reserved for your 10:00 event: transfer it, or pick another."
    )
    moved = await ok(
        w, "outfit_plan", action="transfer", plan=second, from_plan=first, piece=N.shoe_l
    )
    assert N.shoe_l in _ids(moved["plan"]["look"])
    left = (await ok(w, "outfit_plans"))["plans"][0]
    assert N.shoe_l not in _ids(left["look"])


# ---- STY-13 two plans, a declared shared base, "I'm wearing it" ----------------------------------
async def test_sty13_a_meeting_and_an_evening_function_share_a_declared_base() -> None:
    w = await world(at=ist(2026, 11, 17, 8, 0))
    meeting = await _plan(w, day="today", occasion="meeting", start="10:00", end="12:00")
    evening = await _plan(w, day="today", occasion="dinner", start="19:00", end="22:00")
    base = [N.trousers, N.watch]
    got = await ok(w, "outfit_plan", action="share", plan=evening, from_plan=meeting, pieces=base)
    look = got["plan"]["look"]
    assert {N.trousers, N.watch} <= set(_ids(look))
    assert any(
        r.startswith("Reused from your 10:00 event:") and N.trousers in r for r in look["reasons"]
    )
    assert any(r.startswith("Change for this one:") for r in look["reasons"])
    refused = await ok(
        w, "outfit_plan", action="share", plan=evening, from_plan=meeting, pieces=[N.shirt_white]
    )
    assert refused["refused"] is True and "goes to the laundry after a wear" in refused["message"]
    await ok(w, "wear_log", action="start", plan=meeting)  # "I'm wearing it"
    pieces = await w.pieces()
    assert pieces[N.trousers].state == "in_use" and pieces[N.trousers].wear == meeting
    after = (await ok(w, "outfit_plans", day="today"))["plans"]
    evening_now = next(p for p in after if p["id"] == evening)
    assert {N.trousers, N.watch} <= set(_ids(evening_now["look"]))
    assert not evening_now["needs"]
    assert w.notifier.sent == []  # wearing never alerts


# ---- STY-17 one wear -----------------------------------------------------------------------------
async def test_sty17_saving_a_plan_changes_no_wear_count_and_start_then_done_is_one_wear() -> None:
    w = await world(at=ist(2026, 11, 17, 8, 0))
    plan = await _plan(w, day="today", occasion="meeting", start="10:00", end="12:00")
    await ok(w, "outfit_suggest", day="today")
    assert {p.wears for p in (await w.pieces()).values()} == {0}
    started = await ok(w, "wear_log", action="start", plan=plan)
    worn = started["pieces"]
    assert N.shirt_white in worn and N.trousers in worn
    w.clock.advance(hours=10)
    done = await ok(w, "wear_log", action="done")  # "done for today": everything in use
    pieces = await w.pieces()
    assert done["message"] == f"Done for today: {len(worn)} pieces, one wear each."
    assert all(pieces[p].wears == 1 for p in worn)
    assert pieces[N.shirt_white].state == "in_laundry"  # the rewear rule
    assert pieces[N.trousers].state == "ready"


async def test_wear_by_his_words_names_one_piece_or_asks_which() -> None:
    w = await world(at=ist(2026, 11, 17, 8, 0))
    got = await ok(w, "wear_log", action="start", query="the light blue shirt")
    assert got["pieces"] == [N.shirt_lb]
    unsure = await ok(w, "wear_log", action="start", query="my black socks and a shirt")
    assert unsure["refused"] is True and unsure["message"].startswith("Which one")
    assert (await w.pieces())[N.shirt_white].state == "ready"  # never a guess
    vest = await ok(w, "wear_log", action="start", query="my vest")
    assert vest["refused"] is True and N.vest1 in vest["message"] and N.vest2 in vest["message"]
    assert "a private basic" in vest["message"]


async def test_a_wear_card_says_fixed_words_through_the_preview() -> None:
    w = await world(at=ist(2026, 11, 17, 8, 0))
    tool = next(t for t in w.part.tools if t.name == "wear_log")
    assert tool.preview is not None
    from jarvis.tools.context import tool_context

    with tool_context("owner-w:s"):
        card = await tool.preview({"action": "start", "pieces": [N.shirt_lb, N.under]})
    assert card.summary == "Log a wear: a light blue shirt and a private basic."


async def test_wearing_a_plan_whose_shirt_went_to_the_basket_wears_the_substitute() -> None:
    w = await world(at=ist(2026, 11, 17, 7, 0))
    plan = await _plan(w, day="today", occasion="meeting", start="10:00", end="12:00")
    await w.move(N.shirt_white, "deposited")
    w.notifier.sent.clear()
    got = await ok(w, "wear_log", action="start", plan=plan)
    assert N.shirt_lb in got["pieces"] and N.shirt_white not in got["pieces"]
    pieces = await w.pieces()
    assert pieces[N.shirt_lb].state == "in_use" and pieces[N.shirt_lb].wear == plan
    assert w.notifier.sent == []  # the substitute worn for its own plan: no change
