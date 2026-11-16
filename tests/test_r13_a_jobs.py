# tests/test_r13_a_jobs.py -- R13 Part A (docs/plans/r13-wardrobe.md D3, D4.4, D20, e2e 8; STY-17's
# sweep): `wardrobe_sweep` closes a forgotten wear from 04:00 HIS local time (never before, never a
# wear started after local midnight; tested at 23:30, 00:30, 03:30 and 04:30 IST), gives a hold
# without its entry one through B's writer; the Privacy data (count, a plain export without photos,
# delete everything); the pilot's counts and pass line. Every clock is fixed.
from __future__ import annotations

import json
from typing import Any

import pytest
from r13_fakes import UID, FixedClock, RecordingWriter, ev, ist
from r13_fakes_a import Catalog, catalog, fp, jpeg

from jarvis.wardrobe.catalog import jobs as sweep_module
from jarvis.wardrobe.catalog.edits import NewPiece
from jarvis.wardrobe.ports import Commit


def desk(cat: Catalog) -> Any:
    return cat.store.desk  # type: ignore[attr-defined]


async def _commit(cat: Catalog, *events: Any) -> None:
    async def fn(view: object, tx: object) -> Commit:
        return Commit(events=tuple(events))

    await cat.store.transact(UID, fn)


async def _worn_since(cat: Catalog, at: Any) -> tuple[str, str]:
    shirt, belt = (
        await desk(cat).service.add(UID, [NewPiece(type="shirt"), NewPiece(type="belt")])
    ).ids
    await _commit(cat, ev(shirt, "wear_started", at), ev(belt, "wear_started", at))
    return shirt, belt


def _sweep(cat: Catalog, *, closer: bool = True) -> Any:
    """The sweep, joined as the wiring joins it: C's checked rules close a forgotten wear."""
    from jarvis.api.r13_wiring import sweep_closer
    from jarvis.wardrobe.styling.rules import load_rules

    [job] = cat.part.daily_jobs
    job.closer = sweep_closer(cat.store, load_rules()) if closer else None
    return job


# ---- a forgotten wear (STY-17, H1) ---
async def test_a_wear_started_last_evening_is_closed_from_four_by_the_rewear_rule() -> None:
    cat = catalog(clock=FixedClock(ist(2026, 11, 16, 20, 0)))
    shirt, belt = await _worn_since(cat, cat.clock())
    cat.clock.set(ist(2026, 11, 17, 4, 30))
    got = await _sweep(cat).run([UID])
    assert got == {"owners": 1, "closed": 2, "holds": 0, "failed": 0}
    view = await cat.store.view(UID)
    assert (view.pieces[shirt].state, view.pieces[belt].state) == ("in_laundry", "ready")
    assert (view.pieces[shirt].wears, view.pieces[belt].wears) == (1, 1)
    again = await _sweep(cat).run([UID])  # one wear, never two
    assert again["closed"] == 0 and (await cat.store.view(UID)).pieces[shirt].wears == 1


@pytest.mark.parametrize(
    ("started", "swept"),
    [
        (ist(2026, 11, 16, 20, 0), ist(2026, 11, 17, 3, 30)),  # before 04:00: he may still be out
        (ist(2026, 11, 17, 0, 30), ist(2026, 11, 17, 4, 30)),  # started after local midnight
        (ist(2026, 11, 16, 20, 0), ist(2026, 11, 16, 23, 30)),  # the same evening
        (ist(2026, 11, 16, 23, 30), ist(2026, 11, 17, 0, 30)),  # half an hour later
    ],
)
async def test_a_wear_is_left_open_before_four_or_when_it_began_after_midnight(
    started: Any, swept: Any
) -> None:
    cat = catalog(clock=FixedClock(started))
    shirt, _ = await _worn_since(cat, started)
    cat.clock.set(swept)
    assert (await _sweep(cat).run([UID]))["closed"] == 0
    assert (await cat.store.view(UID)).pieces[shirt].state == "in_use"


def test_the_rewear_rule_has_one_source_and_it_is_parts_cs() -> None:
    """Workshop decision 1: A keeps no copy of the rewear rule (no WORN_AGAIN, no after_wear)."""
    assert not hasattr(sweep_module, "WORN_AGAIN") and not hasattr(sweep_module, "after_wear")


async def test_a_forgotten_wear_closes_by_cs_rule_a_festive_layer_stays_ready() -> None:
    cat = catalog(clock=FixedClock(ist(2026, 11, 16, 20, 0)))
    [layer, tee] = (
        await desk(cat).service.add(UID, [NewPiece(type="festive_layer"), NewPiece(type="t_shirt")])
    ).ids
    await _commit(cat, ev(layer, "wear_started", cat.clock()), ev(tee, "wear_started", cat.clock()))
    cat.clock.set(ist(2026, 11, 17, 4, 30))
    assert (await _sweep(cat).run([UID]))["closed"] == 2
    view = await cat.store.view(UID)
    assert (view.pieces[layer].state, view.pieces[tee].state) == ("ready", "in_laundry")
    assert (await _sweep(cat).run([UID]))["closed"] == 0  # once


