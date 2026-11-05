# tests/test_kb_store.py -- R2 C: notes on the Docs port, encrypted by JARVIS (D2), sharded by size.
from __future__ import annotations

from datetime import UTC, datetime

import pytest
from kb_fakes import OTHER, ROOT_KEY, UID, scan

from jarvis.kb.models import MAX_TEXT, Note, NotesError
from jarvis.kb.store import SHARD_CIPHER_MAX, NotesStore
from jarvis.keyring import Keyring
from jarvis.storage.docs import MemoryDocs

AT = datetime(2026, 11, 3, tzinfo=UTC)


def mk(i: int, text: str = "hello", **over: object) -> Note:
    base: dict[str, object] = {
        "id": f"n_{i:012x}",
        "kind": "note",
        "title": f"title {i}",
        "text": text,
        "origin": "typed",
        "created_at": AT,
        "updated_at": AT,
    }
    base.update(over)
    return Note(**base)  # type: ignore[arg-type]


def rig() -> tuple[MemoryDocs, NotesStore]:
    docs = MemoryDocs()
    return docs, NotesStore(docs, Keyring(ROOT_KEY))


def add(*notes: Note):  # type: ignore[no-untyped-def]
    def fn(cur: tuple[Note, ...]) -> tuple[tuple[Note, ...], int]:
        return (*cur, *notes), len(notes)

    return fn


async def test_empty_owner_has_no_notes_and_costs_one_read() -> None:
    docs, store = rig()
    state = await store.load(UID)
    assert state.notes == () and docs.reads == 1


async def test_change_then_load_round_trips_and_warm_load_is_one_read() -> None:
    docs, store = rig()
    state, n = await store.change(UID, add(mk(1), mk(2)))
    assert n == 2 and [x.id for x in state.notes] == [mk(1).id, mk(2).id]
    docs.reads = 0
    again = await store.load(UID)
    assert again.notes == state.notes and docs.reads == 1
    fresh = NotesStore(docs, Keyring(ROOT_KEY))  # another process: cold start
    assert (await fresh.load(UID)).notes == state.notes


async def test_nothing_readable_is_stored_in_firestore() -> None:
    docs, store = rig()
    await store.change(UID, add(mk(1, "the plumber is RAVIKUMAR", tags=("zzneedle",))))
    assert scan(docs, "RAVIKUMAR", "zzneedle", "title 1", "plumber") == []
    assert set(docs._data) == {f"jarvis_kb/{UID}", f"jarvis_kb_shards/{UID}_s0"}
    header = docs._data[f"jarvis_kb/{UID}"]
    assert header["counts"] == {"note": 1, "memo": 0, "link": 0, "deleted": 0}


async def test_another_owner_never_sees_it_and_a_moved_shard_does_not_open() -> None:
    docs, store = rig()
    await store.change(UID, add(mk(1)))
    assert (await store.load(OTHER)).notes == ()
    # an attacker copies the owner's header and shard under another owner's paths
    docs._data[f"jarvis_kb/{OTHER}"] = dict(docs._data[f"jarvis_kb/{UID}"])
    docs._data[f"jarvis_kb_shards/{OTHER}_s0"] = dict(docs._data[f"jarvis_kb_shards/{UID}_s0"])
    with pytest.raises(NotesError) as e:
        await NotesStore(docs, Keyring(ROOT_KEY)).load(OTHER)
    assert e.value.code == "notes_unavailable"


async def test_a_wrong_key_or_tampered_blob_fails_closed_and_is_never_overwritten() -> None:
    docs, store = rig()
    await store.change(UID, add(mk(1)))
    path = f"jarvis_kb_shards/{UID}_s0"
    good = dict(docs._data[path])
    other_key = Keyring(bytes(range(40, 72)))
    with pytest.raises(NotesError):
        await NotesStore(docs, other_key).load(UID)
    docs._data[path]["blob"] = good["blob"][:-4] + "AAAA"
    cold = NotesStore(docs, Keyring(ROOT_KEY))
    with pytest.raises(NotesError):
        await cold.load(UID)
    with pytest.raises(NotesError):
        await cold.change(UID, add(mk(2)))
    assert docs._data[path]["blob"] != good["blob"]  # untouched: still the tampered one
    docs._data[path] = good
    assert len((await cold.load(UID)).notes) == 1


