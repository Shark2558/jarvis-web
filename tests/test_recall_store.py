# tests/test_recall_store.py — slice 8 D11: the memory store on the Docs port. Runs on MemoryDocs;
# with FIRESTORE_EMULATOR_HOST set (CI job `firestore`) the contract tests also run against the
# Firestore emulator through FirestoreDocs.
from __future__ import annotations

import asyncio
import os
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from datetime import UTC, datetime

import pytest
from billing_fakes import put_raw
from brief_fakes import SlowDocs

from jarvis.recall.errors import MemoryFull, MemoryUnavailable
from jarvis.recall.models import MAX_ACTIVE, MemoryState, UseStat
from jarvis.recall.ops import add_fact, delete_facts, new_fact, replace_fact, set_profile
from jarvis.recall.store import MemoryStore, shards_rev
from jarvis.storage.docs import Doc, Docs, MemoryDocs

EMULATOR = bool(os.environ.get("FIRESTORE_EMULATOR_HOST"))
BACKENDS = ["memory", pytest.param("emulator", marks=pytest.mark.firestore_emulator)]
NOW = datetime(2026, 11, 15, 6, 0, tzinfo=UTC)
UID = "u_owner"


@pytest.fixture(params=BACKENDS)
async def docs(request: pytest.FixtureRequest) -> AsyncIterator[Docs]:
    if request.param == "memory":
        d: Docs = MemoryDocs()
    else:
        if not EMULATOR:
            if os.environ.get("JARVIS_REQUIRE_EMULATOR"):
                pytest.fail("JARVIS_REQUIRE_EMULATOR is set but FIRESTORE_EMULATOR_HOST is not")
            pytest.skip("FIRESTORE_EMULATOR_HOST not set")
        from jarvis.storage.firestore_docs import FirestoreDocs

        d = FirestoreDocs(project="demo-jarvis-test", database="(default)")
    yield d
    await d.close()


@pytest.fixture
def prefix() -> str:
    return f"t{uuid.uuid4().hex[:10]}_"


def _adder(text: str, category: str = "other", origin: str = "added"):  # type: ignore[no-untyped-def]
    def fn(s: MemoryState) -> MemoryState:
        return add_fact(s, new_fact(s, text, category, origin=origin, now=NOW))  # type: ignore[arg-type]

    return fn


# ---- contract (memory + emulator) ---------------------------------------------------------------


async def test_empty_memory_loads_as_defaults(docs: Docs, prefix: str) -> None:
    s = await MemoryStore(docs, prefix=prefix).load(UID)
    assert s.all_facts() == [] and s.settings.use is True and s.settings.learn is False


async def test_changes_persist_across_a_cold_start(docs: Docs, prefix: str) -> None:
    store = MemoryStore(docs, prefix=prefix)
    await store.mutate(UID, _adder("Prefers window seats", "preferences"))
    await store.mutate(UID, lambda s: set_profile(s, "about", "Akash, project lead"))
    cold = await MemoryStore(docs, prefix=prefix).load(UID)
    assert [f.text for f in cold.active()] == ["Prefers window seats"]
    assert cold.profile.about == "Akash, project lead"


async def test_replace_and_history_persist(docs: Docs, prefix: str) -> None:
    store = MemoryStore(docs, prefix=prefix)
    s = await store.mutate(UID, _adder("Lives in Kochi", "places"))
    old = s.active()[0]

    def move(cur: MemoryState) -> MemoryState:
        new = new_fact(cur, "Lives in Thiruvananthapuram", "places", origin="learned", now=NOW)
        return replace_fact(cur, old.id, new, NOW)

    await store.mutate(UID, move)
    cold = await MemoryStore(docs, prefix=prefix).load(UID)
    assert [f.text for f in cold.active()] == ["Lives in Thiruvananthapuram"]
    assert [f.replaced_by for f in cold.all_facts() if not f.active] == [cold.active()[0].id]


