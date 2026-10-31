# tests/test_storage.py — slice 5: persistence over the Docs port (written before implementation).
# Every test runs against MemoryDocs; with FIRESTORE_EMULATOR_HOST set (CI job `firestore`)
# the same tests also run against the official Firestore emulator through FirestoreDocs.
from __future__ import annotations

import asyncio
import os
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import pytest

from jarvis.core.guardrails import ActionRisk, InMemoryApprovalStore, PendingAction
from jarvis.core.models import Session, Turn
from jarvis.llm.base import Role, TextBlock, ToolCall, ToolResultBlock
from jarvis.storage.approvals import DocApprovalStore
from jarvis.storage.audit import DocAuditLog
from jarvis.storage.docs import Delete, DocExists, Docs, MemoryDocs, Query, Set
from jarvis.storage.sessions import DocSessionStore
from jarvis.tools.audit import AuditLog

EMULATOR = bool(os.environ.get("FIRESTORE_EMULATOR_HOST"))
BACKENDS = ["memory", pytest.param("emulator", marks=pytest.mark.firestore_emulator)]


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
    """Isolates tests that share one emulator database."""
    return f"t{uuid.uuid4().hex[:10]}_"


def _session(n_turns: int = 3, user_id: str = "owner", first: str = "Plan my week") -> Session:
    s = Session(user_id=user_id)
    for i in range(n_turns):
        role = Role.USER if i % 2 == 0 else Role.ASSISTANT
        s.append(Turn(role=role, content=first if i == 0 else f"turn {i}"))
    return s


def _tool_session() -> Session:
    s = _session(1)
    call = ToolCall(id="c1", name="get_calendar", arguments={"day": "today"})
    s.append(Turn(role=Role.ASSISTANT, content="", blocks=[call]))
    s.append(
        Turn(
            role=Role.USER,
            content="",
            blocks=[
                ToolResultBlock(tool_use_id="c1", content='{"events": []}'),
                TextBlock(text="note"),
            ],
        )
    )
    s.metadata["brain"] = "gemini"
    return s


# ============================================================== Docs port contract
async def test_docs_set_get_delete(docs: Docs, prefix: str) -> None:
    p = f"{prefix}things/a"
    assert await docs.get(p) is None
    await docs.write([Set(p, {"n": 1, "s": "x"})])
    assert await docs.get(p) == {"n": 1, "s": "x"}
    await docs.write([Delete(p)])
    assert await docs.get(p) is None


async def test_docs_query_where_order_limit(docs: Docs, prefix: str) -> None:
    col = f"{prefix}items"
    now = datetime.now(UTC)
    await docs.write(
        [
            Set(f"{col}/a", {"u": "x", "t": now - timedelta(minutes=3)}),
            Set(f"{col}/b", {"u": "x", "t": now - timedelta(minutes=1)}),
            Set(f"{col}/c", {"u": "y", "t": now}),
            Set(f"{col}/b/sub/z", {"u": "x", "t": now}),  # subcollection docs are not included
        ]
    )
    rows = await docs.query(Query(col, where=("u", "x"), order_by="t", descending=True, limit=5))
    assert [i for i, _ in rows] == ["b", "a"]
    rows = await docs.query(Query(col, order_by="t", limit=1))
    assert [i for i, _ in rows] == ["a"]
    assert len(await docs.query(Query(f"{col}/b/sub"))) == 1


async def test_docs_transaction_is_atomic_under_contention(docs: Docs, prefix: str) -> None:
    p = f"{prefix}counters/c"
    await docs.write([Set(p, {"n": 0})])

    async def bump() -> int:
        async def fn(tx) -> int:  # type: ignore[no-untyped-def]
            cur = await tx.get(p)
            n = (cur or {"n": 0})["n"] + 1
            tx.set(p, {"n": n})
            return n

        return await docs.transaction(fn)

    results = await asyncio.gather(*(bump() for _ in range(8)))
    assert sorted(results) == list(range(1, 9))
    assert await docs.get(p) == {"n": 8}


