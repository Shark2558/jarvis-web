# tests/test_r13_b_holds.py -- R13 Part B (docs/plans/r13-wardrobe.md D5, D11, D20, plan review H4):
# holds and pending deposits. LND-03 (a bundle: a verified deposit plus a pending one with no piece
# id that holds only the plausible pieces), LND-04 (two near-identical shirts both withheld until he
# says which; "no deposit" clears to the last verified state), a name that fits several pieces
# (never a guess), and each way a review entry is resolved. Fixed clocks only.
from __future__ import annotations

import pytest
from r13_fakes import UID, ev
from r13_fakes_b import (
    BLUE_SHIRT,
    JACKET,
    NAVY_SHIRT,
    RACK,
    SHOE_L,
    TEE,
    TWIN,
    VEST_A,
    VEST_B,
    WHITE_SHIRT,
    rig,
)

from jarvis.wardrobe.laundry import holds
from jarvis.wardrobe.ports import Refused


async def test_lnd_03_a_jacket_hiding_a_shirt_is_one_deposit_and_one_pending_deposit() -> None:
    r = await rig()
    await r.wear(BLUE_SHIRT, plan="pl_day")
    await r.wear(JACKET)
    r.clock.advance(hours=9)
    got = await r.desk.move(UID, "basket", pieces=(JACKET,), more=1, category="tops")
    assert got.status == "review"
    assert got.message == (
        "Done: a navy jacket is in the laundry. 1 more piece waits for a check in Helpers, "
        "Wardrobe."
    )
    assert await r.state(JACKET) == "in_laundry"
    (entry,) = await r.open_entries()
    assert entry.kind == "pending_deposit" and entry.count == 1 and entry.category == "tops"
    assert entry.candidates == (BLUE_SHIRT,) and entry.pieces == (BLUE_SHIRT,)
    assert await r.state(BLUE_SHIRT) == "review"  # held: the shirt he wore, never a guess
    kinds = [h.event.kind for h in await r.store.history(UID, BLUE_SHIRT)]
    assert "deposited" not in kinds and kinds[-1] == "held"  # no deposit names a piece id
    assert (await r.piece(BLUE_SHIRT)).back_to == "in_use"


async def test_lnd_03_a_pending_deposit_with_no_plausible_piece_holds_nothing() -> None:
    r = await rig()
    got = await r.desk.move(UID, "basket", pieces=(TEE,), more=2, category="footwear")
    (entry,) = await r.open_entries()
    assert got.status == "review" and entry.candidates == () and entry.count == 2
    assert await r.state(SHOE_L) == "ready"


async def test_lnd_03_he_says_which_one_and_its_wear_is_closed() -> None:
    r = await rig()
    await r.wear(BLUE_SHIRT, plan="pl_day")
    r.clock.advance(hours=9)
    await r.desk.move(UID, "basket", pieces=(JACKET,), more=1, category="tops")
    (entry,) = await r.open_entries()
    r.clock.advance(minutes=5)
    done = await r.desk.resolve(UID, entry.id, "these", pieces=(BLUE_SHIRT,))
    shirt = await r.piece(BLUE_SHIRT)
    assert done.status == "done" and shirt.state == "in_laundry" and shirt.wears == 1
    assert await r.open_entries() == ()
    (closed,) = (await r.review()).entries
    assert closed.outcome == "these" and closed.closed_at == r.clock()


async def test_plausible_pieces_are_the_ones_in_use_or_worn_in_the_last_day() -> None:
    r = await rig()
    await r.wear(NAVY_SHIRT)
    r.clock.advance(minutes=1)
    await r.commit(ev(NAVY_SHIRT, "wear_done", r.clock(), to="ready"))  # worn, rewear: Ready
    await r.wear(BLUE_SHIRT)
    await r.wear(TEE)
    r.clock.advance(minutes=1)
    await r.commit(ev(TEE, "deposited", r.clock()))  # already dirty: not plausible
    view = await r.view()
    assert holds.plausible(view, "tops", r.clock(), exclude=()) == (BLUE_SHIRT, NAVY_SHIRT)
    r.clock.advance(hours=24, minutes=1)
    later = await r.view()
    assert holds.plausible(later, "tops", r.clock(), exclude=()) == (BLUE_SHIRT,)  # still in use
    assert holds.plausible(later, "tops", r.clock(), exclude=(BLUE_SHIRT,)) == ()


