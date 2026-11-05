# tests/test_belongings_service.py -- R2 D11: put / move / where / list / history / remove + Undo /
# purge / wipe / export of "Where did I keep it?".
from __future__ import annotations

import pytest
from belongings_fakes import OTHER, UID, things

from jarvis.belongings.models import MAX_LIVE
from jarvis.belongings.service import ThingRejected, search
from jarvis.undo.models import RestoreStatus


async def test_put_adds_then_moves_and_says_the_previous_place() -> None:
    t = things()
    a = await t.svc.put(UID, "My passport", "the blue file")
    assert a.created and a.previous_place is None and not a.moved
    b = await t.svc.put(UID, "passport", "the steel almirah")
    assert b.moved and b.previous_place == "the blue file" and not b.created
    assert b.thing.id == a.thing.id
    assert [x.name for x in (await t.store.load(UID)).live()] == ["My passport"]


async def test_the_same_place_again_only_refreshes() -> None:
    t = things()
    await t.svc.put(UID, "Keys", "the hook by the door")
    again = await t.svc.put(UID, "keys", "The Hook by the door", note="spare set")
    assert not again.moved and again.thing.note == "spare set"
    thing, moves, _ = await t.svc.history(UID, "keys")
    assert moves == [] and thing.moves == 0


async def test_where_finds_by_key_synonym_and_words() -> None:
    t = things()
    await t.svc.put(UID, "Driving licence", "wallet, back pocket")
    await t.svc.put(UID, "Spectacles", "bedside table")
    await t.svc.put(UID, "Gold chain", "bank locker in Kochi")
    found, _ = await t.svc.where(UID, "my DL")
    assert found.best is not None and found.best.name == "Driving licence"
    found, _ = await t.svc.where(UID, "glasses")
    assert found.best is not None and found.best.name == "Spectacles"
    found, _ = await t.svc.where(UID, "what is in the locker")
    assert found.best is not None and found.best.name == "Gold chain"
    nothing, _ = await t.svc.where(UID, "submarine")
    assert nothing.best is None and nothing.candidates == ()


async def test_where_gives_at_most_three_candidates() -> None:
    t = things()
    for i in range(6):
        await t.svc.put(UID, f"Box {i}", "attic shelf")
    found, _ = await t.svc.where(UID, "attic")
    assert len(found.candidates) == 3


async def test_list_filters_by_holder_and_query_and_caps_at_fifty() -> None:
    t = things()
    await t.svc.put(UID, "Passport", "file", holder="Neha")
    await t.svc.put(UID, "Visa", "folder")
    mine, _ = await t.svc.list(UID, holder="neha")
    assert [x.name for x in mine] == ["Passport"]
    hit, _ = await t.svc.list(UID, q="folder")
    assert [x.name for x in hit] == ["Visa"]
    for i in range(55):
        await t.svc.put(UID, f"Item {i}", "somewhere")
    allof, _ = await t.svc.list(UID)
    assert len(allof) == 50


async def test_history_is_newest_first_and_shows_ten() -> None:
    t = things()
    for i in range(14):
        await t.svc.put(UID, "Keys", f"spot {i}")
    thing, moves, _ = await t.svc.history(UID, "keys")
    assert len(moves) == 10 and moves[0].place == "spot 12" and thing.place == "spot 13"


async def test_owners_never_see_each_other() -> None:
    t = things()
    await t.svc.put(UID, "Passport", "file")
    found, _ = await t.svc.where(OTHER, "passport")
    assert found.best is None


@pytest.mark.parametrize(
    ("name", "place", "code"),
    [
        ("", "x", "no_name"),
        ("the", "x", "no_name"),
        ("Passport", "", "no_place"),
        ("x" * 61, "y", "too_long"),
        ("Passport", "y" * 201, "too_long"),
        ("Card", "card number 4111 1111 1111 1111 in drawer", "sensitive"),
        ("Wifi", "password is hunter2hunter2", "sensitive"),
    ],
)
async def test_bad_input_is_refused_in_words(name: str, place: str, code: str) -> None:
    with pytest.raises(ThingRejected) as e:
        await things().svc.put(UID, name, place)
    assert e.value.code == code and e.value.status == 422


async def test_place_text_that_merely_says_kept_in_is_fine() -> None:
    r = await things().svc.put(UID, "Passport", "kept in the blue file")
    assert r.thing.place == "kept in the blue file"


async def test_the_live_list_is_capped() -> None:
    t = things()
    for i in range(MAX_LIVE):
        await t.svc.put(UID, f"Thing {i}", "somewhere")
    with pytest.raises(ThingRejected) as e:
        await t.svc.put(UID, "One more", "somewhere")
    assert e.value.code == "things_full" and e.value.status == 409


