# tests/test_book_seal.py -- R6 D6 (builder B): the sealed build books in the vault family. AADs
# exactly as D6, 512 KiB chunks under a per-file DEK, at most 6 chunks a commit and the index last,
# idempotent seal, prune index-first (crypto-shred) then chunks with retries, reads that fail
# closed, the cap, half-finished seals cleared, races, and nothing readable in storage.
from __future__ import annotations

import asyncio
import datetime as dt
import json
from collections.abc import Awaitable, Callable, Sequence
from typing import Any

import pytest
from book_seal_fakes import (
    NOW,
    OTHER,
    UID,
    FlakyDocs,
    big_zip,
    chunk_paths,
    make_release,
    ring,
)

from jarvis.buildbook.model import KEEP, SealedRelease
from jarvis.buildbook.ports import BookError, BookOff, BookUnavailable, BookVault, VaultTampered
from jarvis.buildbook.seal import PENDING_TTL_S, WRITE_GROUP, DocsBookVault
from jarvis.buildbook.seal_index import BookCrypto, chunk_aad, dek_aad, index_aad
from jarvis.storage.docs import Delete, DocTx, MemoryDocs, Op, Set
from jarvis.vault.crypto import CHUNK_BYTES

INDEX = f"jarvis_book/{UID}"


def vault(docs: MemoryDocs | FlakyDocs, limit_mb: int = 60) -> DocsBookVault:
    return DocsBookVault(docs, ring(), limit_mb=limit_mb)


async def seal_n(v: DocsBookVault, n: int, **kw: object) -> SealedRelease:
    release, files = make_release(n, **kw)  # type: ignore[arg-type]
    return await v.seal(UID, release, files, now=NOW + dt.timedelta(minutes=n))


# ---- the envelope ------------------------------------------------------------------------------


def test_the_aads_are_d6_word_for_word() -> None:
    assert index_aad(UID) == f"book/index/{UID}/v1"
    assert (
        dek_aad(UID, "3f2a1c9", "bf_0123456789ab") == f"book/dek/{UID}/3f2a1c9/bf_0123456789ab/v1"
    )
    assert (
        chunk_aad(UID, "3f2a1c9", "bf_0123456789ab", 2, 5)
        == f"book/chunk/{UID}/3f2a1c9/bf_0123456789ab/2/5/v1"
    )


def test_a_file_is_cut_into_512_kib_chunks_under_its_own_data_key() -> None:
    c = BookCrypto(ring())
    data = bytes(CHUNK_BYTES * 2 + 10)
    wrapped, blobs = c.seal(UID, "3f2a1c9", "bf_0123456789ab", data)
    assert len(blobs) == 3
    dek = c.unwrap(UID, "3f2a1c9", "bf_0123456789ab", wrapped)
    plain = [
        c.open_chunk(dek, UID, "3f2a1c9", "bf_0123456789ab", n, 3, b) for n, b in enumerate(blobs)
    ]
    assert b"".join(plain) == data
    # a chunk moved to another position, file, release or owner does not open
    from jarvis.integrations.vault import VaultError

    for args in [
        (UID, "3f2a1c9", "bf_0123456789ab", 1, 3),
        (UID, "3f2a1c9", "bf_ffffffffffff", 0, 3),
        (UID, "0000000", "bf_0123456789ab", 0, 3),
        (OTHER, "3f2a1c9", "bf_0123456789ab", 0, 3),
        (UID, "3f2a1c9", "bf_0123456789ab", 0, 4),
    ]:
        with pytest.raises(VaultError):
            c.open_chunk(dek, *args[:4], args[4], blobs[0])  # type: ignore[arg-type]
    with pytest.raises(VaultError):  # a vault (R2) data key AAD never unwraps a book key
        ring().unwrap(wrapped, aad=f"vault/dek/{UID}/3f2a1c9/bf_0123456789ab/v1")


def test_the_index_is_sealed_under_its_own_purpose() -> None:
    c = BookCrypto(ring())
    blob = c.seal_index(UID, b"[]")
    assert c.open_index(UID, blob) == b"[]"
    from jarvis.integrations.vault import VaultError

    with pytest.raises(VaultError):
        c.open_index(OTHER, blob)
    with pytest.raises(VaultError):
        ring().cipher("vault_index").decrypt(blob, aad=index_aad(UID))


# ---- seal and read -----------------------------------------------------------------------------


async def test_the_vault_meets_its_port() -> None:
    assert isinstance(vault(MemoryDocs()), BookVault)