async def test_docs_large_write_is_chunked_in_order(prefix: str) -> None:
    docs = MemoryDocs()
    ops = [Set(f"{prefix}bulk/{i:04d}", {"i": i}) for i in range(1203)]
    await docs.write(ops)
    assert max(docs.batch_sizes) <= MemoryDocs.MAX_BATCH
    assert docs.batch_sizes == [500, 500, 203]
    assert len(await docs.query(Query(f"{prefix}bulk"))) == 1203


async def test_memory_docs_can_simulate_a_missing_composite_index(prefix: str) -> None:
    from jarvis.storage.docs import IndexNotReady

    docs = MemoryDocs(strict_indexes=True)
    with pytest.raises(IndexNotReady):
        await docs.query(Query(f"{prefix}x", where=("u", 1), order_by="t"))
    assert await docs.query(Query(f"{prefix}x", where=("u", 1))) == []


# ============================================================== sessions
async def test_session_round_trip_and_restart(docs: Docs, prefix: str) -> None:
    s = _tool_session()
    await DocSessionStore(docs, prefix=prefix).save(s)
    fresh = DocSessionStore(docs, prefix=prefix)  # a cold start: new process, same database
    got = await fresh.get(s.id)
    assert got is not None
    assert got.model_dump(mode="json") == s.model_dump(mode="json")


async def test_session_get_missing(docs: Docs, prefix: str) -> None:
    assert await DocSessionStore(docs, prefix=prefix).get("sess_nope") is None


async def test_session_save_writes_only_new_turns(prefix: str) -> None:
    docs = MemoryDocs()
    store = DocSessionStore(docs, prefix=prefix)
    s = _session(3)
    await store.save(s)
    assert docs.sets == 4  # 3 turns + header
    s.append(Turn(role=Role.ASSISTANT, content="more"))
    await store.save(s)
    assert docs.sets == 6  # +1 turn +1 header
    await store.save(s)
    assert docs.sets == 6  # unchanged session: no writes at all


async def test_session_diff_memo_survives_restart_via_get(prefix: str) -> None:
    docs = MemoryDocs()
    await DocSessionStore(docs, prefix=prefix).save(_session(5))
    sid = next(iter(i for i, _ in await docs.query(Query(f"{prefix}sessions"))))
    fresh = DocSessionStore(docs, prefix=prefix)
    s = await fresh.get(sid)
    assert s is not None
    before = docs.sets
    s.append(Turn(role=Role.USER, content="again"))
    await fresh.save(s)
    assert docs.sets - before == 2


async def test_session_get_uses_cache_when_unchanged(prefix: str) -> None:
    docs = MemoryDocs()
    store = DocSessionStore(docs, prefix=prefix)
    s = _session(6)
    await store.save(s)
    before = docs.reads
    got = await store.get(s.id)
    assert got is not None and len(got.turns) == 6
    assert docs.reads - before == 1  # header only
    got.turns.append(Turn(role=Role.USER, content="mutated copy"))
    again = await store.get(s.id)
    assert again is not None and len(again.turns) == 6  # callers get copies


async def test_session_cache_never_serves_stale_data(docs: Docs, prefix: str) -> None:
    a, b = DocSessionStore(docs, prefix=prefix), DocSessionStore(docs, prefix=prefix)
    s = _session(2)
    await a.save(s)
    assert len((await b.get(s.id)).turns) == 2  # type: ignore[union-attr]
    s.append(Turn(role=Role.USER, content="third"))
    s.metadata["brain"] = "anthropic"
    await a.save(s)
    seen = await b.get(s.id)
    assert seen is not None and len(seen.turns) == 3 and seen.metadata["brain"] == "anthropic"


