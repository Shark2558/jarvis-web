# tests/test_session_rev.py — slice 10 A3: a conversation saved by two processes is never silently
# overwritten. Header writes are a compare-and-set on `rev` inside a transaction. Every test runs on
# MemoryDocs; with FIRESTORE_EMULATOR_HOST set (CI job `firestore`, marker firestore_emulator) the
# same tests also run against the Firestore emulator through FirestoreDocs.
from __future__ import annotations

import asyncio
import os
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable

import pytest
from httpx import ASGITransport, AsyncClient

from jarvis.api import create_app
from jarvis.config import Settings
from jarvis.core.models import Session, Turn
from jarvis.llm.base import Role
from jarvis.llm.mock_provider import MockProvider
from jarvis.memory.base import SessionConflict
from jarvis.memory.inmemory import InMemorySessionStore
from jarvis.storage.docs import Docs, DocTx, MemoryDocs, Query, T
from jarvis.storage.sessions import DocSessionStore

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
    return f"r{uuid.uuid4().hex[:10]}_"


def _session(n_turns: int = 2) -> Session:
    s = Session(user_id="owner")
    for i in range(n_turns):
        role = Role.USER if i % 2 == 0 else Role.ASSISTANT
        s.append(Turn(role=role, content=f"turn {i}"))
    return s


def _say(s: Session, text: str) -> Session:
    s.append(Turn(role=Role.USER, content=text))
    return s


async def _contents(docs: Docs, prefix: str, sid: str) -> list[str]:
    got = await DocSessionStore(docs, prefix=prefix).get(sid)  # a fresh process reads it
    assert got is not None
    return [t.content for t in got.turns]


async def _turn_docs(docs: Docs, prefix: str, sid: str) -> int:
    return len(await docs.query(Query(f"{prefix}sessions/{sid}/turns")))


# ---- two processes, one conversation ------------------------------------------------------------


async def test_a_second_process_cannot_overwrite_newer_turns(docs: Docs, prefix: str) -> None:
    a, b = DocSessionStore(docs, prefix=prefix), DocSessionStore(docs, prefix=prefix)
    base = _session(2)
    await a.save(base)
    in_a, in_b = await a.get(base.id), await b.get(base.id)
    assert in_a is not None and in_b is not None
    await b.save(_say(in_b, "from the phone"))
    with pytest.raises(SessionConflict):
        await a.save(_say(in_a, "from the laptop"))
    # nothing of A's reached the database: B's conversation is intact, no stray turn documents
    assert await _contents(docs, prefix, base.id) == ["turn 0", "turn 1", "from the phone"]
    assert await _turn_docs(docs, prefix, base.id) == 3


async def test_a_stale_copy_in_the_same_process_cannot_overwrite_either(
    docs: Docs, prefix: str
) -> None:
    store = DocSessionStore(docs, prefix=prefix)
    s = _session(2)
    await store.save(s)
    first, second = await store.get(s.id), await store.get(s.id)
    assert first is not None and second is not None
    await store.save(_say(second, "newer"))
    with pytest.raises(SessionConflict):
        await store.save(_say(first, "older"))
    assert await _contents(docs, prefix, s.id) == ["turn 0", "turn 1", "newer"]


async def test_a_header_only_change_elsewhere_is_merged_and_this_append_reapplied(
    docs: Docs, prefix: str
) -> None:
    a, b = DocSessionStore(docs, prefix=prefix), DocSessionStore(docs, prefix=prefix)
    s = _session(2)
    s.metadata["brain"] = "anthropic"
    await a.save(s)
    in_b = await b.get(s.id)
    assert in_b is not None
    in_b.metadata["persona"] = "v9"  # B changed only the header (no turns)
    await b.save(in_b)
    s.metadata["brain_cutoff"] = 2  # A changed its own key and appended a turn
    await a.save(_say(s, "still consistent"))
    fresh = await DocSessionStore(docs, prefix=prefix).get(s.id)
    assert fresh is not None
    assert [t.content for t in fresh.turns][-1] == "still consistent"
    assert fresh.metadata == {"brain": "anthropic", "persona": "v9", "brain_cutoff": 2}
    assert s.metadata == fresh.metadata  # the caller's copy took the other writer's change
    await a.save(_say(s, "and again"))  # and A's next save is on the merged revision
    assert (await _contents(docs, prefix, s.id))[-2:] == ["still consistent", "and again"]


async def test_a_key_removed_here_stays_removed_after_the_merge(docs: Docs, prefix: str) -> None:
    a, b = DocSessionStore(docs, prefix=prefix), DocSessionStore(docs, prefix=prefix)
    s = _session(2)
    s.metadata.update(brain="gemini", brain_cutoff=1)
    await a.save(s)
    in_b = await b.get(s.id)
    assert in_b is not None
    in_b.user_id = "owner-2"  # B moved it to another owner id (reassign_user)
    await b.save(in_b)
    del s.metadata["brain_cutoff"]
    await a.save(_say(s, "x"))
    fresh = await DocSessionStore(docs, prefix=prefix).get(s.id)
    assert fresh is not None and fresh.user_id == "owner-2"
    assert fresh.metadata == {"brain": "gemini"}


async def test_a_conversation_deleted_elsewhere_is_not_brought_back(
    docs: Docs, prefix: str
) -> None:
    a, b = DocSessionStore(docs, prefix=prefix), DocSessionStore(docs, prefix=prefix)
    s = _session(2)
    await a.save(s)
    assert await b.delete(s.id) is True
    with pytest.raises(SessionConflict) as info:
        await a.save(_say(s, "too late"))
    assert "deleted" in str(info.value)
    assert await DocSessionStore(docs, prefix=prefix).get(s.id) is None
    assert await _turn_docs(docs, prefix, s.id) == 0


