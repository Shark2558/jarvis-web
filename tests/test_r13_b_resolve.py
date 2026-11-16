# tests/test_r13_b_resolve.py -- R13 Part B (docs/plans/r13-wardrobe.md D11, D4.4): every kind of
# review entry answered. A stale check (C's quick check, through B's writer) and its "check this
# place" fold confirm a sighting or a new place; a conflict and a "which one?" are noted; A's holds
# (`restored`, `missing`) come back by his word; an answer that doesn't fit the entry is refused in
# plain words. Fixed clocks only.
from __future__ import annotations

import pytest
from r13_fakes import UID, ev
from r13_fakes_b import (
    BELT,
    BLUE_SHIRT,
    DRAWER,
    RACK,
    TEE,
    TRAVEL,
    TRAY,
    TWIN,
    WATCH,
    WHITE_SHIRT,
    rig,
)

from jarvis.storage.docs import DocTx
from jarvis.tools.gateway import GatewayOutcome
from jarvis.wardrobe.laundry import review
from jarvis.wardrobe.laundry.holds import admit
from jarvis.wardrobe.model import WardrobeView
from jarvis.wardrobe.ports import Commit, Refused, ReviewNeeded


async def _stale(r, *pids: str) -> None:  # type: ignore[no-untyped-def]
    async def fn(view: WardrobeView, tx: DocTx) -> Commit:
        needs = [ReviewNeeded("stale", p, reason="stale") for p in pids]
        return Commit(extra=tuple(await r.writer.entries(UID, view, tx, needs)))

    await r.store.transact(UID, fn)


async def test_a_stale_check_is_answered_by_a_sighting_where_it_is_or_a_new_place() -> None:
    r = await rig()
    await _stale(r, BELT, WATCH)
    belt, watch = await r.open_entries()
    assert belt.place == TRAY and belt.pieces == ()  # a stale check holds nothing
    seen = await r.desk.resolve(UID, belt.id, "these", how="qr")
    assert seen.status == "done" and await r.state(BELT) == "ready"
    kinds = [(h.event.kind, h.event.evidence.how) for h in await r.store.history(UID, BELT)]
    assert kinds[-1] == ("seen", "qr")  # the verified sighting is in his history
    await r.desk.resolve(UID, watch.id, "moved", place=TRAVEL)
    assert (await r.piece(WATCH)).place == TRAVEL and await r.open_entries() == ()


async def test_a_stale_check_may_be_dismissed_and_a_second_need_is_merged() -> None:
    r = await rig()
    await _stale(r, BELT)
    await _stale(r, BELT)  # C asks again: covered, never twice
    (entry,) = await r.open_entries()
    await r.desk.resolve(UID, entry.id, "dismiss")
    assert await r.open_entries() == () and await r.state(BELT) == "ready"


async def test_a_place_check_is_answered_piece_by_piece() -> None:
    r = await rig()
    await _stale(r, BELT, WATCH)
    doc = await r.review()
    folded = review._fold(doc, review.open_entries(doc), TRAY, r.clock())  # noqa: SLF001
    await r.docs.write([r.desk.store.review_op(UID, folded, r.clock())])
    (place,) = await r.open_entries()
    assert place.kind == "place" and set(place.candidates) == {BELT, WATCH}
    assert review.words_of(place) == "Check this place: several pieces wait for a quick check."
    part = await r.desk.resolve(UID, place.id, "these", pieces=(BELT,))
    assert part.message == "Done: 1 piece checked; 1 still waits."
    (left,) = await r.open_entries()
    assert left.candidates == (WATCH,)


async def test_a_conflict_is_noted_and_nothing_moves() -> None:
    r = await rig()
    await r.commit(ev(TEE, "dried", r.clock()))
    (entry,) = await r.open_entries()
    done = await r.desk.resolve(UID, entry.id, "dismiss")
    assert done.message == "Done: the check is closed." and await r.state(TEE) == "ready"