async def test_a_change_that_raises_writes_nothing() -> None:
    docs, store = rig()
    await store.change(UID, add(mk(1)))
    before = dict(docs._data)

    def boom(cur: tuple[Note, ...]) -> tuple[tuple[Note, ...], int]:
        raise NotesError(409, "notes_full", "full")

    with pytest.raises(NotesError) as e:
        await store.change(UID, boom)
    assert e.value.code == "notes_full" and docs._data == before


async def test_a_no_op_change_writes_nothing() -> None:
    docs, store = rig()
    await store.change(UID, add(mk(1)))
    docs.sets = 0
    await store.change(UID, lambda cur: (cur, 0))
    assert docs.sets == 0


async def test_big_collections_split_into_shards_under_the_ciphertext_limit() -> None:
    docs, store = rig()
    big = [mk(i, "é" * MAX_TEXT) for i in range(1, 140)]  # 2-byte characters: worst case
    await store.change(UID, add(*big))
    shard_docs = [d for p, d in docs._data.items() if p.startswith("jarvis_kb_shards/")]
    assert len(shard_docs) >= 2
    assert all(len(d["blob"]) <= SHARD_CIPHER_MAX for d in shard_docs)
    assert len((await NotesStore(docs, Keyring(ROOT_KEY)).load(UID)).notes) == 139


async def test_shrinking_deletes_the_extra_shards() -> None:
    docs, store = rig()
    await store.change(UID, add(*[mk(i, "é" * MAX_TEXT) for i in range(1, 140)]))
    await store.change(UID, lambda cur: (cur[:1], 0))
    assert [p for p in docs._data if p.startswith("jarvis_kb_shards/")] == [
        f"jarvis_kb_shards/{UID}_s0"
    ]


async def test_only_changed_shards_are_rewritten() -> None:
    docs, store = rig()
    await store.change(UID, add(*[mk(i, "é" * MAX_TEXT) for i in range(1, 140)]))
    docs.log.clear()
    first = mk(1, "é" * MAX_TEXT)  # same size, so the shard boundaries stay put
    await store.change(
        UID, lambda cur: ((first.model_copy(update={"title": "titleZ1"}), *cur[1:]), 0)
    )
    shard_writes = [o.path for o in docs.log if "kb_shards" in o.path]
    assert shard_writes == [f"jarvis_kb_shards/{UID}_s0"]


async def test_a_torn_read_is_retried_then_fails_closed() -> None:
    docs, store = rig()
    await store.change(UID, add(mk(1)))
    cold = NotesStore(docs, Keyring(ROOT_KEY))
    path = f"jarvis_kb_shards/{UID}_s0"
    original = dict(docs._data[path])
    await store.change(UID, add(mk(2)))  # header now names a newer shard than `original`
    newer = dict(docs._data[path])
    docs._data[path] = original  # shard older than the header
    with pytest.raises(NotesError):
        await cold.load(UID)
    docs._data[path] = newer
    assert len((await cold.load(UID)).notes) == 2


async def test_counts_track_kinds_and_deleted() -> None:
    docs, store = rig()
    deleted = mk(3, deleted_at=AT)
    await store.change(
        UID,
        add(mk(1), mk(2, kind="link", url="https://example.com/", text=""), deleted),
    )
    assert docs._data[f"jarvis_kb/{UID}"]["counts"] == {
        "note": 1,
        "memo": 0,
        "link": 1,
        "deleted": 1,
    }


async def test_wipe_removes_everything_and_reports_the_live_count() -> None:
    docs, store = rig()
    await store.change(UID, add(mk(1), mk(2), mk(3, deleted_at=AT)))
    await store.change(OTHER, add(mk(9)))
    assert await store.wipe(UID) == 2
    assert [p for p in docs._data if UID in p] == []
    assert len((await store.load(OTHER)).notes) == 1
    assert (await store.load(UID)).notes == ()


async def test_invalid_user_id_is_refused() -> None:
    _, store = rig()
    with pytest.raises(ValueError):
        await store.load("../x")