async def test_seal_then_read_both_files_back() -> None:
    docs = MemoryDocs()
    v = vault(docs)
    release, files = make_release(1, source=big_zip(1, CHUNK_BYTES * 2 + 77))
    sealed = await v.seal(UID, release, files, now=NOW)
    assert sealed.id == release.id and sealed.label == "R6" and sealed.sealed_at == NOW.isoformat()
    assert sealed.file("source").count == 3 and sealed.file("book").count == 1
    assert sealed.file("source").sha256 == release.source_sha256
    assert await v.read(UID, release.id, "book") == files["book"]
    assert await v.read(UID, release.id, "source") == files["source"]
    assert await v.used_bytes(UID) == len(files["book"]) + len(files["source"])
    assert [r.id for r in await v.releases(UID)] == [release.id]
    assert len(chunk_paths(docs)) == 4
    assert all(p.startswith(f"jarvis_book/{UID}/book_chunks/bf_") for p in chunk_paths(docs))


async def test_storage_holds_only_ciphertext_and_the_index_document_has_three_fields() -> None:
    docs = MemoryDocs()
    release, files = make_release(1)
    await vault(docs).seal(UID, release, files, now=NOW)
    index = docs._data[INDEX]
    assert set(index) == {"rev", "kid", "blob"} and index["kid"] == "tk1"
    everything = json.dumps(docs._data)
    for clear in (release.sha, "JARVIS-source", "Eight layers", files["book"][:60].decode()):
        assert clear not in everything


async def test_at_most_six_chunks_a_commit_and_the_index_last() -> None:
    docs = MemoryDocs()
    v = vault(docs)
    release, files = make_release(1, source=big_zip(1, CHUNK_BYTES * 13))
    await v.seal(UID, release, files, now=NOW)
    assert WRITE_GROUP == 6
    chunk_batches = [s for s in docs.batch_sizes if s > 0]
    assert chunk_batches and max(chunk_batches) <= 6
    last_set = [op for op in docs.log if isinstance(op, Set)][-1]
    assert last_set.path == INDEX  # the release exists only once its index entry is written


async def test_sealing_the_same_release_again_changes_nothing() -> None:
    docs = MemoryDocs()
    v = vault(docs)
    release, files = make_release(1)
    first = await v.seal(UID, release, files, now=NOW)
    writes = docs.sets
    again = await v.seal(UID, release, files, now=NOW + dt.timedelta(hours=1))
    assert again == first and docs.sets == writes


async def test_releases_are_newest_first() -> None:
    v = vault(MemoryDocs())
    ids = [(await seal_n(v, n)).id for n in (1, 2, 3)]
    assert [r.id for r in await v.releases(UID)] == ids[::-1]


async def test_a_release_must_bring_its_own_two_good_files() -> None:
    v = vault(MemoryDocs())
    release, files = make_release(1)
    with pytest.raises(ValueError):
        await v.seal(UID, release, {"book": files["book"]}, now=NOW)
    with pytest.raises(BookUnavailable):  # bytes that are not this release's
        await v.seal(UID, release, {**files, "source": files["source"] + b"x"}, now=NOW)
    from book_seal_fakes import failed_release

    with pytest.raises(BookUnavailable):
        await v.seal(UID, failed_release(2), files, now=NOW)
    assert await v.releases(UID) == ()


async def test_past_the_total_cap_nothing_is_sealed() -> None:
    docs = MemoryDocs()
    v = vault(docs, limit_mb=20)
    await seal_n(v, 1, source=big_zip(1, 12 * 1024 * 1024))
    with pytest.raises(BookOff):
        await seal_n(v, 2, source=big_zip(2, 9 * 1024 * 1024))
    assert len(await v.releases(UID)) == 1 and len(chunk_paths(docs)) == 25 + 1  # source + book


async def test_another_owner_sees_nothing_and_a_copied_index_does_not_open() -> None:
    docs = MemoryDocs()
    v = vault(docs)
    await seal_n(v, 1)
    assert await v.releases(OTHER) == ()
    docs._data[f"jarvis_book/{OTHER}"] = dict(docs._data[INDEX])
    with pytest.raises(VaultTampered):
        await v.releases(OTHER)


# ---- reads fail closed -------------------------------------------------------------------------


