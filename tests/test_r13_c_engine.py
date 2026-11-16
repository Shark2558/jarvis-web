# tests/test_r13_c_engine.py -- R13 Part C (docs/plans/r13-wardrobe.md D12): the pure engine and the
# rules file. Hard exclusions first (state, holds, reservations, his "never" rules), required slots,
# ranking (dress code, weather, colour, recent wear), ties by piece id, a primary look and up to two
# alternatives, each with reasons naming the actual piece ids, its compromises and any gap with a
# next action. Acceptance checks STY-04 to STY-12, STY-16 and LND-16 at the engine; fixed clocks.
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest
from r13_fakes_c import BLACK_SOCKS, KURTA_SET, SHOES, SNEAKERS, UID, N, World, ist, world

from jarvis.wardrobe.styling import engine
from jarvis.wardrobe.styling.engine import Ask, suggest
from jarvis.wardrobe.styling.rules import RulesError, load_rules

RULES = load_rules()
TUE = date(2026, 11, 17)


async def _w() -> World:
    return await world(at=ist(2026, 11, 16, 20, 0))


async def _look(w: World, ask: Ask) -> engine.Suggestion:
    return suggest(await w.store.view(UID), ask, RULES)


def _ids(look: engine.LookOut) -> set[str]:
    return {pid for p in look.picks for pid in p.pieces}


# ---- the rules file --------------------------------------------------------------------------
def test_the_rules_file_is_checked_at_start(tmp_path: Path) -> None:
    raw = json.loads((Path(engine.__file__).parent / "rules.json").read_text(encoding="utf-8"))
    raw["slots"]["top"] = [*raw["slots"]["top"], "cape"]  # not a type on the fixed list
    bad = tmp_path / "rules.json"
    bad.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(RulesError):
        load_rules(bad)
    raw = json.loads((Path(engine.__file__).parent / "rules.json").read_text(encoding="utf-8"))
    raw["events"]["meeting"]["code"] = "black_tie"  # an unknown dress code
    bad.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(RulesError):
        load_rules(bad)


def test_the_rewear_rule_is_the_owners_default() -> None:
    from r13_fakes import PILOT

    by = {p.type: RULES.after_wear(p) for p in PILOT}
    for t in ("trousers", "jeans", "jacket", "blazer", "belt", "dress_shoe", "sneaker", "watch"):
        assert by[t] == "ready", t
    for t in ("shirt", "t_shirt", "vest", "underpants", "sock"):
        assert by[t] == "in_laundry", t


def test_holi_is_matched_as_a_word_never_inside_holiday() -> None:
    assert RULES.occasion_of("Holi at the society lawn") == "holi"
    assert RULES.occasion_of("Holiday planning call") is None
    assert RULES.occasion_of("Quarterly REVIEW with the board") == "meeting"
    assert RULES.occasion_of("Diwali dinner") == "festival"  # festival before function


# ---- STY-04, STY-09, STY-11 ------------------------------------------------------------------
async def test_sty04_the_meeting_look_is_the_light_blue_shirt_charcoal_trousers_and_the_rest() -> (
    None
):
    w = await _w()
    await w.move(N.shirt_white, "deposited")  # the white one is in the basket
    s = await _look(w, Ask(day=TUE, code="business_formal", occasion="meeting"))
    look = s.primary
    assert look.pick("top").pieces == (N.shirt_lb,)
    assert look.pick("bottom").pieces == (N.trousers,)
    assert look.pick("shoes").pieces == SHOES
    assert look.pick("belt").pieces == (N.brown_belt,)  # matches the brown shoes
    assert look.pick("watch").pieces == (N.watch,)
    assert look.pick("socks").pieces == BLACK_SOCKS
    assert not look.gaps


async def test_sty09_the_meeting_look_lists_shoes_belt_watch_and_the_private_basics() -> None:
    w = await _w()
    look = (await _look(w, Ask(day=TUE, code="business_formal"))).primary
    slots = [p.slot for p in look.picks]
    for slot in ("shoes", "belt", "watch", "underwear", "base"):
        assert slot in slots, slot
    assert look.pick("underwear").pieces == (N.under,)
    assert look.pick("base").pieces == (N.vest1,)  # identical copies: the lower id
    private = [r for r in look.reasons if N.under in r]
    assert private and all("a private basic" in r for r in private)  # never his words or colour


async def test_sty11_every_look_explains_why_and_names_its_piece_ids() -> None:
    w = await _w()
    s = await _look(w, Ask(day=TUE, code="smart_casual"))
    assert s.alternatives, "up to two alternatives"
    assert len(s.alternatives) <= 2
    for look in (s.primary, *s.alternatives):
        text = " ".join(look.reasons)
        assert look.reasons[0].startswith("Smart casual")
        for pid in _ids(look):
            assert pid in text, pid
    assert {p.pieces for p in s.primary.picks} != {p.pieces for p in s.alternatives[0].picks}