async def test_session_metadata_change_alone_is_persisted(docs: Docs, prefix: str) -> None:
    store = DocSessionStore(docs, prefix=prefix)
    s = _session(2)
    await store.save(s)
    s.metadata["brain_cutoff"] = 2
    await store.save(s)
    got = await DocSessionStore(docs, prefix=prefix).get(s.id)
    assert got is not None and got.metadata["brain_cutoff"] == 2


async def test_session_list_newest_first_with_titles(docs: Docs, prefix: str) -> None:
    store = DocSessionStore(docs, prefix=prefix)
    old = _session(2, first="Draft the steering committee note")
    new = _session(2, first="  What's   on\nmy calendar today?  ")
    other = _session(2, user_id="someone-else")
    old.updated_at = datetime.now(UTC) - timedelta(hours=2)
    for s in (old, new, other):
        await store.save(s)
    got = await store.list_for_user("owner", limit=10)
    assert [x.id for x in got] == [new.id, old.id]
    assert got[0].title == "What's on my calendar today?"
    assert got[1].turn_count == 2
    assert [x.id for x in await store.list_for_user("owner", limit=1)] == [new.id]


async def test_session_list_falls_back_while_index_builds(prefix: str) -> None:
    store = DocSessionStore(MemoryDocs(strict_indexes=True), prefix=prefix)
    a, b = _session(1), _session(1)
    a.updated_at = datetime.now(UTC) - timedelta(minutes=5)
    await store.save(a)
    await store.save(b)
    assert [x.id for x in await store.list_for_user("owner")] == [b.id, a.id]


async def test_session_delete(docs: Docs, prefix: str) -> None:
    store = DocSessionStore(docs, prefix=prefix)
    s = _session(3)
    await store.save(s)
    assert await store.delete(s.id) is True
    assert await store.get(s.id) is None
    assert await DocSessionStore(docs, prefix=prefix).get(s.id) is None
    assert await docs.query(Query(f"{prefix}sessions/{s.id}/turns")) == []
    assert await store.delete(s.id) is False


async def test_session_long_conversation_header_written_last(prefix: str) -> None:
    docs = MemoryDocs()
    store = DocSessionStore(docs, prefix=prefix)
    s = _session(620)
    await store.save(s)
    assert max(docs.batch_sizes) <= MemoryDocs.MAX_BATCH
    assert docs.log[-1].path == f"{prefix}sessions/{s.id}"  # header last: never ahead of turns
    got = await DocSessionStore(docs, prefix=prefix).get(s.id)
    assert got is not None and [t.content for t in got.turns] == [t.content for t in s.turns]


async def test_session_ignores_turn_docs_beyond_header_count(prefix: str) -> None:
    docs = MemoryDocs()
    store = DocSessionStore(docs, prefix=prefix)
    s = _session(2)
    await store.save(s)
    await docs.write([Set(f"{prefix}sessions/{s.id}/turns/000099", {"json": "{}"})])
    got = await DocSessionStore(docs, prefix=prefix).get(s.id)
    assert got is not None and len(got.turns) == 2


async def test_session_corrupt_header_is_treated_as_missing(prefix: str) -> None:
    docs = MemoryDocs()
    await docs.write([Set(f"{prefix}sessions/sess_bad", {"json": "{not json", "turn_count": 0})])
    assert await DocSessionStore(docs, prefix=prefix).get("sess_bad") is None


async def test_session_ping_is_cached(prefix: str) -> None:
    docs = MemoryDocs()
    store = DocSessionStore(docs, prefix=prefix)
    assert await store.ping() is True
    before = docs.reads
    assert await store.ping() is True
    assert docs.reads == before


# ============================================================== approvals
def _action(scope: str = "owner:sess_1", **args: object) -> PendingAction:
    return PendingAction(
        tool="send_message",
        arguments={"to": "priya@example.com", "body": "hi", **args},
        risk=ActionRisk.IRREVERSIBLE,
        summary="Send a message to priya@example.com",
        scope=scope,
    )