async def test_holders_are_capped_and_reused() -> None:
    t = things()
    for i in range(12):
        await t.svc.put(UID, f"Thing {i}", "x", holder=f"Person {i}")
    await t.svc.put(UID, "Again", "x", holder="person 3")
    assert len((await t.store.load(UID)).holders) == 12
    with pytest.raises(ThingRejected) as e:
        await t.svc.put(UID, "Over", "x", holder="Person 13")
    assert e.value.code == "holders_full"


async def test_update_renames_moves_and_keeps_history() -> None:
    t = things()
    r = await t.svc.put(UID, "Passport", "file")
    u = await t.svc.update(UID, r.thing.id, name="Indian passport", place="almirah")
    assert u.moved and u.previous_place == "file" and u.thing.key == "indian passport"
    with pytest.raises(ThingRejected) as e:
        await t.svc.update(UID, "t_000000000000", place="x")
    assert e.value.status == 404


async def test_remove_keeps_a_copy_and_undo_restores_in_place() -> None:
    t = things()
    r = await t.svc.put(UID, "Passport", "the blue file")
    thing, kept = await t.svc.remove(UID, "my passport")
    assert thing.id == r.thing.id and kept.kind == "thing" and kept.title == "Thing: Passport"
    assert kept.snapshot == {"ref": r.thing.id}  # the bin holds an id only, never a place
    assert "blue file" not in str(t.docs._data)  # type: ignore[attr-defined]
    assert (await t.svc.where(UID, "passport"))[0].best is None
    out = await t.undo.restore(UID, kept.id)
    assert out.status is RestoreStatus.RESTORED and out.new_id == r.thing.id
    assert "Restored the thing." in out.message
    assert (await t.svc.where(UID, "passport"))[0].best.place == "the blue file"  # type: ignore[union-attr]
    again = await t.undo.restore(UID, kept.id)
    assert again.status is RestoreStatus.ALREADY_RESTORED


async def test_a_restore_marked_outside_keeps_the_mark() -> None:
    t = things()
    await t.svc.put(UID, "Passport", "file")
    _, kept = await t.svc.remove(UID, "passport")
    # a delete the bin recorded as not the owner's own words restores as outside
    item = kept.model_copy(update={"owner_authored": False})
    await t.svc.restore(UID, item, outside=True)
    assert (await t.svc.where(UID, "passport"))[0].best.origin == "outside"  # type: ignore[union-attr]


async def test_remove_without_a_bin_or_with_a_failing_bin_removes_nothing() -> None:
    t = things(bin_on=False)
    await t.svc.put(UID, "Passport", "file")
    with pytest.raises(ThingRejected) as e:
        await t.svc.remove(UID, "passport")
    assert e.value.code == "no_bin"
    t2 = things()
    await t2.svc.put(UID, "Passport", "file")

    async def boom(item: object) -> None:
        raise RuntimeError("down")

    t2.undo.store.add = boom  # type: ignore[method-assign]
    with pytest.raises(ThingRejected) as e2:
        await t2.svc.remove(UID, "passport")
    assert e2.value.code == "not_kept"
    assert (await t2.svc.where(UID, "passport"))[0].best is not None


async def test_remove_unknown_is_404() -> None:
    with pytest.raises(ThingRejected) as e:
        await things().svc.remove(UID, "unicorn")
    assert e.value.status == 404


async def test_purge_deletes_for_good_and_is_repeatable() -> None:
    t = things()
    await t.svc.put(UID, "Keys", "hook")
    await t.svc.put(UID, "Keys", "drawer")
    _, kept = await t.svc.remove(UID, "keys")
    assert await t.undo.purge(UID, kept.id) is True
    assert not [p for p in t.docs._data if "belongings_history" in p]  # type: ignore[attr-defined]
    assert (await t.store.load(UID)).things == ()
    await t.svc.purge(UID, kept)  # again: nothing to do, no error


async def test_restore_after_purge_says_so() -> None:
    t = things()
    await t.svc.put(UID, "Keys", "hook")
    _, kept = await t.svc.remove(UID, "keys")
    await t.svc.purge(UID, kept)
    with pytest.raises(ThingRejected) as e:
        await t.svc.restore(UID, kept)
    assert e.value.status == 410


async def test_export_and_wipe() -> None:
    t = things()
    await t.svc.put(UID, "Keys", "hook", holder="Neha")
    await t.svc.put(UID, "Keys", "drawer")
    out = await t.svc.export(UID)
    assert out["things"][0]["place"] == "drawer" and out["things"][0]["holder"] == "Neha"
    assert out["things"][0]["history"][0]["place"] == "hook"
    assert await t.svc.wipe(UID) == 1
    assert (await t.svc.export(UID))["things"] == []


def test_search_ignores_deleted_things() -> None:
    from jarvis.belongings.models import Thing

    gone = Thing("t_000000000001", "Passport", "passport", "file", "2026-11-05", deleted_at="x")
    assert search([gone], "passport").best is None
