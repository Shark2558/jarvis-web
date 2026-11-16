# tests/test_r13_b_blind.py -- R13 Part B (docs/plans/r13-wardrobe.md D5 OPS-02, D11): a blind
# period in its phone form. "I moved things without scanning" (a tap naming the places or categories
# touched, at the times he states) holds the pieces at rest there until a rescan or his correction:
# they are verified before they appear in a ready plan. Fixed clocks only.
from __future__ import annotations

from datetime import date

import pytest
from r13_fakes import UID, ev, ist
from r13_fakes_b import (
    BELT,
    BLUE_SHIRT,
    DRAWER,
    RACK,
    SOCK_L,
    TRAVEL,
    TRAY,
    TWIN,
    UNDERPANTS,
    VEST_A,
    WATCH,
    WHITE_SHIRT,
    rig,
)

from jarvis.wardrobe.ports import Refused


async def test_ops_02_the_pieces_touched_are_verified_before_they_reach_a_ready_plan() -> None:
    r = await rig()
    got = await r.desk.blind(UID, places=(TRAY,))
    assert got.status == "review"
    assert got.message == (
        "Noted: 2 pieces wait for a quick check in Helpers, Wardrobe before they're offered again."
    )
    for pid in (BELT, WATCH):
        p = await r.piece(pid)
        assert p.state == "review" and p.hold == "blind" and not p.eligible
    (entry,) = await r.open_entries()
    assert entry.kind == "rescan" and entry.reason == "blind" and set(entry.pieces) == {BELT, WATCH}
    assert entry.place == TRAY
    r.clock.advance(minutes=20)
    await r.desk.resolve(UID, entry.id, "these", pieces=(BELT,), how="qr")  # rescanned: still there
    assert (await r.piece(BELT)).eligible and not (await r.piece(WATCH)).eligible
    (still,) = await r.open_entries()
    assert still.pieces == (WATCH,)
    await r.desk.resolve(UID, still.id, "moved", pieces=(WATCH,), to="ready", place=TRAVEL)
    watch = await r.piece(WATCH)
    assert watch.eligible and watch.place == TRAVEL and await r.open_entries() == ()


async def test_ops_02_a_category_holds_its_pieces_at_rest_wherever_they_are() -> None:
    r = await rig()
    await r.desk.move(UID, "basket", pieces=(SOCK_L,))
    load = (await r.desk.move(UID, "load", pieces=(SOCK_L,))).load
    assert load
    got = await r.desk.blind(UID, categories=("base",))
    held = {p.id for p in (await r.view()).active() if p.hold == "blind"}
    assert SOCK_L not in held  # in the machine, not at rest: untouched
    assert {VEST_A, UNDERPANTS} <= held and got.status == "review"
    assert "private" not in got.message


async def test_ops_02_the_stated_times_are_kept_on_the_entry_and_checked() -> None:
    r = await rig()
    await r.desk.blind(UID, places=(DRAWER,), since=ist(2026, 11, 15, 18, 0))
    (entry,) = await r.open_entries()
    assert entry.since == ist(2026, 11, 15, 18, 0)
    await r.desk.blind(UID, places=(RACK,), day=date(2026, 11, 14))  # a day: 12:00 his time
    later = (await r.open_entries())[-1]
    assert later.since == ist(2026, 11, 14, 12, 0)
    with pytest.raises(Refused) as ahead:
        await r.desk.blind(UID, places=(TRAY,), since=ist(2026, 11, 16, 18, 0))
    assert str(ahead.value) == "A time can be at most 30 days back and never ahead."
    with pytest.raises(Refused):
        await r.desk.blind(UID, places=(TRAY,), day=date(2026, 10, 1))


async def test_ops_02_nothing_named_or_nothing_at_rest_is_said_plainly() -> None:
    r = await rig()
    with pytest.raises(Refused) as nothing:
        await r.desk.blind(UID)
    assert str(nothing.value) == "Name the places or the kinds of piece you moved."
    with pytest.raises(Refused) as unknown:
        await r.desk.blind(UID, places=("wl_99999999",))
    assert str(unknown.value) == "That place isn't one of yours."