@pytest.fixture(params=["memory-store", "docs-store"])
def approvals_factory(request: pytest.FixtureRequest, docs: Docs, prefix: str):  # type: ignore[no-untyped-def]
    if request.param == "memory-store":
        shared = InMemoryApprovalStore()
        return lambda: shared
    return lambda: DocApprovalStore(docs, prefix=prefix)


def _same(a: PendingAction):  # type: ignore[no-untyped-def]
    return lambda p: p.tool == a.tool and p.arguments == a.arguments and p.scope == a.scope


async def test_approvals_put_get_list_and_survive_restart(approvals_factory) -> None:  # type: ignore[no-untyped-def]
    a = _action()
    await approvals_factory().put(a)
    store = approvals_factory()
    got = await store.get(a.id)
    assert got is not None and got.model_dump(mode="json") == a.model_dump(mode="json")
    assert [p.id for p in await store.list_pending()] == [a.id]


async def test_approvals_consume_is_single_use_and_checks_match(approvals_factory) -> None:  # type: ignore[no-untyped-def]
    store = approvals_factory()
    a = _action()
    await store.put(a)
    drifted = _action(body="changed")
    assert await store.consume(a.id, _same(drifted)) is None
    assert await store.get(a.id) is not None  # a wrong match never consumes the token
    taken = await store.consume(a.id, _same(a))
    assert taken is not None and taken.id == a.id
    assert await store.consume(a.id, _same(a)) is None
    assert await store.list_pending() == []


async def test_approvals_expired_are_hidden_and_unusable(approvals_factory) -> None:  # type: ignore[no-untyped-def]
    store = approvals_factory()
    a = _action()
    a.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    await store.put(a)
    assert await store.list_pending() == []
    assert await store.consume(a.id, _same(a)) is None


async def test_approvals_concurrent_double_approve_consumes_once(approvals_factory) -> None:  # type: ignore[no-untyped-def]
    store = approvals_factory()
    a = _action()
    await store.put(a)
    results = await asyncio.gather(*(store.consume(a.id, _same(a)) for _ in range(5)))
    assert sum(r is not None for r in results) == 1


async def test_approvals_cancel(approvals_factory) -> None:  # type: ignore[no-untyped-def]
    store = approvals_factory()
    a = _action()
    await store.put(a)
    removed = await store.cancel(a.id)
    assert removed is not None and removed.id == a.id
    assert await store.cancel(a.id) is None


# ============================================================== audit chain
@pytest.fixture(params=["memory-log", "docs-log"])
def audit_factory(request: pytest.FixtureRequest, docs: Docs, prefix: str):  # type: ignore[no-untyped-def]
    if request.param == "memory-log":
        shared = AuditLog()
        return lambda: shared
    return lambda: DocAuditLog(docs, prefix=prefix)


async def _append(log, tool: str = "t") -> None:  # type: ignore[no-untyped-def]
    await log.append(agent="a", tool=tool, risk=ActionRisk.READ_ONLY, outcome="executed", args={})


async def test_audit_tail_window_and_restart(audit_factory) -> None:  # type: ignore[no-untyped-def]
    log = audit_factory()
    for t in ("a", "b", "c"):
        await _append(log, t)
    tail = await log.tail(2)
    assert [e.tool for e in tail.entries] == ["b", "c"] and tail.verified
    fresh = audit_factory()  # cold start
    await _append(fresh, "d")
    tail = await fresh.tail(10)
    assert [e.seq for e in tail.entries] == [1, 2, 3, 4] and tail.verified
    assert tail.entries[3].prev_hash == tail.entries[2].hash
    assert await fresh.verify_all() is True


async def test_audit_empty(audit_factory) -> None:  # type: ignore[no-untyped-def]
    tail = await audit_factory().tail(5)
    assert tail.entries == [] and tail.verified