async def test_a_which_one_may_be_closed_without_a_choice() -> None:
    r = await rig()
    await r.desk.move(UID, "basket", pieces=(WHITE_SHIRT, TWIN))
    await r.desk.move(UID, "ready", query="white shirt")
    (entry,) = await r.open_entries()
    await r.desk.resolve(UID, entry.id, "none")
    assert await r.open_entries() == ()
    assert [await r.state(p) for p in (WHITE_SHIRT, TWIN)] == ["in_laundry", "in_laundry"]


async def test_as_restored_and_missing_holds_come_back_by_his_word() -> None:
    r = await rig()
    await r.commit(ev(BELT, "archived", r.clock()))
    r.clock.advance(minutes=1)
    await r.commit(ev(BELT, "restored", r.clock()))  # INV-17: in review until its condition
    await r.commit(ev(WATCH, "missing", r.clock()))
    restored, missing = await r.open_entries()
    assert review.words_of(restored) == "Back from the archive: check its condition."
    r.clock.advance(minutes=1)
    await r.desk.resolve(UID, restored.id, "these")
    await r.desk.resolve(UID, missing.id, "moved", to="ready", place=DRAWER)
    assert await r.state(BELT) == "ready"
    watch = await r.piece(WATCH)
    assert watch.state == "ready" and watch.place == DRAWER


async def test_a_pending_deposit_with_no_candidates_takes_the_piece_he_names() -> None:
    r = await rig()
    await r.desk.move(UID, "basket", pieces=(TEE,), more=1, category="footwear")
    (entry,) = await r.open_entries()
    from r13_fakes_b import SHOE_L

    await r.desk.resolve(UID, entry.id, "these", pieces=(SHOE_L,))
    assert await r.state(SHOE_L) == "in_laundry"


@pytest.mark.parametrize(
    ("outcome", "words"),
    [
        ("moved", "That answer doesn't fit this check."),
        ("dismiss", "That answer doesn't fit this check."),
    ],
)
async def test_an_answer_that_does_not_fit_is_refused(outcome: str, words: str) -> None:
    r = await rig()
    await r.desk.move(UID, "basket", one_of=(WHITE_SHIRT, TWIN))
    (entry,) = await r.open_entries()
    with pytest.raises(Refused) as no:
        await r.desk.resolve(UID, entry.id, outcome)  # type: ignore[arg-type]
    assert str(no.value) == words


async def test_none_is_only_for_an_unconfirmed_change_and_moved_needs_a_state() -> None:
    r = await rig()
    await r.commit(ev(WATCH, "missing", r.clock()))
    (entry,) = await r.open_entries()
    with pytest.raises(Refused) as none:
        await r.desk.resolve(UID, entry.id, "none")
    assert str(none.value) == "That answer doesn't fit this check."
    with pytest.raises(Refused) as moved:
        await r.desk.resolve(UID, entry.id, "moved")
    assert str(moved.value) == "Say where it is now: a state and, if you like, a place."


async def test_a_pick_for_these_needs_a_piece_and_one_the_check_names() -> None:
    r = await rig()
    await r.desk.move(UID, "basket", pieces=(WHITE_SHIRT, TWIN))
    await r.desk.move(UID, "ready", query="white shirt")
    (entry,) = await r.open_entries()
    with pytest.raises(Refused):
        await r.desk.resolve(UID, entry.id, "these")
    with pytest.raises(Refused):
        await r.desk.resolve(UID, entry.id, "these", pieces=(BLUE_SHIRT,))


async def test_the_unverified_change_resolved_as_his_word_keeps_its_place() -> None:
    r = await rig()
    move = ev(TEE, "deposited", r.clock(), source="camera", place=RACK)
    await r.commit(admit(move))
    (entry,) = await r.open_entries()
    await r.desk.resolve(UID, entry.id, "these")
    assert await r.state(TEE) == "in_laundry"