async def test_ops_02_a_second_report_does_not_hold_twice() -> None:
    r = await rig()
    await r.desk.blind(UID, places=(RACK,))
    first = len(await r.open_entries())
    again = await r.desk.blind(UID, places=(RACK,))
    assert len(await r.open_entries()) == first and again.status == "already"
    assert (await r.piece(WHITE_SHIRT)).hold == "blind" and (await r.piece(BLUE_SHIRT)).hold


async def _blind_entry(r):  # type: ignore[no-untyped-def]
    return next(e for e in await r.open_entries() if e.reason == "blind")


async def test_ops_02_m4_a_piece_another_check_lets_go_is_held_again_by_the_blind_check() -> None:
    r = await rig()
    await r.desk.move(UID, "basket", one_of=(WHITE_SHIRT, TWIN))  # a pending deposit holds both
    pending = (await r.open_entries())[0]
    await r.desk.blind(UID, places=(RACK,))
    blind = await _blind_entry(r)
    assert set(blind.waiting) == {WHITE_SHIRT, TWIN} and WHITE_SHIRT not in blind.pieces
    r.clock.advance(minutes=1)
    await r.desk.resolve(UID, pending.id, "none")  # "there was no deposit"
    for pid in (WHITE_SHIRT, TWIN):  # never back to Ready unchecked: the blind check holds them
        p = await r.piece(pid)
        assert (p.state, p.hold, p.back_to) == ("review", "blind", "ready")
    blind = await _blind_entry(r)
    assert blind.waiting == () and {WHITE_SHIRT, TWIN} <= set(blind.pieces)


async def test_ops_02_m4_a_piece_he_names_for_the_basket_needs_no_blind_check() -> None:
    r = await rig()
    await r.desk.move(UID, "basket", one_of=(WHITE_SHIRT, TWIN))
    pending = (await r.open_entries())[0]
    await r.desk.blind(UID, places=(RACK,))
    r.clock.advance(minutes=1)
    await r.desk.resolve(UID, pending.id, "these", pieces=(WHITE_SHIRT,))
    assert await r.state(WHITE_SHIRT) == "in_laundry"  # his word: verified
    assert (await r.piece(TWIN)).hold == "blind"  # the other one: checked again
    blind = await _blind_entry(r)
    assert blind.waiting == () and WHITE_SHIRT not in blind.pieces and TWIN in blind.pieces


async def test_ops_02_m4_already_only_when_a_blind_check_covers_every_touched_piece() -> None:
    r = await rig()
    await r.commit(ev(BELT, "missing", r.clock()), ev(WATCH, "missing", r.clock()))
    got = await r.desk.blind(UID, places=(TRAY,))  # everything there is held elsewhere
    assert got.status == "review" and got.message == (
        "Noted: 2 pieces wait for a quick check in Helpers, Wardrobe before they're offered again."
    )
    blind = await _blind_entry(r)
    assert blind.pieces == () and set(blind.waiting) == {BELT, WATCH}
    again = await r.desk.blind(UID, places=(TRAY,))
    assert again.status == "already"
    with pytest.raises(Refused) as first:
        await r.desk.resolve(UID, blind.id, "these")
    assert str(first.value) == (
        "These pieces wait for another check first: answer that one in Helpers, Wardrobe."
    )
    r.clock.advance(minutes=1)
    for e in [e for e in await r.open_entries() if e.reason == "missing"]:
        await r.desk.resolve(UID, e.id, "these")  # where they were: still the blind check's
    assert [(await r.piece(p)).hold for p in (BELT, WATCH)] == ["blind", "blind"]
    r.clock.advance(minutes=1)
    done = await r.desk.resolve(UID, blind.id, "these", how="qr")
    assert done.message == "Done: the check is closed." and await r.open_entries() == ()
    assert [await r.state(p) for p in (BELT, WATCH)] == ["ready", "ready"]