async def test_lnd_04_two_near_identical_shirts_are_both_withheld_until_he_says() -> None:
    r = await rig()
    got = await r.desk.move(UID, "basket", query="white shirt")
    assert got.status == "review"
    assert got.message == "2 pieces match: they wait for a check in Helpers, Wardrobe."
    assert [await r.state(p) for p in (WHITE_SHIRT, TWIN)] == ["review", "review"]
    (entry,) = await r.open_entries()
    assert entry.kind == "pending_deposit" and set(entry.candidates) == {WHITE_SHIRT, TWIN}
    assert entry.count == 1
    r.clock.advance(minutes=3)
    await r.desk.resolve(UID, entry.id, "these", pieces=(TWIN,))
    assert [await r.state(p) for p in (WHITE_SHIRT, TWIN)] == ["ready", "in_laundry"]


async def test_lnd_04_there_was_no_deposit_clears_both_to_their_last_verified_state() -> None:
    r = await rig()
    await r.wear(TWIN)
    got = await r.desk.move(UID, "basket", one_of=(WHITE_SHIRT, TWIN))  # D7: within 0.03
    assert got.status == "review"
    (entry,) = await r.open_entries()
    await r.desk.resolve(UID, entry.id, "none")
    assert [await r.state(p) for p in (WHITE_SHIRT, TWIN)] == ["ready", "in_use"]
    assert await r.open_entries() == ()


async def test_two_identical_private_vests_are_withheld_and_named_only_as_private_basics() -> None:
    r = await rig()
    got = await r.desk.move(UID, "basket", query="black vest")
    assert got.status == "review" and "private" not in got.message
    assert [await r.state(p) for p in (VEST_A, VEST_B)] == ["review", "review"]


async def test_one_match_is_the_piece_and_no_match_is_refused_in_words() -> None:
    r = await rig()
    one = await r.desk.move(UID, "basket", query="my navy striped shirts")
    assert one.status == "done" and await r.state(NAVY_SHIRT) == "in_laundry"
    with pytest.raises(Refused) as no:
        await r.desk.move(UID, "basket", query="purple scarf")
    assert str(no.value) == (
        "No piece in your wardrobe matches that. Say its colour and type, or pick it in Helpers, "
        "Wardrobe."
    )


async def test_a_name_that_fits_several_pieces_for_another_step_asks_and_holds_nothing() -> None:
    r = await rig()
    await r.desk.move(UID, "basket", pieces=(WHITE_SHIRT, TWIN))
    load = (await r.desk.move(UID, "load", pieces=(WHITE_SHIRT, TWIN))).load
    got = await r.desk.move(UID, "ready", query="white shirt", load=load, place=RACK)
    assert got.status == "review"
    assert got.message == "2 pieces match: pick the right one in Helpers, Wardrobe."
    assert [await r.state(p) for p in (WHITE_SHIRT, TWIN)] == ["washing", "washing"]
    (entry,) = await r.open_entries()
    assert entry.kind == "rescan" and entry.step == "ready" and entry.pieces == ()
    await r.desk.resolve(UID, entry.id, "these", pieces=(WHITE_SHIRT,))
    assert [await r.state(p) for p in (WHITE_SHIRT, TWIN)] == ["ready", "washing"]
    assert (await r.piece(WHITE_SHIRT)).place == RACK


