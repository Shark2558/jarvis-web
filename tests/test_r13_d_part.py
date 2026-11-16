# tests/test_r13_d_part.py -- R13 Part D's one join (docs/plans/r13-wardrobe.md "Part split", D20):
#   - `build(ctx)` passes I0's contract check through the real wiring: its own name, no tool, no
#     job, only the `phrases` service (R13's No-AI routers, in order) and its Privacy rows
#   - the Privacy section "Wardrobe" has D20's four rows, each over every part's WardrobeData read
#     LATE from the app (a part built after D still counts): pieces and places (A's index), the
#     laundry, outfits and wear history (every other source), the photos and fingerprints (A's
#     vault), and the device row (nothing kept on the phone; nothing to delete)
#   - counts add up, the export is each source's plain export under its name, delete (passkey)
#     empties exactly that row's sources; with nothing built the rows say so and delete nothing;
#     a source that fails makes only its row "Couldn't check right now"
#   - FAIL CLOSED (REVIEW-D-1 H3): a source is placed by its own `row`, else by its name (pieces,
#     photos; laundry and outfits are history); a source that fits no row (A's "catalog" today, a
#     typo, a row it doesn't know) lands in NO row: every server row is "Couldn't check right
#     now", nothing is counted, exported or deleted, and no row says "Nothing kept yet"
from __future__ import annotations

from typing import Any

import pytest
from r13_fakes import UID, wardrobe_context
from r13_fakes_d import FakeData, parts_with

from jarvis.api.r13_wiring import SETUP_FAILED, build_parts, check_part
from jarvis.offline.phrases_r13 import ROUTERS
from jarvis.privacy.ports import PrivacyRegistry, PrivacySource
from jarvis.wardrobe.phone import privacy
from jarvis.wardrobe.phone.part import READY, build
from jarvis.wardrobe.ports import WardrobeContext


def _ctx(parts: dict[str, Any] | None = None) -> WardrobeContext:
    return wardrobe_context(state={"r13_parts": parts} if parts is not None else {})


def _rows(ctx: WardrobeContext) -> dict[str, PrivacySource]:
    return {s.id: s for s in build(ctx).privacy}


def test_the_part_keeps_the_contract_through_the_real_wiring() -> None:
    part = check_part("phone", build(_ctx()))
    assert part.name == "phone" and part.ready == READY and part.ready != SETUP_FAILED
    assert part.tools == () and part.clock_jobs == () and part.daily_jobs == ()
    assert set(part.services) == {"phrases"} and tuple(part.services["phrases"]) == ROUTERS
    assert part.data == () and part.observers == ()
    built = build_parts(_ctx())
    assert built["phone"].ready == READY


def test_the_privacy_section_has_d20s_four_rows_in_order() -> None:
    rows = build(_ctx()).privacy
    assert [r.id for r in rows] == list(privacy.ROW_IDS)
    assert [r.label for r in rows] == [
        "Wardrobe pieces and places",
        "Laundry, outfits and wear history",
        "Wardrobe photos and fingerprints",
        "Only on this device: the Wardrobe mode's last choices",
    ]
    assert {r.section for r in rows} == {"Wardrobe"}
    assert all(isinstance(r, PrivacySource) for r in rows)


async def test_with_nothing_built_the_rows_say_so_and_delete_nothing() -> None:
    views = {v.id: v for v in await PrivacyRegistry().describe_all(UID)}
    assert views == {}
    reg = PrivacyRegistry()
    for row in build(_ctx()).privacy:
        reg.register(row)
    for view in await reg.describe_all(UID):
        assert view.available is True
        assert view.delete == "none"
        if view.id != privacy.DEVICE_ID:
            assert view.count == 0 and view.note == privacy.NOTHING_YET