async def test_a_tampered_chunk_fails_closed() -> None:
    docs = MemoryDocs()
    v = vault(docs)
    sealed = await seal_n(v, 1)
    path = next(p for p in chunk_paths(docs) if sealed.file("source").fid in p)
    blob = docs._data[path]["blob"]
    docs._data[path]["blob"] = blob[:-6] + ("AAAA==" if not blob.endswith("AAAA==") else "BBBB==")
    with pytest.raises(VaultTampered):
        await v.read(UID, sealed.id, "source")


async def test_a_chunk_swapped_in_from_another_file_or_missing_fails_closed() -> None:
    docs = MemoryDocs()
    v = vault(docs)
    sealed = await seal_n(v, 1)
    book_path = f"jarvis_book/{UID}/book_chunks/{sealed.file('book').fid}_00"
    source_path = f"jarvis_book/{UID}/book_chunks/{sealed.file('source').fid}_00"
    docs._data[book_path] = dict(docs._data[source_path])
    with pytest.raises(VaultTampered):
        await v.read(UID, sealed.id, "book")
    del docs._data[source_path]
    with pytest.raises(VaultTampered):
        await v.read(UID, sealed.id, "source")


async def test_bytes_that_do_not_match_their_sha256_fail_closed() -> None:
    """An index entry whose digest no longer matches what its chunks hold (e.g. an index
    restored from a backup): the read refuses rather than hand over unverified bytes."""
    docs = MemoryDocs()
    v = vault(docs)
    sealed = await seal_n(v, 1)
    c = BookCrypto(ring())
    raw = json.loads(c.open_index(UID, docs._data[INDEX]["blob"]))
    raw["releases"][0]["files"][0]["sha256"] = "0" * 64
    docs._data[INDEX]["blob"] = c.seal_index(UID, json.dumps(raw).encode())
    with pytest.raises(VaultTampered):
        await v.read(UID, sealed.id, raw["releases"][0]["files"][0]["kind"])


async def test_a_tampered_index_fails_closed_and_is_never_overwritten() -> None:
    docs = MemoryDocs()
    v = vault(docs)
    await seal_n(v, 1)
    docs._data[INDEX]["blob"] = docs._data[INDEX]["blob"][:-4] + "AAA="
    before = dict(docs._data[INDEX])
    for call in (
        v.releases(UID),
        v.used_bytes(UID),
        v.prune(UID),
        seal_n(v, 2),
        v.read(UID, "0000000", "book"),
    ):
        with pytest.raises(VaultTampered):
            await call
    assert docs._data[INDEX] == before
    docs._data[INDEX] = {"rev": "1", "kid": "tk1", "blob": 5}
    with pytest.raises(VaultTampered):
        await v.releases(UID)


async def test_an_unknown_release_is_a_lookup_error() -> None:
    v = vault(MemoryDocs())
    await seal_n(v, 1)
    with pytest.raises(LookupError):
        await v.read(UID, "fffffff", "book")


async def test_a_storage_outage_is_not_called_tampering() -> None:
    docs = FlakyDocs()
    v = vault(docs)
    await seal_n(v, 1)
    docs.fail_reads = True
    with pytest.raises(BookError) as err:
        await v.releases(UID)
    assert not isinstance(err.value, VaultTampered)


# ---- retention: prune index first, then chunks -----------------------------------------------


async def test_a_fourth_release_prunes_the_oldest_index_first_then_its_chunks() -> None:
    docs = MemoryDocs()
    v = vault(docs)
    sealed = [await seal_n(v, n) for n in (1, 2, 3, 4)]
    start = len(docs.log)
    assert await v.prune(UID) == (sealed[0].id,)
    assert KEEP == 3 and [r.id for r in await v.releases(UID)] == [s.id for s in sealed[:0:-1]]
    gone = {f.fid for f in sealed[0].files}
    assert not [p for p in chunk_paths(docs) if any(fid in p for fid in gone)]
    with pytest.raises(LookupError):
        await v.read(UID, sealed[0].id, "book")
    # the index went first (crypto-shred), then the chunks by path
    ops = docs.log[start:]
    assert isinstance(ops[0], Set) and ops[0].path == INDEX
    assert {type(op) for op in ops[1:-1]} == {Delete}
    assert await v.prune(UID) == ()


async def test_prune_keeps_what_it_is_told() -> None:
    v = vault(MemoryDocs())
    for n in (1, 2, 3):
        await seal_n(v, n)
    assert len(await v.prune(UID, keep=2)) == 1 and len(await v.releases(UID)) == 2
    with pytest.raises(ValueError):
        await v.prune(UID, keep=0)