async def test_audit_concurrent_appends_never_fork(audit_factory) -> None:  # type: ignore[no-untyped-def]
    log = audit_factory()
    await asyncio.gather(*(_append(log, f"t{i}") for i in range(10)))
    tail = await log.tail(20)
    assert [e.seq for e in tail.entries] == list(range(1, 11)) and tail.verified


async def test_doc_audit_detects_tampering_and_deletion(docs: Docs, prefix: str) -> None:
    log = DocAuditLog(docs, prefix=prefix)
    for t in ("a", "b", "c", "d"):
        await _append(log, t)
    path2 = f"{prefix}audit/{2:012d}"
    original = await docs.get(path2)
    assert original is not None
    forged = original["json"].replace('"executed"', '"denied"')
    await docs.write([Set(path2, {**original, "json": forged})])
    assert (await log.tail(10)).verified is False
    assert (await log.tail(2)).verified is False  # entry 2 is the window's predecessor
    assert await log.verify_all() is False
    await docs.write([Set(path2, original)])
    assert (await log.tail(10)).verified is True
    await docs.write([Delete(f"{prefix}audit/{3:012d}")])
    assert (await log.tail(10)).verified is False


def test_safe_id_rejects_newlines_and_paths() -> None:
    from jarvis.storage.sessions import safe_id

    assert safe_id("sess_abc-123")
    for bad in ("abc\n", "a/b", "..", "__x__", "", "a" * 129, "sp ace"):
        assert not safe_id(bad), bad


async def test_doc_audit_detects_deleted_head_and_never_overwrites(docs: Docs, prefix: str) -> None:
    log = DocAuditLog(docs, prefix=prefix)
    for t in ("a", "b"):
        await _append(log, t)
    first = await docs.get(f"{prefix}audit/{1:012d}")
    await docs.write([Delete(f"{prefix}meta/audit_head")])
    assert (await log.tail(10)).verified is False
    assert await log.verify_all() is False
    with pytest.raises(DocExists):
        await _append(log, "c")  # would restart at seq 1: refused, entry 1 untouched
    assert await docs.get(f"{prefix}audit/{1:012d}") == first


async def test_session_with_missing_turn_docs_is_never_cached_as_complete(prefix: str) -> None:
    docs = MemoryDocs()
    store = DocSessionStore(docs, prefix=prefix)
    s = _session(5)
    await store.save(s)
    await docs.write([Delete(f"{prefix}sessions/{s.id}/turns/000003")])  # a gap
    fresh = DocSessionStore(docs, prefix=prefix)
    got = await fresh.get(s.id)
    assert got is not None
    got.append(Turn(role=Role.USER, content="next"))
    await fresh.save(got)  # must rewrite every turn, not trust positions read across a gap
    again = await DocSessionStore(docs, prefix=prefix).get(s.id)
    assert again is not None
    assert [t.content for t in again.turns] == [t.content for t in got.turns]


async def test_session_delete_removes_turns_before_header(prefix: str) -> None:
    docs = MemoryDocs()
    store = DocSessionStore(docs, prefix=prefix)
    s = _session(3)
    await store.save(s)
    docs.log.clear()
    await store.delete(s.id)
    assert docs.log[-1].path == f"{prefix}sessions/{s.id}"  # retryable if interrupted


async def test_doc_audit_tail_ignores_entries_newer_than_the_head_it_read(prefix: str) -> None:
    docs = MemoryDocs()
    log = DocAuditLog(docs, prefix=prefix)
    for t in ("a", "b"):
        await _append(log, t)
    real_get = docs.get

    async def get_then_race(path: str):  # type: ignore[no-untyped-def]
        out = await real_get(path)
        if path.endswith("meta/audit_head"):
            docs.get = real_get  # type: ignore[method-assign]
            await _append(DocAuditLog(docs, prefix=prefix), "c")  # lands between the reads
        return out

    docs.get = get_then_race  # type: ignore[method-assign]
    tail = await log.tail(10)
    assert tail.verified and [e.tool for e in tail.entries] == ["a", "b"]
