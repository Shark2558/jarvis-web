# tests/test_r51b_vitals_store.py -- R5.1 D2: the manual list needs no composite index (equality
# query only, sorted by label in Python, still capped at MAX_MANUAL + 1 rows read).
from __future__ import annotations

from vitals_fakes import UID, key

from jarvis.storage.docs import MemoryDocs, Query
from jarvis.vitals.models import MAX_MANUAL
from jarvis.vitals.store import VitalsStore


async def test_list_works_where_a_composite_index_would_be_missing() -> None:
    store = VitalsStore(MemoryDocs(strict_indexes=True))  # equality + order_by raises here
    await store.put(UID, key("brave", label="Brave search"))

    assert [p.id for p in await store.list_manual(UID)] == ["brave"]


async def test_list_is_sorted_by_label_in_python_case_insensitively() -> None:
    store = VitalsStore(MemoryDocs(strict_indexes=True))
    await store.put(UID, key("z1", label="zed"))
    await store.put(UID, key("a1", label="Alpha"))
    await store.put(UID, key("m1", label="Mid"))

    assert [p.id for p in await store.list_manual(UID)] == ["a1", "m1", "z1"]


async def test_the_query_is_equality_only_and_capped() -> None:
    seen: list[Query] = []

    class Spy(MemoryDocs):
        async def query(self, q: Query):  # type: ignore[no-untyped-def]
            seen.append(q)
            return await super().query(q)

    store = VitalsStore(Spy())
    await store.list_manual(UID)

    assert seen and all(q.order_by is None for q in seen)
    assert seen[0].where == ("user_id", UID) and seen[0].limit == MAX_MANUAL + 1


async def test_put_still_enforces_the_cap_without_an_index() -> None:
    store = VitalsStore(MemoryDocs(strict_indexes=True))
    for i in range(3):
        await store.put(UID, key(f"k{i}"))

    assert len(await store.list_manual(UID)) == 3
