# tests/test_book_seal_firestore.py -- R6 D6, D7, D9, D16 (builder B) against the Firestore emulator
# as well as MemoryDocs: real document paths (index, chunk subcollection, lease, tickets, settings),
# 512 KiB chunk documents under Firestore's 1 MiB cap, transactions for the lease and the index,
# prune and delete by path. The emulator leg skips cleanly when FIRESTORE_EMULATOR_HOST is unset
# (JARVIS_REQUIRE_EMULATOR=1 turns the skip into a failure, as the other Firestore tests do).
from __future__ import annotations

import asyncio
import datetime as dt
import os
import uuid
from collections.abc import AsyncIterator

import pytest
from book_seal_fakes import (
    NOW,
    UID,
    FakeNotifier,
    FakeSource,
    big_zip,
    make_release,
    ring,
    view,
)

from jarvis.buildbook.owner import BookSettingsPatch, BookSettingsStore, BookTickets
from jarvis.buildbook.seal import DocsBookVault
from jarvis.buildbook.sealer import BookSealer
from jarvis.storage.docs import Docs, MemoryDocs, Query, Set
from jarvis.vault.crypto import CHUNK_BYTES
from jarvis.vault.unlock import TicketGone

EMULATOR = os.environ.get("FIRESTORE_EMULATOR_HOST")
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
    return f"t{uuid.uuid4().hex[:10]}_"


async def test_seal_read_prune_and_delete_on_real_paths(docs: Docs, prefix: str) -> None:
    v = DocsBookVault(docs, ring(), prefix=prefix)
    sealed = []
    for n in (1, 2, 3, 4):
        source = big_zip(n, CHUNK_BYTES + 1000) if n == 4 else None
        release, files = make_release(n, source=source)
        sealed.append(await v.seal(UID, release, files, now=NOW.replace(minute=n)))
    assert sealed[3].file("source").count == 2
    assert await v.read(UID, sealed[3].id, "source") == files["source"]
    index = await docs.get(f"{prefix}book/{UID}")
    assert index is not None and set(index) == {"rev", "kid", "blob"}
    fid = sealed[0].file("book").fid
    assert await docs.get(f"{prefix}book/{UID}/book_chunks/{fid}_00") is not None
    assert await v.prune(UID) == (sealed[0].id,)
    assert await docs.get(f"{prefix}book/{UID}/book_chunks/{fid}_00") is None
    assert await v.delete_all(UID) == 3
    assert await docs.get(f"{prefix}book/{UID}") is None


async def test_racing_seals_keep_one_release(docs: Docs, prefix: str) -> None:
    a = DocsBookVault(docs, ring(), prefix=prefix)
    b = DocsBookVault(docs, ring(), prefix=prefix)
    release, files = make_release(1)
    got = await asyncio.gather(
        a.seal(UID, release, files, now=NOW), b.seal(UID, release, files, now=NOW)
    )
    assert got[0] == got[1] and len(await a.releases(UID)) == 1


async def test_the_sealer_lease_and_notice(docs: Docs, prefix: str) -> None:
    source, notes = FakeSource(*make_release(1)), FakeNotifier()
    v = DocsBookVault(docs, ring(), prefix=prefix)
    sealer = BookSealer(source, v, docs, notifier=notes, audit=None, prefix=prefix)
    assert (await sealer.ensure(UID)).state == "sealed"
    again = BookSealer(source, v, docs, notifier=notes, audit=None, prefix=prefix)
    assert (await again.ensure(UID)).state == "kept"
    assert notes.kinds() == ["book_sealed"]
    lease = await docs.get(f"{prefix}book_lease/{UID}")
    assert lease is not None and lease.get("holder") is None and lease.get("told")


async def test_tickets_and_settings(docs: Docs, prefix: str) -> None:
    tickets = BookTickets(docs, ring(), prefix=prefix)
    session = view("owner", at=dt.datetime.now(dt.UTC))
    t = await tickets.issue(UID, "3f2a1c9", session=session)
    taken = await tickets.take(UID, t.ticket)
    assert (taken.item, taken.session) == ("3f2a1c9", session.session_id)
    with pytest.raises(TicketGone):
        await tickets.take(UID, t.ticket)
    store = BookSettingsStore(docs, prefix=prefix)
    saved = await store.update(UID, BookSettingsPatch(creator_name="Akash", talk_on=False))
    assert await BookSettingsStore(docs, prefix=prefix).get(UID) == saved


async def test_an_unreadable_index_is_deleted_by_listing_its_chunks(
    docs: Docs, prefix: str
) -> None:
    vault = DocsBookVault(docs, ring(), prefix=prefix)
    release, files = make_release(1, source=big_zip(1, CHUNK_BYTES * 2))
    await vault.seal(UID, release, files, now=NOW)
    index = await docs.get(f"{prefix}book/{UID}")
    assert index is not None
    await docs.write([Set(f"{prefix}book/{UID}", {**index, "blob": "not a sealed blob"})])
    assert await vault.delete_all(UID) >= 1
    assert await docs.get(f"{prefix}book/{UID}") is None
    assert await docs.query(Query(f"{prefix}book/{UID}/book_chunks")) == []
