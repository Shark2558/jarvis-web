# tests/test_vault_store.py -- R2 D1/D2: encrypted index + chunks on the Docs port, fail closed
from __future__ import annotations

import datetime as dt

import pytest
from vault_fakes import NOW, OTHER, UID, ring, scan

from jarvis.storage.docs import MemoryDocs
from jarvis.vault.crypto import VaultCrypto
from jarvis.vault.models import (
    Holder,
    Orphan,
    Pending,
    VaultIndex,
    VaultRejected,
    VaultUnavailable,
)
from jarvis.vault.store import WRITE_GROUP, VaultStore


def build(docs: MemoryDocs | None = None) -> tuple[VaultStore, MemoryDocs]:
    docs = docs or MemoryDocs()
    return VaultStore(docs, VaultCrypto(ring()), clock=lambda: NOW), docs


def add_holder(label: str):
    def fn(index: VaultIndex) -> tuple[VaultIndex, str]:
        h = Holder(id="h_00000001", label=label)
        return index.model_copy(update={"holders": (*index.holders, h)}), h.id

    return fn


async def test_empty_owner_loads_an_empty_index() -> None:
    store, _ = build()
    assert await store.load(UID) == (0, VaultIndex())


async def test_change_round_trips_and_bumps_rev() -> None:
    store, docs = build()
    await store.change(UID, add_holder("Anjali Rao"))
    rev, index = await store.load(UID)
    assert rev == 1 and index.holders[0].label == "Anjali Rao"
    doc = docs._data[f"jarvis_vault/{UID}"]
    assert set(doc) == {"rev", "v", "kid", "blob", "bytes_total", "updated_at"}
    assert doc["kid"] == "tk1" and not scan(docs, "Anjali")


async def test_two_owners_are_separate() -> None:
    store, _ = build()
    await store.change(UID, add_holder("A"))
    assert (await store.load(OTHER))[1] == VaultIndex()


async def test_unreadable_index_fails_closed_and_is_never_overwritten() -> None:
    store, docs = build()
    await store.change(UID, add_holder("A"))
    path = f"jarvis_vault/{UID}"
    docs._data[path]["blob"] = docs._data[path]["blob"][:-6] + "AAAAAA"
    fresh, _ = build(docs)
    with pytest.raises(VaultUnavailable):
        await fresh.load(UID)
    before = dict(docs._data[path])
    with pytest.raises(VaultUnavailable):
        await fresh.change(UID, add_holder("B"))
    assert docs._data[path] == before


async def test_index_copied_from_another_owner_is_refused() -> None:
    store, docs = build()
    await store.change(UID, add_holder("A"))
    docs._data[f"jarvis_vault/{OTHER}"] = dict(docs._data[f"jarvis_vault/{UID}"])
    fresh, _ = build(docs)
    with pytest.raises(VaultUnavailable):
        await fresh.load(OTHER)


async def test_a_tampered_document_is_not_served_from_the_cache() -> None:
    store, docs = build()
    await store.change(UID, add_holder("A"))
    path = f"jarvis_vault/{UID}"
    docs._data[path]["blob"] = docs._data[path]["blob"][:-6] + "AAAAAA"
    with pytest.raises(VaultUnavailable):
        await store.load(UID)


async def test_malformed_document_fails_closed() -> None:
    store, docs = build()
    docs._data[f"jarvis_vault/{UID}"] = {"rev": "x", "blob": 5}
    with pytest.raises(VaultUnavailable):
        await store.load(UID)


async def test_a_rejected_change_writes_nothing() -> None:
    store, docs = build()

    def refuse(index: VaultIndex) -> tuple[VaultIndex, None]:
        raise VaultRejected("no", "no")

    with pytest.raises(VaultRejected):
        await store.change(UID, refuse)
    assert not docs._data


async def test_storage_errors_become_unavailable() -> None:
    store, docs = build()

    async def boom(*a: object, **k: object) -> None:
        raise RuntimeError("secret detail")

    docs.get = boom  # type: ignore[method-assign]
    with pytest.raises(VaultUnavailable) as e:
        await store.load(UID)
    assert "secret" not in str(e.value)


async def test_chunks_written_in_groups_of_six_by_path() -> None:
    store, docs = build()
    await store.put_chunks(UID, "f_000000000001", [f"b{n}" for n in range(14)])
    assert docs.batch_sizes == [WRITE_GROUP, WRITE_GROUP, 2]
    assert await store.chunk(UID, "f_000000000001", 13) == "b13"
    assert f"jarvis_vault/{UID}/vault_chunks/f_000000000001_13" in docs._data


async def test_a_missing_chunk_fails_closed() -> None:
    store, _ = build()
    with pytest.raises(VaultUnavailable):
        await store.chunk(UID, "f_000000000001", 0)


async def test_drop_chunks_deletes_by_path_and_repeats_safely() -> None:
    store, docs = build()
    await store.put_chunks(UID, "f_000000000001", ["a", "b", "c"])
    await store.drop_chunks(UID, "f_000000000001", 3)
    await store.drop_chunks(UID, "f_000000000001", 3)
    assert not docs._data


async def test_sweep_clears_stale_pending_and_orphans() -> None:
    store, docs = build()
    await store.put_chunks(UID, "f_000000000001", ["a", "b"])
    await store.put_chunks(UID, "f_000000000002", ["c"])
    old = NOW - dt.timedelta(hours=2)
    new = NOW - dt.timedelta(minutes=5)

    def seed(index: VaultIndex) -> tuple[VaultIndex, None]:
        return index.model_copy(
            update={
                "pending": (
                    Pending(fid="f_000000000001", item_id="", chunks=2, size=9, started_at=old),
                    Pending(fid="f_000000000003", item_id="", chunks=1, size=9, started_at=new),
                ),
                "orphans": (Orphan(fid="f_000000000002", chunks=1),),
            }
        ), None

    await store.change(UID, seed)
    assert await store.sweep(UID) == 2
    assert not [p for p in docs._data if "vault_chunks" in p]
    _, index = await store.load(UID)
    assert [p.fid for p in index.pending] == ["f_000000000003"] and not index.orphans


async def test_sweep_never_raises() -> None:
    store, docs = build()
    docs._data[f"jarvis_vault/{UID}"] = {"rev": 1, "blob": "garbage"}
    assert await store.sweep(UID) == 0


async def test_queries_never_touch_chunk_collections() -> None:
    store, docs = build()
    queried: list[str] = []
    real = docs.query

    async def spy(q):  # type: ignore[no-untyped-def]
        queried.append(q.collection)
        return await real(q)

    docs.query = spy  # type: ignore[method-assign]
    await store.put_chunks(UID, "f_000000000001", ["a"])
    await store.change(UID, add_holder("A"))
    await store.sweep(UID)
    await store.chunk(UID, "f_000000000001", 0)
    assert queried == []
