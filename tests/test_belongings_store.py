# tests/test_belongings_store.py -- R2 D2/D11: the Things index and history are AES-GCM under the
# `belongings` key with AAD; nothing readable in Firestore; swapped / tampered / wrong-key data is
# refused and never overwritten.
from __future__ import annotations

import pytest
from belongings_fakes import OTHER, ROOT, UID, things

from jarvis.belongings.models import MAX_HISTORY, Move
from jarvis.belongings.store import BelongingsStore, Change, ThingsUnavailable
from jarvis.keyring import Keyring
from jarvis.storage.docs import MemoryDocs

NEEDLES = ("passport", "blue file", "Neha")


async def _seed() -> tuple[MemoryDocs, BelongingsStore]:
    t = things()
    await t.svc.put(
        UID, "Passport", "the blue file on the top shelf", note="Neha's too", holder="Neha"
    )
    await t.svc.put(UID, "Passport", "the steel almirah")
    return t.docs, t.store


async def test_nothing_readable_lands_in_firestore() -> None:
    docs, _ = await _seed()
    dump = str(docs._data).lower()  # type: ignore[attr-defined]
    for needle in NEEDLES + ("almirah", "steel"):
        assert needle.lower() not in dump


async def test_round_trip_with_history_and_rev() -> None:
    _, store = await _seed()
    state = await store.load(UID)
    assert state.rev == 2 and [t.name for t in state.live()] == ["Passport"]
    (thing,) = state.live()
    assert thing.place == "the steel almirah" and thing.moves == 1
    (move,) = await store.history(UID, thing.id)
    assert move.place == "the blue file on the top shelf"


async def test_an_empty_owner_loads_an_empty_state() -> None:
    state = await things().store.load(UID)
    assert state.rev == 0 and state.things == () and state.holders == ()


async def test_another_owners_index_cannot_be_swapped_in() -> None:
    docs, store = await _seed()
    data = docs._data  # type: ignore[attr-defined]
    data["jarvis_belongings/" + OTHER] = dict(data["jarvis_belongings/" + UID])
    with pytest.raises(ThingsUnavailable):
        await store.load(OTHER)


async def test_a_history_moved_to_another_thing_is_refused() -> None:
    docs, store = await _seed()
    data = docs._data  # type: ignore[attr-defined]
    path = next(p for p in data if p.startswith("jarvis_belongings_history/"))
    bad = "jarvis_belongings_history/" + UID + "_t_aaaaaaaaaaaa"
    data[bad] = data[path]
    with pytest.raises(ThingsUnavailable):
        await store.history(UID, "t_aaaaaaaaaaaa")


async def test_a_wrong_key_and_tampering_fail_closed_and_are_not_overwritten() -> None:
    docs, _ = await _seed()
    other = BelongingsStore(docs, Keyring(bytes(range(40, 72))))
    with pytest.raises(ThingsUnavailable):
        await other.load(UID)
    with pytest.raises(ThingsUnavailable):
        await other.change(UID, lambda s: Change(s))
    again = BelongingsStore(docs, Keyring(ROOT))
    assert (await again.load(UID)).rev == 2  # still readable by the right key


async def test_storage_trouble_is_plain_and_hides_the_cause() -> None:
    class Broken(MemoryDocs):
        async def get(self, path: str) -> None:
            raise RuntimeError("firestore internal detail")

    store = BelongingsStore(Broken(), Keyring(ROOT))
    with pytest.raises(ThingsUnavailable) as e:
        await store.load(UID)
    assert "firestore" not in str(e.value)


async def test_history_keeps_the_newest_50() -> None:
    t = things()
    for i in range(MAX_HISTORY + 8):
        await t.svc.put(UID, "Keys", f"place {i}")
    (thing,) = (await t.store.load(UID)).live()
    moves = await t.store.history(UID, thing.id)
    assert len(moves) == MAX_HISTORY and moves[0].place == "place 7" and thing.moves == MAX_HISTORY


async def test_wipe_deletes_the_index_and_every_history() -> None:
    t = things()
    await t.svc.put(UID, "Keys", "hook")
    await t.svc.put(UID, "Keys", "drawer")
    assert await t.store.wipe(UID) == 1
    assert not [p for p in t.docs._data if "belongings" in p]  # type: ignore[attr-defined]


async def test_a_bad_owner_id_is_refused() -> None:
    with pytest.raises(ValueError):
        await things().store.load("../x")
    assert Move("a", "b", "c").origin == "typed"
