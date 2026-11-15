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
from __future__ import annotations

from typing import Any

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
    history = FakeData("history", [{"e": 1}])
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
        "history": {"items": [{"e": 1}]},
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
    history = await rows[privacy.HISTORY_ID].describe(UID)
    assert "title is never kept" in history.what
    device = await rows[privacy.DEVICE_ID].describe(UID)
    assert "memory only" in device.what and "closing the page" in device.what
    assert await rows[privacy.DEVICE_ID].export(UID) is None
