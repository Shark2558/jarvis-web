# tests/test_documents_store.py — slice 10 E: attachment header + chunk docs on the Docs port
# (Firestore in prod, MemoryDocs here): header written last in one commit, owner-checked atomic
# binding to a conversation, queries by conversation and for waiting uploads, full delete.
from __future__ import annotations

from datetime import UTC, datetime

import pytest

from jarvis.documents.chunking import Chunk
from jarvis.documents.models import Attachment, new_doc_id
from jarvis.documents.store import CACHE_DOCS, AttachmentStore, NotAvailable
from jarvis.storage.docs import Create, MemoryDocs, Set


def att(owner: str = "u1", **kw: object) -> Attachment:
    base: dict[str, object] = {
        "id": new_doc_id(),
        "owner": owner,
        "name": "Plan.pdf",
        "kind": "pdf",
        "size": 1234,
        "pages": 2,
        "pages_total": 2,
        "words": 10,
        "chars": 60,
        "chunk_count": 2,
        "preview": "hello",
        "created_at": datetime(2026, 11, 1, tzinfo=UTC),
    }
    return Attachment.model_validate(base | kw)


CHUNKS = [Chunk("first chunk ", 0, 1, 1), Chunk("second chunk", 12, 2, 2)]


@pytest.fixture
def docs() -> MemoryDocs:
    return MemoryDocs()


@pytest.fixture
def store(docs: MemoryDocs) -> AttachmentStore:
    return AttachmentStore(docs, prefix="t_")


async def test_create_writes_chunks_then_the_header_in_one_commit(
    store: AttachmentStore, docs: MemoryDocs
) -> None:
    a = att()
    await store.create(a, CHUNKS)
    assert docs.batch_sizes == [3]
    assert isinstance(docs.log[-1], Create) and docs.log[-1].path == f"t_attachments/{a.id}"
    assert [op.path for op in docs.log[:2]] == [
        f"t_attachments/{a.id}/chunks/000001",
        f"t_attachments/{a.id}/chunks/000002",
    ]
    assert isinstance(docs.log[0], Set) and docs.log[0].data["text"] == "first chunk "
    assert await store.get(a.id) == a


async def test_chunks_come_back_in_order_and_are_cached(
    store: AttachmentStore, docs: MemoryDocs
) -> None:
    a = att()
    await store.create(a, CHUNKS)
    assert await store.chunks(a) == CHUNKS
    reads = docs.reads
    assert await store.chunks(a) == CHUNKS
    assert docs.reads == reads


async def test_a_part_reads_only_its_own_chunks(store: AttachmentStore, docs: MemoryDocs) -> None:
    # integration review M2: doc_read never re-reads the whole document for each part
    many = [Chunk(f"chunk {i} ", i * 9, None, None) for i in range(40)]
    a = att(chunk_count=40)
    await store.create(a, many)
    cold = AttachmentStore(docs, prefix="t_")  # another process: nothing cached
    reads = docs.reads
    assert await cold.part(a, 4, 6) == many[4:6]
    assert docs.reads - reads == 2
    assert await cold.part(a, 39, 41) == many[39:]  # the last part may be a single chunk
    assert await cold.part(a, 40, 42) == []
    await store.chunks(a)  # a document already cached is sliced, not read again
    reads = docs.reads
    assert await store.part(a, 0, 2) == many[:2] and docs.reads == reads


async def test_reading_parts_never_pushes_searched_documents_out_of_the_cache(
    store: AttachmentStore, docs: MemoryDocs
) -> None:
    searched = att()
    await store.create(searched, CHUNKS)
    await store.chunks(searched)
    for _ in range(CACHE_DOCS + 2):  # parts of other documents: read, not cached
        other = att()
        await store.create(other, CHUNKS)
        await store.part(other, 0, 2)
    reads = docs.reads
    assert await store.chunks(searched) == CHUNKS and docs.reads == reads


async def test_get_refuses_a_malformed_id_without_reading(
    store: AttachmentStore, docs: MemoryDocs
) -> None:
    assert await store.get("../t_sessions/x") is None and docs.reads == 0


async def test_bind_ties_waiting_uploads_to_one_conversation_and_turn(
    store: AttachmentStore,
) -> None:
    a, b = att(), att()
    await store.create(a, CHUNKS)
    await store.create(b, CHUNKS)
    bound = await store.bind([a.id, b.id], owner="u1", session_id="s1", turn_id="t1")
    assert [(x.session, x.turn) for x in bound] == [("s1", "t1"), ("s1", "t1")]
    got = await store.get(a.id)
    assert got is not None and not got.waiting
    assert {x.id for x in await store.in_session("s1")} == {a.id, b.id}
    assert await store.waiting() == []


async def test_bind_is_all_or_nothing_and_owner_checked(store: AttachmentStore) -> None:
    mine, theirs = att("u1"), att("u2")
    await store.create(mine, CHUNKS)
    await store.create(theirs, CHUNKS)
    with pytest.raises(NotAvailable):
        await store.bind([mine.id, theirs.id], owner="u1", session_id="s1", turn_id="t1")
    still = await store.get(mine.id)
    assert still is not None and still.waiting  # nothing was bound
    with pytest.raises(NotAvailable):
        await store.bind([new_doc_id()], owner="u1", session_id="s1", turn_id="t1")


async def test_a_sent_attachment_cannot_be_sent_again(store: AttachmentStore) -> None:
    a = att()
    await store.create(a, CHUNKS)
    await store.bind([a.id], owner="u1", session_id="s1", turn_id="t1")
    with pytest.raises(NotAvailable):
        await store.bind([a.id], owner="u1", session_id="s2", turn_id="t9")


async def test_unbind_returns_files_bound_to_that_turn_to_waiting(store: AttachmentStore) -> None:
    a, b = att(), att()
    await store.create(a, CHUNKS)
    await store.create(b, CHUNKS)
    await store.bind([a.id], owner="u1", session_id="s1", turn_id="t1")
    await store.bind([b.id], owner="u1", session_id="s1", turn_id="t2")
    await store.unbind([a.id, b.id], owner="u1", turn_id="t1")
    back, other = await store.get(a.id), await store.get(b.id)
    assert back is not None and back.waiting and back.session == ""
    assert other is not None and other.turn == "t2"  # bound to another turn: untouched
    await store.unbind([a.id], owner="u2", turn_id="t1")  # not theirs: nothing happens


async def test_delete_removes_every_chunk_and_the_header(
    store: AttachmentStore, docs: MemoryDocs
) -> None:
    a = att()
    await store.create(a, CHUNKS)
    await store.chunks(a)  # cached
    await store.delete(a.id)
    assert await store.get(a.id) is None
    assert not [p for p in docs._data if a.id in p]
    assert await store.chunks(a) == []  # the cache went with it


async def test_waiting_lists_only_unsent_uploads(store: AttachmentStore) -> None:
    a, b = att(), att()
    await store.create(a, CHUNKS)
    await store.create(b, CHUNKS)
    await store.bind([b.id], owner="u1", session_id="s1", turn_id="t1")
    assert [x.id for x in await store.waiting()] == [a.id]