async def test_a_chunk_delete_that_fails_is_retried_by_the_next_run() -> None:
    docs = FlakyDocs()
    v = vault(docs)
    sealed = [await seal_n(v, n) for n in (1, 2, 3, 4)]
    docs.fail_deletes = 2  # both of the shredded release's chunk sets
    assert await v.prune(UID) == (sealed[0].id,)  # the release is gone (crypto-shredded) ...
    with pytest.raises(LookupError):
        await v.read(UID, sealed[0].id, "source")
    left = [p for p in chunk_paths(docs.inner) if sealed[0].file("source").fid in p]
    assert left  # ... its chunks wait for the next run
    assert await v.prune(UID) == ()
    assert not [p for p in chunk_paths(docs.inner) if sealed[0].file("source").fid in p]


# ---- half-finished seals, races, delete -----------------------------------------------------


async def test_a_seal_that_fails_half_way_leaves_nothing_behind() -> None:
    docs = FlakyDocs()
    v = vault(docs)
    release, files = make_release(1, source=big_zip(1, CHUNK_BYTES * 8))
    real_write = docs.inner.write
    calls = {"n": 0}

    async def second_write_fails(ops: Sequence[Op]) -> None:
        calls["n"] += 1
        if calls["n"] == 2:  # the second group of chunks
            raise RuntimeError("write failed")
        await real_write(ops)

    docs.inner.write = second_write_fails  # type: ignore[method-assign]
    with pytest.raises(BookError):
        await v.seal(UID, release, files, now=NOW)
    assert chunk_paths(docs.inner) == [] and await v.releases(UID) == ()
    assert await v.prune(UID) == ()


async def test_a_seal_cut_off_by_a_crash_is_swept_after_its_time() -> None:
    docs = MemoryDocs()
    clock = {"now": NOW}
    v = DocsBookVault(docs, ring(), clock=lambda: clock["now"])
    release, files = make_release(1)

    async def crash_after_chunks(*_: object, **__: object) -> None:
        raise asyncio.CancelledError

    original = v._commit  # the index step never runs: the process died after the chunks
    v._commit = crash_after_chunks  # type: ignore[assignment,method-assign]
    with pytest.raises(asyncio.CancelledError):
        await v.seal(UID, release, files, now=NOW)
    v._commit = original  # type: ignore[method-assign]
    assert chunk_paths(docs) and await v.releases(UID) == ()
    assert await v.prune(UID) == () and chunk_paths(docs)  # still in flight: left alone
    clock["now"] = NOW + dt.timedelta(seconds=PENDING_TTL_S + 1)
    await v.prune(UID)
    assert chunk_paths(docs) == []


async def test_two_racing_seals_of_one_release_keep_one_and_leave_no_stray_chunks() -> None:
    docs = MemoryDocs()
    a, b = vault(docs), vault(docs)
    release, files = make_release(1)
    got = await asyncio.gather(
        a.seal(UID, release, files, now=NOW), b.seal(UID, release, files, now=NOW)
    )
    assert got[0] == got[1]
    assert len(await a.releases(UID)) == 1
    assert len(chunk_paths(docs)) == 2  # one book chunk + one source chunk
    assert await a.read(UID, release.id, "source") == files["source"]


async def test_delete_all_shreds_every_release_and_a_seal_in_flight_cannot_bring_one_back() -> None:
    docs = FlakyDocs()
    v = vault(docs)
    await seal_n(v, 1)
    await seal_n(v, 2)
    assert await v.delete_all(UID) == 2
    assert await v.releases(UID) == () and chunk_paths(docs.inner) == []
    assert INDEX not in docs.inner._data
    # a seal whose chunks are written when the owner deletes everything: its commit is refused
    release, files = make_release(3)
    real = docs.inner.transaction
    calls = {"n": 0}

    async def tx(fn: Callable[[DocTx], Awaitable[Any]]) -> Any:
        calls["n"] += 1
        if calls["n"] == 2:  # the seal's index commit: the owner deletes everything just before
            await v.delete_all(UID)
        return await real(fn)

    docs.inner.transaction = tx  # type: ignore[method-assign]
    with pytest.raises(BookError):
        await v.seal(UID, release, files, now=NOW)
    docs.inner.transaction = real  # type: ignore[method-assign]
    assert await v.releases(UID) == () and chunk_paths(docs.inner) == []
    assert await v.delete_all(UID) == 0
