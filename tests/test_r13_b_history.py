# tests/test_r13_b_history.py -- R13 Part B (docs/plans/r13-wardrobe.md D11, LND-15): one piece's
# history shows its verified events, the corrections and the current step. "Where is my white
# shirt" shows Drying and its latest verified movement. Every sentence with a time is asserted
# WHOLE from a fixed clock, also at 23:30 and 00:30 IST (D15: no date bombs).
from __future__ import annotations

import pytest
from r13_fakes import IST, UID, ev, ist
from r13_fakes_b import RACK, TWIN, WHITE_SHIRT, rig

from jarvis.wardrobe.laundry import history
from jarvis.wardrobe.laundry.holds import admit


async def test_lnd_15_where_is_my_white_shirt_shows_drying_and_its_latest_verified_move() -> None:
    r = await rig(twin=False)
    await r.desk.move(UID, "basket", pieces=(WHITE_SHIRT,))
    r.clock.advance(hours=1)
    load = (await r.desk.move(UID, "load", pieces=(WHITE_SHIRT,))).load
    r.clock.advance(hours=1, minutes=4)  # 11:05 IST
    await r.desk.move(UID, "drying", load=load)
    r.clock.advance(minutes=30)
    late = ev(WHITE_SHIRT, "deposited", ist(2026, 11, 16, 10, 30), source="camera")
    await r.commit(admit(late))  # an old, unverified basket message delivered late
    got = await r.desk.history(UID, query="white shirt")
    assert got["state"] == "drying" and got["state_words"] == "Drying"
    assert got["step"] == "Drying since 11:05"
    assert got["latest_verified"] == {"kind": "dried", "at": "11:05", "words": "Drying"}
    kinds = [(e["kind"], e["mark"]) for e in got["events"]]
    assert kinds[-1] == ("dried", "applied")
    assert ("deposited", "superseded") in kinds and await r.open_entries() == ()


async def test_lnd_15_a_correction_is_shown_with_what_it_struck_out() -> None:
    r = await rig()
    dirty = await r.desk.move(UID, "basket", pieces=(WHITE_SHIRT,))
    r.clock.advance(minutes=5)
    await r.desk.correct(UID, WHITE_SHIRT, dirty.committed.events[0].id)
    got = await r.desk.history(UID, piece=WHITE_SHIRT)
    assert got["state"] == "ready" and got["corrections"] == 1
    marks = [(e["kind"], e["mark"]) for e in got["events"]]
    assert ("deposited", "voided") in marks and ("corrected", "applied") in marks


async def test_lnd_15_a_name_that_fits_two_pieces_is_never_a_guess() -> None:
    r = await rig()
    got = await r.desk.history(UID, query="white shirt")
    assert got["found"] is False and set(got["candidates"]) == {WHITE_SHIRT, TWIN}


@pytest.mark.parametrize(
    ("then", "now", "words"),
    [
        (ist(2026, 11, 16, 14, 5), ist(2026, 11, 16, 23, 30), "since 14:05"),
        (ist(2026, 11, 16, 23, 10), ist(2026, 11, 17, 0, 30), "since yesterday 23:10"),
        (ist(2026, 11, 17, 0, 10), ist(2026, 11, 17, 0, 30), "since 00:10"),
        (ist(2026, 11, 14, 9, 0), ist(2026, 11, 17, 0, 30), "since Sat 14 Nov 09:00"),
        (ist(2026, 12, 31, 23, 50), ist(2027, 1, 1, 0, 30), "since yesterday 23:50"),
    ],
)
def test_since_words_use_his_local_day_at_the_midnight_edges(then, now, words) -> None:  # type: ignore[no-untyped-def]
    assert history.since_words(then, now, IST) == words


async def test_lnd_15_place_and_return_words_come_from_his_places() -> None:
    r = await rig(twin=False)
    await r.desk.move(UID, "basket", pieces=(WHITE_SHIRT,))
    await r.desk.move(UID, "ready", pieces=(WHITE_SHIRT,), place=RACK)
    got = await r.desk.history(UID, piece=WHITE_SHIRT)
    assert got["state"] == "ready" and got["place"] == "Shirt rack"
    assert got["step"] == "Ready since 09:01"


async def test_l11_the_latest_verified_step_says_where_it_really_went() -> None:
    r = await rig()
    await r.desk.move(UID, "basket", pieces=(WHITE_SHIRT,))  # in the basket, at the shirt rack
    await r.desk.blind(UID, places=(RACK,))
    blind = next(e for e in await r.open_entries() if e.reason == "blind")
    r.clock.advance(minutes=1)  # 09:02
    await r.desk.resolve(UID, blind.id, "these", pieces=(WHITE_SHIRT,))  # still in the basket
    got = await r.desk.history(UID, piece=WHITE_SHIRT)
    assert got["state"] == "in_laundry"
    assert got["latest_verified"] == {"kind": "released", "at": "09:02", "words": "In laundry"}
    r.clock.advance(minutes=1)
    await r.commit(ev(WHITE_SHIRT, "returned", r.clock(), source="camera", verified=False))
    got = await r.desk.history(UID, piece=WHITE_SHIRT)  # an unconfirmed change holds it since
    assert got["state"] == "review" and got["latest_verified"]["words"] == (
        "Back as it was before its check"
    )
