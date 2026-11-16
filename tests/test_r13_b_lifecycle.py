# tests/test_r13_b_lifecycle.py -- R13 Part B (docs/plans/r13-wardrobe.md D3, D4, D11): the laundry
# lifecycle on I0's in-memory store, one named test per acceptance check of LND-01, LND-02,
# LND-05 to LND-08 and LND-10 to LND-13, plus plan review 1's H1 (a worn piece into the basket
# closes its wear) and M3 (a tap and a scan of one deposit make one change). Fixed clocks only.
from __future__ import annotations

import pytest
from r13_fakes import UID, ev
from r13_fakes_b import (
    BASKET,
    BLUE_SHIRT,
    DRAWER,
    JACKET,
    JEANS,
    NAVY_SHIRT,
    RACK,
    SOCK_L,
    SOCK_PAIR,
    SOCK_R,
    TEE,
    TROUSERS,
    TWIN,
    WATCH,
    WHITE_SHIRT,
    rig,
)

from jarvis.storage.docs import Op
from jarvis.wardrobe.laundry.holds import admit
from jarvis.wardrobe.model import Evidence
from jarvis.wardrobe.ports import Refused
from jarvis.wardrobe.states import owned, wearable_pair


async def _owned(r) -> int:  # type: ignore[no-untyped-def]
    return sum(1 for p in (await r.view()).active() if owned(p.state))


async def test_lnd_01_a_deposit_keeps_the_shirt_owned_but_out_of_ready_pieces() -> None:
    r = await rig()
    before = await _owned(r)
    got = await r.desk.move(UID, "basket", pieces=(NAVY_SHIRT,))
    assert got.status == "done" and got.message == "Done: a navy shirt is in the laundry."
    shirt = await r.piece(NAVY_SHIRT)
    assert shirt.state == "in_laundry" and not shirt.eligible
    assert await _owned(r) == before  # still owned, never counted twice or dropped
    assert NAVY_SHIRT not in {p.id for p in (await r.view()).active() if p.eligible}


async def test_lnd_02_a_cancelled_scan_sends_nothing_and_a_camera_deposit_needs_a_release() -> None:
    r = await rig()
    assert await r.state(WHITE_SHIRT) == "ready"  # a scan he cancels never calls B: Ready
    no_release = ev(WHITE_SHIRT, "deposited", r.clock(), source="camera", via="cam-basket")
    held = admit(no_release)
    assert held.verified is False
    await r.commit(held)
    assert await r.state(WHITE_SHIRT) == "review"
    (entry,) = await r.open_entries()
    assert entry.kind == "hold" and entry.reason == "unverified" and entry.pieces == (WHITE_SHIRT,)
    released = no_release.model_copy(
        update={"evidence": Evidence(how="match", released=True), "id": "we_" + "1" * 20}
    )
    assert admit(released).verified is True  # a release seen over the rim is a deposit
    assert admit(ev(BLUE_SHIRT, "deposited", r.clock())).verified is True  # a tap stays as it is


async def test_lnd_05_correcting_an_old_basket_event_never_overwrites_a_later_clean_return() -> (
    None
):
    r = await rig()
    dirty = await r.desk.move(UID, "basket", pieces=(BLUE_SHIRT,))
    deposit = dirty.committed.events[0].id
    r.clock.advance(hours=1)
    await r.desk.move(UID, "load", pieces=(BLUE_SHIRT,))
    r.clock.advance(hours=1)
    await r.desk.move(UID, "ready", pieces=(BLUE_SHIRT,), place=RACK)
    r.clock.advance(minutes=5)
    fixed = await r.desk.correct(UID, BLUE_SHIRT, deposit)
    assert fixed.status == "done" and await r.state(BLUE_SHIRT) == "ready"
    marks = {h.event.id: h.mark for h in await r.store.history(UID, BLUE_SHIRT)}
    assert marks[deposit] == "voided"