async def _rescan(r, pid: str, reason: str) -> None:  # type: ignore[no-untyped-def]
    """A's fold asks for a rescan (r13-a `catalog/fold.py`: a correction made later steps clash)."""

    async def fn(view: WardrobeView, tx: DocTx) -> Commit:
        need = ReviewNeeded("rescan", pid, "we_" + pid[-8:] * 2 + "aaaa", reason=reason)
        return Commit(extra=tuple(await r.writer.entries(UID, view, tx, (need,))))

    await r.store.transact(UID, fn)


async def test_h1_as_rescan_answered_these_is_a_sighting_never_a_clean_return() -> None:
    r = await rig()
    await r.desk.move(UID, "basket", pieces=(BLUE_SHIRT,))
    r.clock.advance(minutes=5)
    await _rescan(r, BLUE_SHIRT, "corrected")
    (entry,) = await r.open_entries()
    assert review.words_of(entry) == "Two later steps disagree: check this piece."
    before = len(await r.store.history(UID, BLUE_SHIRT))
    r.clock.advance(minutes=1)
    got = await r.desk.resolve(UID, entry.id, "these", pieces=(BLUE_SHIRT,))
    assert got.message == "Done: the check is closed." and await r.open_entries() == ()
    assert await r.state(BLUE_SHIRT) == "in_laundry"  # still dirty: never Ready by a check
    added = [h.event.kind for h in await r.store.history(UID, BLUE_SHIRT)][before:]
    assert added == ["seen"]  # a sighting where it is, and nothing else


async def test_h1_any_other_rescan_is_a_check_that_may_be_moved_or_dismissed() -> None:
    r = await rig()
    await r.desk.move(UID, "basket", pieces=(BLUE_SHIRT, TEE))
    await _rescan(r, BLUE_SHIRT, "which")  # another part's "which": no step of B's
    await _rescan(r, TEE, "")
    which, plain = await r.open_entries()
    assert review.words_of(plain) == "A quick check, please: is this piece where JARVIS thinks?"
    r.clock.advance(minutes=1)
    await r.desk.resolve(UID, which.id, "moved", pieces=(BLUE_SHIRT,), place=DRAWER)
    shirt = await r.piece(BLUE_SHIRT)
    assert shirt.state == "in_laundry" and shirt.place == DRAWER
    await r.desk.resolve(UID, plain.id, "dismiss")
    assert await r.open_entries() == () and await r.state(TEE) == "in_laundry"


def test_h1_a_which_entry_without_its_step_takes_no_laundry_step() -> None:
    from r13_fakes import ist

    from jarvis.wardrobe.laundry import resolve
    from jarvis.wardrobe.laundry.store import Entry, LaundryDoc

    now = ist(2026, 11, 16, 9, 0)
    lost = Entry(id="rv_" + "0" * 10, kind="rescan", reason="which", candidates=(TEE,),
                 opened_at=now)  # fmt: skip
    with pytest.raises(Refused) as no:
        ask = resolve._Ask("these", (TEE,), None, None, "tap", {}, now)  # noqa: SLF001
        resolve._which(WardrobeView(uid=UID), LaundryDoc(), lost, ask)  # noqa: SLF001
    assert str(no.value) == "That answer doesn't fit this check."


async def _hold_without_entry(r, event) -> None:  # type: ignore[no-untyped-def]
    """A hold whose entry is gone (what A's 04:00 sweep repairs): no writer for one commit."""
    r.store.bind(review_writer=None, observers=[r.observer])
    await r.commit(event)
    r.store.bind(review_writer=r.writer, observers=[r.observer])


