# tests/test_r13_b_correct.py -- R13 Part B, LND-05 (docs/plans/r13-wardrobe.md D4, D11; review M1):
# striking out a laundry step keeps B's own records true in the SAME commit as the `corrected`
# event: a struck-out load start leaves its load, a struck-out send-out leaves its batch (no false
# "overdue"), a struck-out return to the shop puts the piece back on its batch, a struck-out hold
# shrinks or closes its check. Archive, restore, merge and a correction are undone with their own
# button (A's `CARD_ONLY`), never here. Fixed clocks only.
from __future__ import annotations

from datetime import date

import pytest
from r13_fakes import UID, ev, ist, piece
from r13_fakes_b import (
    BELT,
    BLAZER,
    BLUE_SHIRT,
    RACK,
    TEE,
    TRAY,
    TROUSERS,
    TWIN,
    WATCH,
    WHITE_SHIRT,
    rig,
)

from jarvis.wardrobe.ports import Refused


async def test_lnd_05_a_struck_out_load_start_leaves_its_load_and_the_load_still_closes() -> None:
    r = await rig()
    await r.desk.move(UID, "basket", pieces=(BLUE_SHIRT, TEE))
    load = (await r.desk.move(UID, "load", pieces=(BLUE_SHIRT, TEE))).load
    r.clock.advance(minutes=2)
    commits = len(r.docs.tx_sizes)
    await r.desk.correct(UID, TEE)  # its newest step: the load start
    assert len(r.docs.tx_sizes) == commits + 1  # the event and B's load: ONE commit
    assert await r.state(TEE) == "in_laundry"
    (x,) = (await r.laundry()).loads
    assert x.pieces == (BLUE_SHIRT,) and (await r.desk.status(UID))["loads"][0]["step"] == "washing"
    await r.desk.move(UID, "ready", load=load, place=RACK)  # the whole load is back
    (x,) = (await r.laundry()).loads
    assert x.closed_at == r.clock() and x.back == (BLUE_SHIRT,)


async def test_lnd_05_a_load_whose_only_piece_is_struck_out_is_gone() -> None:
    r = await rig()
    await r.desk.move(UID, "basket", pieces=(TEE,))
    await r.desk.move(UID, "load", pieces=(TEE,))
    r.clock.advance(minutes=2)
    await r.desk.correct(UID, TEE)
    assert (await r.laundry()).loads == () and await r.state(TEE) == "in_laundry"


async def test_lnd_05_a_struck_out_send_out_leaves_its_batch_and_never_alerts() -> None:
    r = await rig()
    batch = (
        await r.desk.send_out(UID, (BLAZER, TROUSERS), "Dry cleaner", due=date(2026, 11, 18))
    ).batch
    r.clock.advance(minutes=2)
    await r.desk.correct(UID, TROUSERS)  # it never went
    assert await r.state(TROUSERS) == "ready"
    (b,) = (await r.laundry()).batches
    assert b.pieces == (BLAZER,)
    await r.desk.receive(UID, batch, (BLAZER,))
    (b,) = (await r.laundry()).batches
    assert b.closed_at == r.clock() and not b.short
    r.clock.set(ist(2026, 11, 20, 9, 0))
    (job,) = r.part.daily_jobs
    assert await job.run([UID]) == {} and r.notifier.sent == []  # no false "overdue"


async def test_lnd_05_a_batch_whose_only_piece_is_struck_out_is_gone() -> None:
    r = await rig()
    await r.desk.send_out(UID, (BLAZER,), "Dry cleaner")
    r.clock.advance(minutes=2)
    await r.desk.correct(UID, BLAZER)
    assert (await r.laundry()).batches == () and await r.state(BLAZER) == "ready"


async def test_lnd_05_a_struck_out_return_from_the_shop_puts_it_back_on_its_batch() -> None:
    r = await rig()
    batch = (await r.desk.send_out(UID, (BLAZER, TROUSERS), "Dry cleaner")).batch
    await r.desk.receive(UID, batch, (BLAZER, TROUSERS))
    r.clock.advance(minutes=2)
    await r.desk.correct(UID, TROUSERS)  # it is still at the shop
    assert await r.state(TROUSERS) == "with_provider"
    (b,) = (await r.laundry()).batches
    assert b.closed_at is None and b.back == (BLAZER,) and b.short  # never stranded (M3)
    r.clock.advance(minutes=2)
    await r.desk.receive(UID, batch, (TROUSERS,))
    assert await r.state(TROUSERS) == "ready"