async def test_lnd_05_striking_out_a_release_reopens_its_check() -> None:
    r = await rig()
    await r.desk.move(UID, "basket", one_of=(WHITE_SHIRT, TWIN))
    (entry,) = await r.open_entries()
    await r.desk.resolve(UID, entry.id, "none")  # "there was no deposit": both released
    assert await r.state(WHITE_SHIRT) == "ready" and await r.open_entries() == ()
    r.clock.advance(minutes=5)
    got = await r.desk.correct(UID, WHITE_SHIRT)  # the newest step: the release
    shirt = await r.piece(WHITE_SHIRT)
    assert shirt.state == "review" and shirt.hold == "held"
    (again,) = await r.open_entries()  # a hold never lives without its entry (H4)
    assert (again.kind, again.reason, again.pieces, again.back_to) == (
        "hold",
        "held",
        (WHITE_SHIRT,),
        "ready",
    )
    assert got.status == "review" and got.entry == again.id
    assert got.message == (
        "Done: that step is struck out. The piece waits for a check in Helpers, Wardrobe."
    )
    r.clock.advance(minutes=1)
    await r.desk.resolve(UID, again.id, "these")  # and it can be answered
    assert await r.state(WHITE_SHIRT) == "ready" and await r.open_entries() == ()


async def test_lnd_05_a_correction_that_leaves_no_hold_opens_nothing() -> None:
    r = await rig()
    await r.desk.move(UID, "basket", pieces=(TEE,))
    r.clock.advance(minutes=5)
    got = await r.desk.correct(UID, TEE)
    assert got.status == "done" and got.entry is None and await r.open_entries() == ()


async def test_lnd_05_a_correction_beside_an_open_check_opens_no_second_one() -> None:
    r = await rig()
    await r.commit(ev(WATCH, "missing", r.clock()))
    r.clock.advance(minutes=1)
    seen = ev(WATCH, "seen", r.clock(), place=DRAWER)
    await r.commit(seen)
    r.clock.advance(minutes=1)
    got = await r.desk.correct(UID, WATCH, seen.id)  # still missing: its own check answers it
    assert got.status == "done" and got.entry is None
    (only,) = await r.open_entries()
    assert only.pieces == (WATCH,) and await r.state(WATCH) == "review"


async def test_lnd_06_a_shirt_lifted_from_the_hamper_to_the_sorting_table_stays_unavailable() -> (
    None
):
    r = await rig()
    await r.desk.move(UID, "basket", pieces=(WHITE_SHIRT,), place=BASKET)
    r.clock.advance(minutes=10)
    got = await r.desk.move(UID, "lifted", pieces=(WHITE_SHIRT,), place=DRAWER)
    shirt = await r.piece(WHITE_SHIRT)
    assert got.status == "done" and shirt.state == "in_laundry" and shirt.place == DRAWER
    assert not shirt.eligible


async def test_lnd_07_a_mixed_load_moves_its_five_confirmed_pieces_in_one_commit() -> None:
    r = await rig()
    basket = (BLUE_SHIRT, WHITE_SHIRT, NAVY_SHIRT, TEE, JEANS, TROUSERS, JACKET)
    await r.desk.move(UID, "basket", pieces=basket)
    r.clock.advance(minutes=30)
    commits = len(r.docs.tx_sizes)
    load = basket[:5]
    got = await r.desk.move(UID, "load", pieces=load)
    assert got.status == "done" and got.message == "Done: a load of 5 pieces is washing."
    assert len(r.docs.tx_sizes) == commits + 1  # the load and the states: ONE commit
    assert [await r.state(p) for p in load] == ["washing"] * 5
    assert [await r.state(p) for p in basket[5:]] == ["in_laundry"] * 2
    (open_load,) = (await r.laundry()).loads
    assert open_load.pieces == load and open_load.closed_at is None