async def test_the_rows_read_every_parts_data_late_and_add_it_up() -> None:
    pieces = FakeData("pieces", [{"id": "wi_000000000001"}, {"id": "wi_000000000002"}])
    history = FakeData("wardrobe_log", [{"e": 1}], row="history")  # says its row itself
    laundry = FakeData("laundry", [{"load": 1}, {"load": 2}])
    outfits = FakeData("outfits", [{"plan": 1}])
    photos = FakeData("photos", [{"photo": "wh_000000000001"}])
    parts: dict[str, Any] = {}
    rows = _rows(_ctx(parts))  # D is built before the others' data exist (the wiring's order)
    parts.update(parts_with(pieces, history, laundry, outfits, photos))
    got = {k: await r.describe(UID) for k, r in rows.items()}
    assert got[privacy.PIECES_ID].count == 2 and got[privacy.PIECES_ID].delete == "passkey"
    assert got[privacy.HISTORY_ID].count == 4 and got[privacy.HISTORY_ID].delete == "passkey"
    assert got[privacy.PHOTOS_ID].count == 1 and got[privacy.PHOTOS_ID].delete == "passkey"
    assert got[privacy.DEVICE_ID].count is None and got[privacy.DEVICE_ID].delete == "none"
    assert all(got[k].encrypted_by_jarvis for k in privacy.ROW_IDS[:3])
    exported = await rows[privacy.HISTORY_ID].export(UID)
    assert exported == {
        "wardrobe_log": {"items": [{"e": 1}]},
        "laundry": {"items": [{"load": 1}, {"load": 2}]},
        "outfits": {"items": [{"plan": 1}]},
    }
    assert await rows[privacy.PHOTOS_ID].delete(UID) == 1
    assert photos.deleted == [UID] and pieces.deleted == [] and photos.items == []
    assert (await rows[privacy.PIECES_ID].describe(UID)).count == 2  # the others untouched


async def test_a_failing_source_makes_only_its_row_unavailable() -> None:
    parts = parts_with(FakeData("pieces", [{}]), FakeData("laundry", [{}], fail=True))
    reg = PrivacyRegistry()
    for row in build(_ctx(parts)).privacy:
        reg.register(row)
    views = {v.id: v for v in await reg.describe_all(UID)}
    assert views[privacy.HISTORY_ID].available is False
    assert views[privacy.PIECES_ID].available is True and views[privacy.PIECES_ID].count == 1


async def test_the_words_say_what_is_never_kept() -> None:
    rows = _rows(_ctx(parts_with(FakeData("photos", [{}]))))
    photos = await rows[privacy.PHOTOS_ID].describe(UID)
    assert "Never for a private piece" in photos.what and "can miss" in photos.note
    assert "removes every wardrobe photo and fingerprint at once" in photos.note  # L8
    history = await rows[privacy.HISTORY_ID].describe(UID)
    assert "title is never kept" in history.what
    device = await rows[privacy.DEVICE_ID].describe(UID)
    assert "memory only" in device.what and "closing the page" in device.what
    assert await rows[privacy.DEVICE_ID].export(UID) is None


@pytest.mark.parametrize(
    "stray",
    [
        FakeData("catalog", [{"id": "wi_000000000001"}, {"photo": "wh_000000000001"}]),  # A today
        FakeData("historyy", [{"e": 1}]),  # a typo is not "history"
        FakeData("pieces", [{"e": 1}], row="everything"),  # a row it doesn't know
    ],
    ids=["catalog", "typo", "unknown_row"],
)
async def test_a_source_that_fits_no_row_lands_in_none_and_nothing_is_deleted(
    stray: FakeData,
) -> None:
    laundry, photos = FakeData("laundry", [{"load": 1}]), FakeData("photos", [{"p": 1}])
    rows = _rows(_ctx(parts_with(stray, laundry, photos)))
    reg = PrivacyRegistry()
    for row in rows.values():
        reg.register(row)
    views = {v.id: v for v in await reg.describe_all(UID)}
    for rid in privacy.ROW_IDS[:3]:  # never "Nothing kept yet", never deletable
        assert views[rid].available is False and views[rid].delete == "none", rid
        assert views[rid].note != privacy.NOTHING_YET and views[rid].count is None
        with pytest.raises(privacy.UnsortedData):
            await rows[rid].delete(UID)
        with pytest.raises(privacy.UnsortedData):
            await rows[rid].export(UID)
    assert views[privacy.DEVICE_ID].available is True
    assert stray.deleted == [] and laundry.deleted == [] and photos.deleted == []
    assert stray.items and laundry.items and photos.items


def test_each_source_finds_its_row_by_its_own_row_else_its_name() -> None:
    row_of = privacy.row_of
    assert row_of(FakeData("catalog", row="pieces")) == "pieces"  # A at I1 says its row
    assert row_of(FakeData("photos")) == "photos" and row_of(FakeData("pieces")) == "pieces"
    assert row_of(FakeData("laundry")) == row_of(FakeData("outfits")) == "history"
    assert row_of(FakeData("catalog")) is None and row_of(FakeData("history")) is None
    assert row_of(FakeData("laundry", row="photos")) == "photos"  # its own word wins
    assert row_of(FakeData("photos", row="nothing")) is None
    assert privacy.HISTORY_DATA == {"laundry", "outfits"} and privacy.ROWS == {
        "pieces",
        "history",
        "photos",
    }