async def test_owners_are_separate(docs: Docs, prefix: str) -> None:
    store = MemoryStore(docs, prefix=prefix)
    await store.mutate(UID, _adder("Prefers tea"))
    assert (await store.load("u_other")).all_facts() == []


# ---- Firestore budget (D11), MemoryDocs counters -------------------------------------------------


async def test_warm_load_is_one_read() -> None:
    docs = MemoryDocs()
    store = MemoryStore(docs)
    await store.mutate(UID, _adder("Prefers tea"))
    await store.load(UID)
    before = docs.reads
    await store.load(UID)
    assert docs.reads - before == 1


async def test_cold_load_of_a_full_memory_is_at_most_eight_reads() -> None:
    docs = MemoryDocs()
    store = MemoryStore(docs)

    def fill(s: MemoryState) -> MemoryState:
        for i in range(MAX_ACTIVE):
            f = new_fact(s, f"note {i} about topic t{i}", "other", origin="added", now=NOW)
            s = add_fact(s, f)
        return s

    await store.mutate(UID, fill)

    # plus history: 150 replaced facts (kept 30 days)
    def churn(cur: MemoryState) -> MemoryState:
        for f in cur.active()[:150]:
            new = new_fact(cur, f.text + " (updated)", "other", origin="told", now=NOW)
            cur = replace_fact(cur, f.id, new, NOW)
        return cur

    with pytest.raises(MemoryFull):  # 500 active is the limit; churn replaces 1:1, never adds
        await store.mutate(UID, _adder("one note too many"))
    s = await store.mutate(UID, churn)
    assert len(s.all_facts()) == MAX_ACTIVE + 150
    cold_docs_reads = docs.reads
    await MemoryStore(docs).load(UID)
    assert docs.reads - cold_docs_reads <= 8


@pytest.mark.parametrize("change", ["add", "replace", "delete", "settings", "profile"])
async def test_one_change_is_at_most_three_writes(change: str) -> None:
    docs = MemoryDocs()
    store = MemoryStore(docs)
    for i in range(150):  # two shards
        await store.mutate(UID, _adder(f"note {i} about topic t{i}"))
    s = await store.load(UID)
    first = s.shards[0][0]
    before = docs.sets + docs.deletes

    def fn(cur: MemoryState) -> MemoryState:
        if change == "add":
            return add_fact(cur, new_fact(cur, "brand new note", "other", origin="told", now=NOW))
        if change == "replace":
            new = new_fact(cur, "replacement note", "other", origin="learned", now=NOW)
            return replace_fact(cur, first.id, new, NOW)
        if change == "delete":
            from jarvis.recall.ops import delete_facts

            return delete_facts(cur, [first.id])[0]
        if change == "settings":
            return cur.with_settings(cur.settings.model_copy(update={"use": False}))
        return set_profile(cur, "about", "Akash")

    await store.mutate(UID, fn)
    assert docs.sets + docs.deletes - before <= 3


async def test_usage_only_changes_keep_the_warm_cache() -> None:
    docs = MemoryDocs()
    store = MemoryStore(docs)
    s = await store.mutate(UID, _adder("Prefers tea"))
    fid = s.active()[0].id
    rev = s.rev
    s2 = await store.mutate(UID, lambda cur: cur.with_usage({fid: UseStat(at=NOW, n=3)}))
    assert s2.rev == rev
    before_sets = docs.sets
    assert before_sets > 0
    before = docs.reads
    loaded = await store.load(UID)
    assert docs.reads - before == 1
    assert loaded.active()[0].use_count == 3 and loaded.active()[0].last_used_at == NOW


async def test_a_mutation_that_returns_none_writes_nothing() -> None:
    docs = MemoryDocs()
    store = MemoryStore(docs)
    await store.mutate(UID, _adder("Prefers tea"))
    before = docs.sets
    await store.mutate(UID, lambda cur: None)
    assert docs.sets == before


# ---- robustness ------------------------------------------------------------------------------