async def test_ties_are_broken_by_piece_id_and_the_engine_is_deterministic() -> None:
    w = await _w()
    view = await w.store.view(UID)
    a = suggest(view, Ask(day=TUE, code="casual"), RULES)
    b = suggest(view, Ask(day=TUE, code="casual"), RULES)
    assert a == b


# ---- STY-05 Diwali, STY-06 Holi --------------------------------------------------------------
async def test_sty05_a_diwali_look_uses_the_festive_set_and_checks_every_part() -> None:
    w = await _w()
    look = (await _look(w, Ask(day=TUE, code="festive", occasion="festival"))).primary
    assert look.pick("top").pieces == (N.kurta,)
    assert look.pick("bottom").pieces == (N.pyjama,)
    assert any(KURTA_SET in r and N.kurta in r and N.pyjama in r for r in look.reasons)


async def test_sty05_a_set_with_a_part_in_the_laundry_is_not_worn_whole() -> None:
    w = await _w()
    await w.move(N.pyjama, "deposited")
    look = (await _look(w, Ask(day=TUE, code="festive", occasion="festival"))).primary
    assert look.pick("top").pieces == (N.kurta,)  # "can be worn alone"
    assert N.pyjama not in _ids(look)
    assert any(KURTA_SET in c and N.pyjama in c and "In laundry" in c for c in look.compromises)


async def test_sty06_holi_takes_only_okay_to_stain_pieces_never_a_delicate_one() -> None:
    w = await _w()
    await w.edit(N.blazer, mess_ok=True)  # okay to stain, but delicate: still out
    await w.edit(N.shirt_navy, mess_ok=True)  # his favourite, excluded from Holi below
    ask = Ask(day=TUE, code="mess_tolerant", occasion="holi", excluded=frozenset({N.shirt_navy}))
    s = await _look(w, ask)
    for look in (s.primary, *s.alternatives):
        ids = _ids(look)
        assert N.blazer not in ids and N.shirt_navy not in ids
        assert ids - {N.under} <= {N.tee, N.shorts}
    assert s.primary.pick("top").pieces == (N.tee,)
    assert s.primary.pick("bottom").pieces == (N.shorts,)


# ---- STY-07 the weather ------------------------------------------------------------------------
async def test_sty07_rain_outdoors_takes_the_rain_ok_shoes_and_outer_layer() -> None:
    w = await _w()
    look = (await _look(w, Ask(day=TUE, code="casual", rain=True, outdoor=True))).primary
    assert look.pick("shoes").pieces == SNEAKERS
    assert look.pick("outer").pieces == (N.rain_jacket,)


async def test_no_rain_leaves_the_outer_layer_to_the_dress_code() -> None:
    w = await _w()
    look = (await _look(w, Ask(day=TUE, code="casual", rain=False, hot=True))).primary
    assert look.pick("outer") is None


# ---- STY-08 his "never" rules -------------------------------------------------------------------
async def test_sty08_no_tight_collars_filters_and_names_the_rule_that_leaves_nothing() -> None:
    w = await _w()
    for pid in (N.shirt_lb, N.shirt_white):
        await w.edit(pid, features={"neck": "tight"})
    never = (("neck", "tight"),)
    casual = (await _look(w, Ask(day=TUE, code="smart_casual", never=never))).primary
    assert casual.pick("top").pieces in ((N.shirt_navy,), (N.tee,))
    formal = (await _look(w, Ask(day=TUE, code="business_formal", never=never))).primary
    assert formal.pick("top") is None
    gap = next(g for g in formal.gaps if g.startswith("No top"))
    assert "never tight at the neck" in gap and N.shirt_lb in gap and N.shirt_white in gap


# ---- STY-10, STY-16, LND-16 availability --------------------------------------------------------
async def test_sty10_a_dirty_belt_or_a_pair_missing_a_shoe_is_never_suggested() -> None:
    w = await _w()
    await w.move(N.brown_belt, "deposited")
    await w.move(N.belt, "deposited")
    await w.move(N.shoe_r, "deposited")
    s = await _look(w, Ask(day=TUE, code="business_formal"))
    pieces = await w.pieces()
    for look in (s.primary, *s.alternatives):
        for pid in _ids(look):
            assert pieces[pid].state == "ready", pid
        assert N.shoe_l not in _ids(look) and N.belt not in _ids(look)


async def test_sty16_no_ready_formal_shoes_is_said_with_the_eligible_pieces_apart() -> None:
    w = await _w()
    for pid in SHOES:
        await w.move(pid, "deposited")
    look = (await _look(w, Ask(day=TUE, code="business_formal"))).primary
    gap = next(g for g in look.gaps if "shoes" in g)
    assert gap.startswith("No ready formal shoes")
    assert N.shoe_l in gap and N.shoe_r in gap and "In laundry" in gap
    assert look.pick("top") is not None and look.pick("bottom") is not None  # the rest stands
    assert look.pick("shoes") is None