async def test_without_the_styling_part_the_sweep_closes_nothing_and_goes_on() -> None:
    cat = catalog(clock=FixedClock(ist(2026, 11, 16, 20, 0)))
    shirt, _ = await _worn_since(cat, cat.clock())
    cat.clock.set(ist(2026, 11, 17, 4, 30))
    got = await _sweep(cat, closer=False).run([UID])
    assert got == {"owners": 1, "closed": 0, "holds": 0, "failed": 0}
    assert (await cat.store.view(UID)).pieces[shirt].state == "in_use"


async def test_a_hold_without_its_entry_is_handed_to_bs_writer_again() -> None:
    cat = catalog()
    writer = RecordingWriter()
    cat.store.bind(review_writer=writer)
    [shirt] = (await desk(cat).service.add(UID, [NewPiece(type="shirt")])).ids
    await _commit(cat, ev(shirt, "held", cat.clock()))
    writer.needed.clear()  # say the entry was lost
    got = await _sweep(cat).run([UID])
    assert got["holds"] == 1
    [(need,)] = writer.needed
    assert (need.kind, need.piece, need.back_to, need.reason) == (
        "hold",
        shirt,
        "ready",
        "held",
    )  # its own hold, so the words say why


async def test_one_owner_that_cannot_be_read_never_stops_the_others() -> None:
    cat = catalog()
    await desk(cat).service.add(UID, [NewPiece(type="shirt")])
    got = await _sweep(cat).run(["../bad", UID])
    assert got["failed"] == 1 and got["owners"] == 2


# ---- the Privacy data (D20) ---
async def test_the_export_is_plain_json_without_photos_or_fingerprints() -> None:
    cat = catalog()
    [shirt] = (await desk(cat).service.add(UID, [NewPiece(type="shirt", label="Office shirt")])).ids
    await desk(cat).vault.save(UID, shirt, "front", jpeg())
    await desk(cat).vault.prints.save(UID, shirt, "front", "mnv2-int8-1", fp(5))
    data, photos = cat.part.data
    assert (data.name, data.row, await data.count(UID)) == ("pieces", "pieces", 1)
    assert (photos.name, photos.row, await photos.count(UID)) == ("photos", "photos", 1)
    out = await data.export(UID)
    text = json.dumps(out)
    assert "Office shirt" in text and fp(5)[:30] not in text and "wh_" not in text
    assert [e["kind"] for e in out["history"][shirt]] == ["registered"]


async def test_delete_everything_leaves_nothing_of_his_in_the_catalogs_collections() -> None:
    cat = catalog()
    [shirt] = (await desk(cat).service.add(UID, [NewPiece(type="shirt")])).ids
    await desk(cat).vault.save(UID, shirt, "front", jpeg())
    await desk(cat).vault.prints.save(UID, shirt, "front", "mnv2-int8-1", fp(5))
    data, _ = cat.part.data
    assert await data.delete(UID) == 1
    left = [p for p in cat.docs._data if UID in p]  # noqa: SLF001 - every stored path
    assert left == []
    assert (await cat.store.view(UID)).pieces == {}


async def test_deleting_the_photos_row_leaves_the_catalog_usable_and_says_nothing_of_bytes() -> (
    None
):
    """INTEGRATION-D 6.4 and e2e 7: the "photos" row drops photos and fingerprints only."""
    cat = catalog()
    [shirt] = (await desk(cat).service.add(UID, [NewPiece(type="shirt", label="Office")])).ids
    await desk(cat).vault.save(UID, shirt, "front", jpeg())
    await desk(cat).vault.prints.save(UID, shirt, "front", "mnv2-int8-1", fp(5))
    data, photos = cat.part.data
    exported = json.dumps(await photos.export(UID))
    assert "wh_" not in exported and fp(5)[:30] not in exported
    assert await photos.delete(UID) == 1 and await photos.count(UID) == 0
    view = await cat.store.view(UID)
    assert view.pieces[shirt].photos == () and view.pieces[shirt].label == "Office"
    assert await data.count(UID) == 1  # the catalog stays
    assert await desk(cat).vault.prints.items(UID, "mnv2-int8-1") == ()


# ---- the pilot's counts (e2e 8) ---
async def test_the_pilot_counts_candidates_choices_and_state_corrections() -> None:
    cat = catalog()
    shirt, vest = (
        await desk(cat).service.add(UID, [NewPiece(type="shirt"), NewPiece(type="vest")])
    ).ids
    cat.clock.advance(minutes=1)
    dep = ev(shirt, "deposited", cat.clock(), how="match", score=0.91, source="phone")
    await _commit(cat, dep, ev(vest, "seen", cat.clock(), how="tap", score=0.62, source="phone"))
    cat.clock.advance(minutes=1)
    await cat.store.correct(UID, shirt, dep.id)
    got = await desk(cat).pilot.counts(UID)
    assert (got.scans_with_candidate, got.first_candidate_chosen) == (2, 1)
    assert (got.events, got.state_corrections) == (5, 1)
    # Part C keeps no log of what each suggestion named: not measured in v13.0.0 (None, never 0)
    assert (got.suggested, got.unavailable_suggested) == (None, None)