async def test_lnd_05_a_struck_out_hold_shrinks_its_check_and_the_last_one_closes_it() -> None:
    r = await rig()
    await r.desk.move(UID, "basket", one_of=(WHITE_SHIRT, TWIN))
    r.clock.advance(minutes=1)
    await r.desk.correct(UID, WHITE_SHIRT)  # its hold
    (pending,) = await r.open_entries()
    assert pending.pieces == (TWIN,) and await r.state(WHITE_SHIRT) == "ready"
    await r.desk.blind(UID, places=(TRAY,))  # the belt and the watch
    r.clock.advance(minutes=1)
    await r.desk.correct(UID, BELT)
    blind = next(e for e in await r.open_entries() if e.reason == "blind")
    assert blind.pieces == (WATCH,) and await r.state(BELT) == "ready"
    await r.desk.correct(UID, WATCH)
    assert [e.reason for e in await r.open_entries()] == ["pending"]  # the blind check is closed


async def test_lnd_05_archive_restore_merge_and_a_correction_have_their_own_button() -> None:
    r = await rig()
    with pytest.raises(Refused) as nothing:
        await r.desk.correct(UID, BELT)  # only its registration: nothing of laundry's
    assert str(nothing.value) == "There's no step to strike out for that piece."
    registered = (await r.store.history(UID, BELT))[0].event.id
    with pytest.raises(Refused) as own:
        await r.desk.correct(UID, BELT, registered)
    assert str(own.value) == "That change is undone with its own button: archive, restore or merge."
    await r.commit(ev(BELT, "archived", r.clock()))
    r.clock.advance(minutes=1)
    await r.commit(ev(BELT, "restored", r.clock()))
    with pytest.raises(Refused):
        await r.desk.correct(UID, BELT)  # the newest is a restore: never struck out here
    assert await r.state(BELT) == "review"


async def test_lnd_05_a_struck_out_return_puts_the_piece_back_in_its_load() -> None:
    r = await rig()
    await r.desk.move(UID, "basket", pieces=(TEE,))
    load = (await r.desk.move(UID, "load", pieces=(TEE,))).load
    r.clock.advance(minutes=5)
    await r.desk.move(UID, "ready", pieces=(TEE,), load=load, place=RACK)
    assert (await r.laundry()).loads[0].closed_at is not None
    r.clock.advance(minutes=1)
    await r.desk.correct(UID, TEE)  # it never came back
    assert await r.state(TEE) == "washing"
    (x,) = (await r.laundry()).loads
    assert (x.closed_at, x.back, x.pieces) == (None, (), (TEE,))


async def test_lnd_05_a_batch_whose_last_piece_out_is_struck_out_closes() -> None:
    r = await rig()
    batch = (await r.desk.send_out(UID, (BLAZER, TROUSERS), "Dry cleaner")).batch
    assert batch is not None
    await r.desk.receive(UID, batch, (BLAZER,))
    r.clock.advance(minutes=2)
    await r.desk.correct(UID, TROUSERS)  # it never went: nothing is out any more
    (b,) = (await r.laundry()).batches
    assert b.pieces == (BLAZER,) and b.closed_at == r.clock() and not b.short


async def test_lnd_05_a_load_start_struck_out_after_its_return_leaves_the_load_as_it_was() -> None:
    r = await rig()
    await r.desk.move(UID, "basket", pieces=(TEE, BLUE_SHIRT))
    started = await r.desk.move(UID, "load", pieces=(TEE, BLUE_SHIRT))
    start = next(e.id for e in started.committed.events if e.piece == TEE)
    await r.desk.move(UID, "ready", pieces=(TEE,), load=started.load, place=RACK)
    before = (await r.laundry()).loads
    r.clock.advance(minutes=2)
    await r.desk.correct(UID, TEE, start)
    assert (await r.laundry()).loads == before and await r.state(TEE) == "ready"


def test_the_correction_planner_refuses_a_piece_not_his_and_a_card_only_step() -> None:
    from jarvis.wardrobe.laundry import corrections
    from jarvis.wardrobe.laundry.store import LaundryDoc, ReviewDoc
    from jarvis.wardrobe.model import WardrobeView

    now = ist(2026, 11, 16, 9, 0)
    empty = WardrobeView(uid=UID)
    with pytest.raises(Refused) as gone:
        corrections.plan_correct(empty, LaundryDoc(), ReviewDoc(), ev(BELT, "seen", now), now)
    assert str(gone.value) == "That piece isn't in your wardrobe."
    view = empty.model_copy(update={"pieces": {BELT: piece(BELT, "belt")}})
    with pytest.raises(Refused) as own:
        corrections.plan_correct(view, LaundryDoc(), ReviewDoc(), ev(BELT, "archived", now), now)
    assert str(own.value) == "That change is undone with its own button: archive, restore or merge."