async def test_unreadable_header_fails_closed() -> None:
    docs = MemoryDocs()
    await put_raw(docs, f"jarvis_memory/{UID}", {"rev": "x", "shard_count": 1, "json": "{not json"})
    store = MemoryStore(docs)
    with pytest.raises(MemoryUnavailable):
        await store.load(UID)
    with pytest.raises(MemoryUnavailable):
        await store.mutate(UID, _adder("Prefers tea"))


async def test_unreadable_shard_fails_closed_and_is_never_overwritten() -> None:
    docs = MemoryDocs()
    store = MemoryStore(docs)
    await store.mutate(UID, _adder("Prefers tea"))
    await put_raw(docs, f"jarvis_memory_shards/{UID}_0", {"json": "[{broken"})
    cold = MemoryStore(docs)
    with pytest.raises(MemoryUnavailable):
        await cold.load(UID)
    with pytest.raises(MemoryUnavailable):
        await cold.mutate(UID, _adder("Prefers coffee"))
    assert (await docs.get(f"jarvis_memory_shards/{UID}_0")) == {"json": "[{broken"}


async def test_invalid_user_id_is_refused() -> None:
    with pytest.raises(ValueError):
        await MemoryStore(MemoryDocs()).load("../x")


async def test_concurrent_adds_are_both_kept() -> None:
    docs = SlowDocs()
    a, b = MemoryStore(docs), MemoryStore(docs)  # two instances: no shared cache
    await asyncio.gather(
        a.mutate(UID, _adder("Prefers tea")), b.mutate(UID, _adder("Owns a Nexon EV"))
    )
    texts = sorted(f.text for f in (await MemoryStore(docs).load(UID)).active())
    assert texts == ["Owns a Nexon EV", "Prefers tea"]


async def test_stale_cache_is_refreshed_when_another_writer_changed_the_rev() -> None:
    docs = MemoryDocs()
    a, b = MemoryStore(docs), MemoryStore(docs)
    await a.mutate(UID, _adder("Prefers tea"))
    await a.load(UID)
    await b.mutate(UID, _adder("Owns a Nexon EV"))
    assert len((await a.load(UID)).active()) == 2


class _WriterBetweenReads(MemoryDocs):
    """Another instance writes after this one read the header and before it read the shards."""

    def __init__(self) -> None:
        super().__init__()
        self.between: Callable[[], Awaitable[None]] | None = None

    async def get(self, path: str) -> Doc | None:
        doc = await super().get(path)
        if self.between is not None and path.endswith(f"memory/{UID}"):
            hook, self.between = self.between, None
            await hook()
        return doc


async def test_a_torn_read_is_never_cached_under_the_old_rev() -> None:
    """MEDIUM 8: header (rev X) then newer shards (Y) were cached as X; when the other writer
    later returned the shards to X (a delete), the cached Y shards resurrected the fact."""
    docs = _WriterBetweenReads()
    a, b = MemoryStore(docs), MemoryStore(docs)
    await a.mutate(UID, _adder("Works at Amnex"))
    ghost: list[str] = []

    async def other_instance() -> None:
        new = await b.mutate(UID, _adder("Secret ghost fact"))
        ghost.extend(f.id for f in new.active() if "ghost" in f.text)

    a._known.clear()  # a cold instance
    docs.between = other_instance
    seen = await a.load(UID)
    assert seen.rev == shards_rev(seen.shards)  # what it returns is one consistent revision
    await b.mutate(UID, lambda cur: delete_facts(cur, ghost)[0])
    assert [f.text for f in (await a.load(UID)).active()] == ["Works at Amnex"]


async def test_a_read_that_stays_torn_is_returned_but_not_cached() -> None:
    docs = MemoryDocs()
    a = MemoryStore(docs)
    await a.mutate(UID, _adder("Works at Amnex"))
    head = await docs.get(f"jarvis_memory/{UID}")
    assert head is not None
    await put_raw(docs, f"jarvis_memory/{UID}", {**head, "rev": "0000000000000000"})
    a._known.clear()
    s = await a.load(UID)
    assert [f.text for f in s.active()] == ["Works at Amnex"]
    assert UID not in a._known