async def test_lnd_07_a_failed_write_leaves_neither_the_load_nor_the_states(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    r = await rig()
    await r.desk.move(UID, "basket", pieces=(BLUE_SHIRT,))
    path = r.desk.store.laundry_path(UID)
    real = r.docs._apply  # noqa: SLF001 - the fake's commit, made to fail on B's document

    def failing(ops: list[Op]) -> None:
        if any(op.path == path for op in ops):
            raise RuntimeError("the commit failed")
        real(ops)

    monkeypatch.setattr(r.docs, "_apply", failing)
    with pytest.raises(RuntimeError):
        await r.desk.move(UID, "load", pieces=(BLUE_SHIRT,))
    monkeypatch.undo()
    assert await r.state(BLUE_SHIRT) == "in_laundry" and (await r.laundry()).loads == ()


async def test_lnd_07_a_load_takes_only_pieces_that_are_in_the_basket() -> None:
    r = await rig()
    await r.desk.move(UID, "basket", pieces=(BLUE_SHIRT,))
    with pytest.raises(Refused) as no:
        await r.desk.move(UID, "load", pieces=(BLUE_SHIRT, WHITE_SHIRT))
    assert (
        str(no.value) == "A white shirt isn't in the laundry basket, so that step doesn't fit it."
    )
    assert await r.state(BLUE_SHIRT) == "in_laundry" and (await r.laundry()).loads == ()


async def test_lnd_08_three_of_five_moved_to_drying_change_only_those_three() -> None:
    r = await rig()
    five = (BLUE_SHIRT, WHITE_SHIRT, NAVY_SHIRT, TEE, JEANS)
    await r.desk.move(UID, "basket", pieces=five)
    load = (await r.desk.move(UID, "load", pieces=five)).load
    assert load is not None
    r.clock.advance(hours=1)
    got = await r.desk.move(UID, "drying", pieces=five[:3], load=load)
    assert got.message == "Done: 3 pieces are drying."
    assert [await r.state(p) for p in five] == ["drying"] * 3 + ["washing"] * 2


async def test_lnd_08_a_step_on_a_piece_not_in_that_load_is_refused() -> None:
    r = await rig()
    await r.desk.move(UID, "basket", pieces=(BLUE_SHIRT, WHITE_SHIRT))
    first = (await r.desk.move(UID, "load", pieces=(BLUE_SHIRT,))).load
    await r.desk.move(UID, "load", pieces=(WHITE_SHIRT,))
    with pytest.raises(Refused) as no:
        await r.desk.move(UID, "drying", pieces=(WHITE_SHIRT,), load=first)
    assert str(no.value) == "A white shirt isn't in that load."
    assert await r.state(WHITE_SHIRT) == "washing"


async def test_lnd_08_the_whole_load_moves_on_when_he_marks_it_done() -> None:
    r = await rig()
    await r.desk.move(UID, "basket", pieces=(BLUE_SHIRT, TEE))
    load = (await r.desk.move(UID, "load", pieces=(BLUE_SHIRT, TEE))).load
    await r.desk.move(UID, "drying", load=load)  # the phone form of the washer's "finished"
    assert [await r.state(p) for p in (BLUE_SHIRT, TEE)] == ["drying", "drying"]


async def test_lnd_10_a_damp_shirt_and_one_that_needs_pressing_stay_out_until_returned() -> None:
    r = await rig()
    await r.desk.move(UID, "basket", pieces=(BLUE_SHIRT, WHITE_SHIRT))
    load = (await r.desk.move(UID, "load", pieces=(BLUE_SHIRT, WHITE_SHIRT))).load
    await r.desk.move(UID, "drying", pieces=(BLUE_SHIRT,), load=load)  # damp
    pressed = await r.desk.move(UID, "prep", pieces=(WHITE_SHIRT,), load=load)  # needs pressing
    assert pressed.message == "Done: a white shirt needs pressing."
    assert [await r.state(p) for p in (BLUE_SHIRT, WHITE_SHIRT)] == ["drying", "needs_prep"]
    assert not any([(await r.piece(p)).eligible for p in (BLUE_SHIRT, WHITE_SHIRT)])
    await r.desk.move(UID, "ready", pieces=(BLUE_SHIRT, WHITE_SHIRT), place=RACK)
    assert all([(await r.piece(p)).eligible for p in (BLUE_SHIRT, WHITE_SHIRT)])


async def test_lnd_11_the_navy_shirt_comes_back_with_its_id_and_the_plan_check_hears_it() -> None:
    r = await rig()
    before = await _owned(r)
    await r.desk.move(UID, "basket", pieces=(NAVY_SHIRT,))
    await r.desk.move(UID, "load", pieces=(NAVY_SHIRT,))
    r.observer.heard.clear()
    back = await r.desk.move(UID, "ready", pieces=(NAVY_SHIRT,), place=RACK)
    assert back.message == "Done: a navy shirt is back and ready."
    shirt = await r.piece(NAVY_SHIRT)
    assert shirt.id == NAVY_SHIRT and shirt.eligible and shirt.place == RACK
    assert await _owned(r) == before
    (heard,) = r.observer.heard  # C's refresh hears it once, after the commit
    assert (heard.piece, heard.kind, heard.before, heard.after) == (
        NAVY_SHIRT,
        "returned",
        "washing",
        "ready",
    )


async def test_lnd_12_four_of_six_returned_restore_four_ids_and_two_stay_unavailable() -> None:
    r = await rig()
    six = (BLUE_SHIRT, WHITE_SHIRT, NAVY_SHIRT, TEE, JEANS, TROUSERS)
    await r.desk.move(UID, "basket", pieces=six)
    load = (await r.desk.move(UID, "load", pieces=six)).load
    await r.desk.move(UID, "drying", load=load)
    got = await r.desk.move(UID, "ready", pieces=six[:4], load=load, place=RACK)
    assert got.message == "Done: 4 pieces are back and ready."
    view = await r.view()
    assert not [p for p in view.active() if p.state == "in_laundry"]  # the basket is empty
    assert [view.pieces[p].eligible for p in six] == [True] * 4 + [False] * 2
    (still,) = (await r.laundry()).loads
    assert still.back == six[:4] and still.closed_at is None
    await r.desk.move(UID, "ready", pieces=six[4:], load=load, place=DRAWER)
    (done,) = (await r.laundry()).loads
    assert done.closed_at == r.clock()


async def test_lnd_13_a_clean_left_sock_stays_while_its_pair_waits_for_its_partner() -> None:
    r = await rig()
    pairs = (await r.view()).pairs
    await r.desk.move(UID, "basket", pieces=(SOCK_L, SOCK_R))
    await r.desk.move(UID, "load", pieces=(SOCK_L, SOCK_R))
    await r.desk.move(UID, "ready", pieces=(SOCK_L,), place=DRAWER)
    view = await r.view()
    pair = view.pairs[SOCK_PAIR]
    assert view.pieces[SOCK_L].eligible and owned(view.pieces[SOCK_L].state)
    assert not wearable_pair([view.pieces[p].state for p in pair.pieces])
    status = await r.desk.status(UID)
    assert status["half_pairs"] == [{"pair": SOCK_PAIR, "ready": [SOCK_L], "out": [SOCK_R]}]
    await r.desk.move(UID, "ready", pieces=(SOCK_R,), place=DRAWER)
    view = await r.view()
    assert wearable_pair([view.pieces[p].state for p in pair.pieces])
    assert view.pairs == pairs  # B never re-pairs: only his explicit edit does (A)
    assert (await r.desk.status(UID))["half_pairs"] == []


async def test_h1_a_worn_shirt_into_the_basket_closes_its_wear_for_its_plan() -> None:
    r = await rig()
    await r.wear(BLUE_SHIRT, plan="pl_meeting")
    r.clock.advance(hours=8)
    r.observer.heard.clear()
    got = await r.desk.move(UID, "basket", pieces=(BLUE_SHIRT,))
    shirt = await r.piece(BLUE_SHIRT)
    assert got.status == "done" and shirt.state == "in_laundry" and shirt.wears == 1
    assert shirt.wear is None
    (heard,) = r.observer.heard  # the wear's plan travels with it: C marks nothing
    assert heard.kind == "wear_done" and heard.plan == "pl_meeting"


async def test_m3_a_tap_and_a_scan_of_one_deposit_make_one_change_and_no_entry() -> None:
    r = await rig()
    scan = ev(TEE, "deposited", r.clock(), source="phone", how="qr", client_id="scan-000001")
    await r.commit(scan)
    r.clock.advance(minutes=1)
    tap = await r.desk.move(UID, "basket", pieces=(TEE,))
    assert tap.status == "already" and tap.message == "Already done: nothing changed."
    again = await r.desk.move(UID, "basket", pieces=(TEE,), client_id="tap-0000001")
    retry = await r.desk.move(UID, "basket", pieces=(TEE,), client_id="tap-0000001")
    assert again.status == retry.status == "already"
    assert await r.open_entries() == () and await r.state(TEE) == "in_laundry"
    kinds = [h.event.kind for h in await r.store.history(UID, TEE)]
    assert kinds.count("deposited") == 3  # kept (duplicates), the retry not even appended


async def test_a_held_piece_is_refused_with_the_way_out() -> None:
    r = await rig()
    await r.commit(admit(ev(WHITE_SHIRT, "deposited", r.clock(), source="camera")))
    with pytest.raises(Refused) as no:
        await r.desk.move(UID, "load", pieces=(WHITE_SHIRT,))
    assert str(no.value) == (
        "A white shirt waits for a check in Helpers, Wardrobe: resolve that first."
    )


async def test_a_private_piece_is_a_private_basic_in_every_sentence() -> None:
    r = await rig()
    from r13_fakes_b import VEST_A

    got = await r.desk.move(UID, "basket", pieces=(VEST_A,))
    assert got.message == "Done: a private basic is in the laundry."
    with pytest.raises(Refused) as no:
        await r.desk.move(UID, "drying", pieces=(VEST_A,))
    assert str(no.value) == "A private basic isn't washing, so that step doesn't fit it."