async def _sweep(r, pid: str) -> None:  # type: ignore[no-untyped-def]
    """A's repair as on r13-a (`catalog/jobs.py`): the entry's reason is "sweep"."""
    back = (await r.piece(pid)).back_to

    async def fn(view: WardrobeView, tx: DocTx) -> Commit:
        need = ReviewNeeded("hold", pid, back_to=back, reason="sweep")
        return Commit(extra=tuple(await r.writer.entries(UID, view, tx, (need,))))

    await r.store.transact(UID, fn)


async def test_h2_a_hold_the_sweep_repaired_is_released_by_these() -> None:
    r = await rig()
    await _hold_without_entry(r, ev(WHITE_SHIRT, "held", r.clock()))
    await _sweep(r, WHITE_SHIRT)
    (entry,) = await r.open_entries()
    assert entry.reason == "sweep" and (await r.piece(WHITE_SHIRT)).hold == "held"
    r.clock.advance(minutes=1)
    got = await r.desk.resolve(UID, entry.id, "these")
    assert got.message == "Done: the check is closed." and await r.state(WHITE_SHIRT) == "ready"
    assert await r.open_entries() == ()


@pytest.mark.parametrize(("outcome", "state"), [("none", "ready"), ("these", "in_laundry")])
async def test_h2_a_sweep_repaired_unverified_change_keeps_none_and_its_confirm(
    outcome: str, state: str
) -> None:
    r = await rig()
    await _hold_without_entry(r, admit(ev(TEE, "deposited", r.clock(), source="camera")))
    await _sweep(r, TEE)
    (entry,) = await r.open_entries()
    assert entry.events == () and (await r.piece(TEE)).hold == "unverified"
    r.clock.advance(minutes=1)
    await r.desk.resolve(UID, entry.id, outcome)  # type: ignore[arg-type]
    assert await r.state(TEE) == state and await r.open_entries() == ()


async def test_h2_a_hold_answered_another_way_never_says_done() -> None:
    r = await rig()
    await r.commit(ev(WATCH, "missing", r.clock()))
    (entry,) = await r.open_entries()
    r.clock.advance(minutes=1)
    await r.commit(ev(WATCH, "found", r.clock(), to="ready"))  # a scan found it meanwhile
    got = await r.desk.resolve(UID, entry.id, "these")
    assert got.message == "Nothing to change: it was answered another way. The check is closed."
    assert await r.open_entries() == () and await r.state(WATCH) == "ready"


async def test_m3_a_check_never_lands_a_piece_at_the_shop_without_a_batch() -> None:
    r = await rig()
    await r.commit(ev(BLUE_SHIRT, "missing", r.clock()))
    (entry,) = await r.open_entries()
    with pytest.raises(Refused) as no:
        await r.desk.resolve(UID, entry.id, "moved", to="with_provider")
    assert str(no.value) == (
        "A piece goes to an outside laundry only with 'send out', so it has its batch."
    )
    bad = await r.tool(
        "laundry_review", action="resolve", entry=entry.id, outcome="moved", to="with_provider"
    )
    assert bad.outcome is GatewayOutcome.ERROR and await r.state(BLUE_SHIRT) == "review"


def test_needs_from_another_part_still_become_entries() -> None:
    from r13_fakes import ist

    from jarvis.wardrobe.laundry.store import ReviewDoc
    from jarvis.wardrobe.model import WardrobeView

    now = ist(2026, 11, 16, 9, 0)
    view = WardrobeView(uid=UID)
    doc = review.add_needs(
        ReviewDoc(),
        [
            ReviewNeeded("pending_deposit", None, candidates=(BELT, WATCH)),
            ReviewNeeded("rescan", BELT, reason="blind"),
            ReviewNeeded("rescan", WATCH),
        ],
        view,
        now,
    )
    kinds = [(e.kind, e.reason, e.pieces, e.candidates) for e in doc.entries]
    assert kinds == [
        ("pending_deposit", "pending", (), (BELT, WATCH)),
        ("rescan", "blind", (BELT,), (BELT,)),
        ("rescan", "rescan", (), (WATCH,)),
    ]