async def test_two_saves_from_the_same_revision_race_and_exactly_one_wins(
    docs: Docs, prefix: str
) -> None:
    a, b = DocSessionStore(docs, prefix=prefix), DocSessionStore(docs, prefix=prefix)
    s = _session(2)
    await a.save(s)
    in_a, in_b = await a.get(s.id), await b.get(s.id)
    assert in_a is not None and in_b is not None
    results = await asyncio.gather(
        a.save(_say(in_a, "A")), b.save(_say(in_b, "B")), return_exceptions=True
    )
    assert sorted(type(r).__name__ for r in results) == ["NoneType", "SessionConflict"]
    last = (await _contents(docs, prefix, s.id))[-1]
    assert last in ("A", "B") and await _turn_docs(docs, prefix, s.id) == 3


async def test_a_brand_new_session_never_replaces_an_existing_one(docs: Docs, prefix: str) -> None:
    store = DocSessionStore(docs, prefix=prefix)
    s = _session(2)
    await store.save(s)
    impostor = Session(id=s.id, user_id="owner")
    _say(impostor, "a different first message")
    with pytest.raises(SessionConflict):
        await DocSessionStore(docs, prefix=prefix).save(impostor)
    assert await _contents(docs, prefix, s.id) == ["turn 0", "turn 1"]


# ---- cost and the twin's transaction limits (MemoryDocs only) ------------------------------------


async def test_a_save_reads_the_header_once_and_an_unchanged_save_costs_nothing(
    prefix: str,
) -> None:
    docs = MemoryDocs()
    store = DocSessionStore(docs, prefix=prefix)
    s = _session(2)
    await store.save(s)
    reads, sets = docs.reads, docs.sets
    await store.save(_say(s, "one more"))
    assert docs.reads - reads == 1 and docs.sets - sets == 2  # header check; +1 turn +1 header
    reads, sets = docs.reads, docs.sets
    await store.save(s)
    assert (docs.reads, docs.sets) == (reads, sets)


async def test_a_long_first_save_keeps_every_commit_within_firestore_limits(prefix: str) -> None:
    docs = MemoryDocs()
    store = DocSessionStore(docs, prefix=prefix)
    s = _session(620)
    await store.save(s)
    assert docs.tx_sizes and max(docs.tx_sizes + docs.batch_sizes) <= MemoryDocs.MAX_BATCH
    assert docs.log[-1].path == f"{prefix}sessions/{s.id}"  # header last
    await store.save(_say(s, "next"))
    assert await _contents(docs, prefix, s.id) == [t.content for t in s.turns]


class AmbiguousDocs(MemoryDocs):
    """The next transaction commits, then reports a failure (a lost response)."""

    def __init__(self) -> None:
        super().__init__()
        self.fail_once = False

    async def transaction(self, fn: Callable[[DocTx], Awaitable[T]]) -> T:
        result = await super().transaction(fn)
        if self.fail_once:
            self.fail_once = False
            raise RuntimeError("deadline exceeded")
        return result


async def test_a_commit_that_reported_an_error_is_recognised_as_our_own(prefix: str) -> None:
    docs = AmbiguousDocs()
    store = DocSessionStore(docs, prefix=prefix)
    s = _session(2)
    await store.save(s)
    docs.fail_once = True
    with pytest.raises(RuntimeError):
        await store.save(_say(s, "landed anyway"))
    await store.save(_say(s, "next"))  # the stored revision is ours: consistent, not a conflict
    assert (await _contents(docs, prefix, s.id))[-2:] == ["landed anyway", "next"]


# ---- the API: 409 {error: session_conflict} -----------------------------------------------------


class ConflictingStore(InMemorySessionStore):
    """Saves until `conflict` is set, then refuses like DocSessionStore on a lost race."""

    def __init__(self) -> None:
        super().__init__()
        self.conflict = False

    async def save(self, session: Session) -> None:
        if self.conflict:
            raise SessionConflict("changed in another window")
        await super().save(session)


@pytest.fixture
async def conflict_app(settings: Settings) -> AsyncIterator[tuple[AsyncClient, ConflictingStore]]:
    store = ConflictingStore()
    app = create_app(settings, provider=MockProvider(), store=store)
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
            yield c, store


async def test_chat_answers_409_session_conflict(
    conflict_app: tuple[AsyncClient, ConflictingStore],
) -> None:
    client, store = conflict_app
    sid = (await client.post("/v1/chat", json={"message": "hi"})).json()["session_id"]
    store.conflict = True
    r = await client.post("/v1/chat", json={"message": "again", "session_id": sid})
    assert r.status_code == 409
    body = r.json()
    assert body["error"] == "session_conflict"
    assert "another window" in body["detail"] and "Traceback" not in body["detail"]


async def test_stream_ends_with_a_session_conflict_event(
    conflict_app: tuple[AsyncClient, ConflictingStore],
) -> None:
    client, store = conflict_app
    sid = (await client.post("/v1/chat", json={"message": "hi"})).json()["session_id"]
    store.conflict = True
    async with client.stream(
        "POST", "/v1/chat/stream", json={"message": "go", "session_id": sid}
    ) as r:
        body = "".join([chunk async for chunk in r.aiter_text()])
    final = body.rsplit("\x1e", 1)[1]
    assert '"error": "session_conflict"' in final