async def test_lnd16_a_shirt_due_back_tomorrow_is_outstanding_beside_a_ready_one() -> None:
    w = await _w()
    await w.move(N.shirt_white, "sent_out")
    await w.edit(N.shirt_white, expected_back=TUE)  # A's view shows the latest sent_out's due
    look = (await _look(w, Ask(day=TUE, code="business_formal", occasion="meeting"))).primary
    assert look.pick("top").pieces == (N.shirt_lb,)
    line = next(g for g in look.gaps if N.shirt_white in g)
    assert line == (
        f"Outstanding: collect a white shirt ({N.shirt_white}) from the laundry shop, due back "
        "Tuesday 17 November."
    )


# ---- STY-12 change one slot; reservations; the hand-off -----------------------------------------
async def test_sty12_changing_the_shoes_keeps_the_other_slots_still_eligible() -> None:
    w = await _w()
    await w.edit(N.snk_l, formality=4)
    await w.edit(N.snk_r, formality=4)
    first = (await _look(w, Ask(day=TUE, code="business_casual"))).primary
    keep = {p.slot: p.pieces for p in first.picks}
    skip = {"shoes": frozenset(keep["shoes"])}
    ask = Ask(day=TUE, code="business_casual", locked=keep, skip=skip)
    second = (await _look(w, ask)).primary
    assert second.pick("shoes").pieces != keep["shoes"]
    for slot in ("top", "bottom", "watch"):
        assert second.pick(slot).pieces == keep[slot], slot


async def test_a_locked_piece_that_left_eligibility_is_replaced_and_said() -> None:
    w = await _w()
    await w.move(N.shirt_white, "deposited")
    ask = Ask(day=TUE, code="business_formal", locked={"top": (N.shirt_white,)})
    look = (await _look(w, ask)).primary
    assert look.pick("top").pieces == (N.shirt_lb,)
    assert any(N.shirt_white in c and "In laundry" in c for c in look.compromises)


async def test_sty14_a_reserved_piece_is_never_offered_to_a_second_plan() -> None:
    w = await _w()
    ask = Ask(day=TUE, code="business_formal", reserved={p: "your 10:00 event" for p in SHOES})
    look = (await _look(w, ask)).primary
    assert look.pick("shoes") is None
    gap = next(g for g in look.gaps if "shoes" in g)
    assert "reserved for your 10:00 event" in gap


async def test_sty13_an_in_use_piece_is_eligible_only_through_a_declared_hand_off() -> None:
    w = await _w()
    await w.move(N.trousers, "wear_started", plan="op_00000001")
    plain = (await _look(w, Ask(day=TUE, code="business_formal"))).primary
    assert N.trousers not in _ids(plain)
    handed = Ask(day=TUE, code="business_formal", shared={N.trousers: "op_00000001"})
    assert (await _look(w, handed)).primary.pick("bottom").pieces == (N.trousers,)
    wrong = Ask(day=TUE, code="business_formal", shared={N.trousers: "op_00000099"})
    assert N.trousers not in _ids((await _look(w, wrong)).primary)


async def test_the_availability_switch_is_what_the_eval_control_turns_off(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    w = await _w()
    for pid in SHOES:
        await w.move(pid, "deposited")
    monkeypatch.setattr(engine, "AVAILABILITY", False)
    look = (await _look(w, Ask(day=TUE, code="business_formal"))).primary
    assert look.pick("shoes").pieces == SHOES  # the control: an unavailable pair suggested


# ---- code review M1: a set's mates pass every hard exclusion -----------------------------------
async def test_m1_a_set_mate_held_by_another_plan_never_enters_the_look() -> None:
    w = await _w()
    ask = Ask(day=TUE, code="festive", occasion="festival", reserved={N.pyjama: "your 08:00 event"})
    look = (await _look(w, ask)).primary
    assert look.pick("top").pieces == (N.kurta,)  # it can be worn alone
    assert N.pyjama not in _ids(look)
    assert not any("is complete" in r for r in look.reasons)
    assert (
        f"The set {KURTA_SET} isn't worn whole here: {N.pyjama} is reserved for your 08:00 event; "
        f"{N.kurta} can be worn alone." in look.compromises
    )


async def test_m1_a_set_mate_he_excluded_never_enters_the_look() -> None:
    w = await _w()
    ask = Ask(day=TUE, code="festive", occasion="festival", excluded=frozenset({N.pyjama}))
    look = (await _look(w, ask)).primary
    assert N.pyjama not in _ids(look) and look.pick("top").pieces == (N.kurta,)
    assert any(KURTA_SET in c and "left out by your rules" in c for c in look.compromises)


async def test_m1_a_part_that_cant_be_worn_alone_needs_its_mates_free() -> None:
    w = await _w()
    ask = Ask(day=TUE, code="festive", occasion="festival", reserved={N.kurta: "your 08:00 event"})
    look = (await _look(w, ask)).primary
    assert N.kurta not in _ids(look) and N.pyjama not in _ids(look)
