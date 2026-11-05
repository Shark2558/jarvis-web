# tests/test_vitals_store.py -- R4 D2/D4: manual records and last status on the Docs port.
from __future__ import annotations

import pytest
from vitals_fakes import OTHER, T0, UID, key

from jarvis.storage.docs import MemoryDocs
from jarvis.vitals.models import MAX_MANUAL
from jarvis.vitals.store import VitalsFull, VitalsStore, VitalsUnavailable


async def test_put_then_list_round_trips_a_record() -> None:
    store = VitalsStore(MemoryDocs())
    p = key("brave", limit=2000, used=10, expires_in_days=40, unit="queries", note="web search")

    await store.put(UID, p)

    assert await store.list_manual(UID) == [p]


async def test_put_same_id_replaces_not_duplicates() -> None:
    store = VitalsStore(MemoryDocs())
    await store.put(UID, key("brave", limit=1))
    await store.put(UID, key("brave", limit=2))

    got = await store.list_manual(UID)

    assert len(got) == 1 and got[0].limit == 2


async def test_records_are_per_owner() -> None:
    store = VitalsStore(MemoryDocs())
    await store.put(UID, key("a"))
    await store.put(OTHER, key("b"))

    assert [p.id for p in await store.list_manual(UID)] == ["a"]


async def test_list_is_ordered_by_label() -> None:
    store = VitalsStore(MemoryDocs())
    await store.put(UID, key("z1", label="Zed"))
    await store.put(UID, key("a1", label="Alpha"))

    assert [p.id for p in await store.list_manual(UID)] == ["a1", "z1"]


async def test_delete_removes_and_reports_whether_it_existed() -> None:
    store = VitalsStore(MemoryDocs())
    await store.put(UID, key("a"))

    assert await store.delete(UID, "a") is True
    assert await store.delete(UID, "a") is False
    assert await store.list_manual(UID) == []


async def test_auto_records_are_never_stored() -> None:
    store = VitalsStore(MemoryDocs())

    with pytest.raises(ValueError):
        await store.put(UID, key("a", source="auto"))


async def test_bad_owner_id_is_refused() -> None:
    store = VitalsStore(MemoryDocs())

    with pytest.raises(ValueError):
        await store.list_manual("../x")


async def test_record_cap_is_enforced_but_replacing_still_works() -> None:
    store = VitalsStore(MemoryDocs())
    for i in range(MAX_MANUAL):
        await store.put(UID, key(f"k{i}"))

    with pytest.raises(VitalsFull):
        await store.put(UID, key("one-too-many"))
    await store.put(UID, key("k0", limit=5))


async def test_a_corrupt_record_is_skipped_not_fatal() -> None:
    docs = MemoryDocs()
    store = VitalsStore(docs)
    await store.put(UID, key("good"))
    from jarvis.storage.docs import Set

    await docs.write([Set(f"jarvis_vitals_providers/{UID}__bad", {"user_id": UID, "kind": 5})])

    assert [p.id for p in await store.list_manual(UID)] == ["good"]


async def test_storage_failure_becomes_plain_unavailable() -> None:
    class Down(MemoryDocs):
        async def query(self, q):  # type: ignore[no-untyped-def]
            raise OSError("secret detail")

    with pytest.raises(VitalsUnavailable) as e:
        await VitalsStore(Down()).list_manual(UID)
    assert "secret" not in str(e.value)


async def test_last_status_defaults_to_none_and_round_trips() -> None:
    store = VitalsStore(MemoryDocs())
    assert await store.last_status(UID, "brave") is None

    await store.set_status(UID, "brave", "amber", T0)

    assert await store.last_status(UID, "brave") == "amber"


async def test_garbage_last_status_reads_as_none() -> None:
    docs = MemoryDocs()
    from jarvis.storage.docs import Set

    await docs.write([Set(f"jarvis_vitals_status/{UID}__brave", {"status": "purple"})])

    assert await VitalsStore(docs).last_status(UID, "brave") is None


async def test_delete_also_forgets_last_status() -> None:
    store = VitalsStore(MemoryDocs())
    await store.put(UID, key("a"))
    await store.set_status(UID, "a", "red", T0)

    await store.delete(UID, "a")

    assert await store.last_status(UID, "a") is None