async def test_an_unverified_change_is_confirmed_or_denied_from_its_entry() -> None:
    r = await rig()
    await r.commit(holds.admit(ev(TEE, "deposited", r.clock(), source="camera")))
    await r.commit(holds.admit(ev(NAVY_SHIRT, "deposited", r.clock(), source="camera")))
    yes, no = await r.open_entries()
    r.clock.advance(minutes=2)
    await r.desk.resolve(UID, yes.id, "these")
    await r.desk.resolve(UID, no.id, "none")
    assert [await r.state(p) for p in (TEE, NAVY_SHIRT)] == ["in_laundry", "ready"]


async def test_a_piece_held_by_another_check_is_never_released_by_this_one() -> None:
    r = await rig()
    await r.commit(holds.admit(ev(TWIN, "deposited", r.clock(), source="camera")))
    r.clock.advance(minutes=1)
    await r.desk.move(UID, "basket", one_of=(WHITE_SHIRT, TWIN))
    first, second = await r.open_entries()
    assert second.pieces == (WHITE_SHIRT,)  # TWIN was already held: not this entry's hold
    await r.desk.resolve(UID, second.id, "none")
    assert [await r.state(p) for p in (WHITE_SHIRT, TWIN)] == ["ready", "review"]
    with pytest.raises(Refused) as gone:
        await r.desk.resolve(UID, second.id, "none")
    assert str(gone.value) == "That check is already closed."


async def test_l8_picking_a_piece_another_check_holds_is_refused_in_its_own_words() -> None:
    r = await rig()
    await r.commit(holds.admit(ev(TWIN, "deposited", r.clock(), source="camera")))
    r.clock.advance(minutes=1)
    await r.desk.move(UID, "basket", one_of=(WHITE_SHIRT, TWIN))
    first, second = await r.open_entries()
    with pytest.raises(Refused) as held:
        await r.desk.resolve(UID, second.id, "these", pieces=(TWIN,))
    assert str(held.value) == (
        "A white shirt waits for a check in Helpers, Wardrobe: resolve that first."
    )  # never "isn't ready or in use": the way out is the other check
    assert (await r.piece(TWIN)).hold == "unverified" and len(await r.open_entries()) == 2


async def test_a_choice_outside_the_candidates_is_refused() -> None:
    r = await rig()
    await r.desk.move(UID, "basket", one_of=(WHITE_SHIRT, TWIN))
    (entry,) = await r.open_entries()
    with pytest.raises(Refused) as no:
        await r.desk.resolve(UID, entry.id, "these", pieces=(BLUE_SHIRT,))
    assert str(no.value) == "Pick one of the pieces this check names."
    with pytest.raises(Refused):
        await r.desk.resolve(UID, entry.id, "these", pieces=(WHITE_SHIRT, TWIN))  # count is 1


async def test_the_holds_switch_is_one_function_the_eval_control_turns_off(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(holds, "hold_events", lambda *a, **k: ())
    r = await rig()
    await r.desk.move(UID, "basket", one_of=(WHITE_SHIRT, TWIN))
    assert [await r.state(p) for p in (WHITE_SHIRT, TWIN)] == ["ready", "ready"]


async def test_m3_one_of_never_holds_a_piece_at_the_shop_or_already_in_the_basket() -> None:
    r = await rig()
    await r.desk.send_out(UID, (TWIN,), "Dry cleaner")
    with pytest.raises(Refused) as shop:
        await r.desk.move(UID, "basket", one_of=(WHITE_SHIRT, TWIN))
    assert (
        str(shop.value) == "A white shirt is with an outside laundry: mark it back from its batch."
    )
    await r.desk.move(UID, "basket", pieces=(NAVY_SHIRT,))
    with pytest.raises(Refused) as dirty:
        await r.desk.move(UID, "basket", one_of=(WHITE_SHIRT, NAVY_SHIRT))
    assert str(dirty.value) == "A navy shirt isn't ready or in use, so that step doesn't fit it."
    assert await r.open_entries() == () and await r.state(TWIN) == "with_provider"
