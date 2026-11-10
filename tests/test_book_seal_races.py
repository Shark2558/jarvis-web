# tests/test_book_seal_races.py -- R6 D6/D7/D16 (builder B), the review fixes: a Privacy delete
# that lands while a seal of the held release is in flight never brings it back; `told` and
# `failed` are claimed before a notice goes and hold more than one id; making room prunes one
# release at a time (and refuses, untouched, when even that can't fit); a run that blows up is
# told once; the empty index is removed only while it is still empty; an index that won't open
# can still be deleted.
from __future__ import annotations

import asyncio
import datetime as dt
from collections.abc import Awaitable, Callable, Sequence
from typing import Any

import pytest
from book_seal_fakes import (
    NOW,
    UID,
    FakeNotifier,
    FakeSource,
    FlakyDocs,
    big_zip,
    chunk_paths,
    failed_release,
    make_release,
    ring,
)

from jarvis.buildbook.model import FileKind, Release
from jarvis.buildbook.ports import BookError, BookVault
from jarvis.buildbook.privacy import BookSealedSource
from jarvis.buildbook.seal import DocsBookVault
from jarvis.buildbook.sealer import BookSealer
from jarvis.storage.docs import Delete, DocTx, MemoryDocs, Op, _MemoryTx

INDEX = f"jarvis_book/{UID}"


class World:
    def __init__(self, docs: MemoryDocs | FlakyDocs | None = None, limit_mb: int = 60) -> None:
        self.docs = docs or MemoryDocs()
        self.raw = self.docs.inner if isinstance(self.docs, FlakyDocs) else self.docs
        self.clock = {"now": NOW}
        self.source = FakeSource()
        self.notes = FakeNotifier()
        self.limit = limit_mb
        self.vault = self.new_vault()
        self.sealer = self.process()
        self.privacy = BookSealedSource(self.vault, self.sealer, limit_mb=limit_mb)

    def now(self) -> dt.datetime:
        return self.clock["now"]

    def new_vault(self, cls: type[DocsBookVault] = DocsBookVault) -> DocsBookVault:
        return cls(self.docs, ring(), limit_mb=self.limit, clock=self.now)

    def process(self, vault: BookVault | None = None) -> BookSealer:
        return BookSealer(
            self.source, vault or self.vault, self.docs, notifier=self.notes, audit=None,
            limit_mb=self.limit, clock=self.now,
        )  # fmt: skip

    def deploy(self, n: int, **kw: Any) -> Release:
        release, files = make_release(n, **kw)
        self.source.use(release, files)
        self.clock["now"] = NOW + dt.timedelta(hours=n)
        return release


# ---- a Privacy delete while the held release is being sealed (security 1, python 5) ----------


async def test_a_privacy_delete_while_the_lease_is_taken_stops_the_seal_before_any_work() -> None:
    w = World()
    w.deploy(1)
    sealer = w.process()
    take = sealer._st.lease

    async def lease_then_delete(uid: str) -> str | None:
        holder = await take(uid)  # the held check before the lease saw nothing held
        await w.privacy.delete(uid)
        return holder

    sealer._st.lease = lease_then_delete  # type: ignore[method-assign]
    assert (await sealer.ensure(UID)).state == "held"
    assert w.source.reads == 0  # nothing read, nothing encrypted
    assert await w.vault.releases(UID) == () and chunk_paths(w.raw) == []
    assert w.notes.sent == []
    assert w.raw._data[f"jarvis_book_lease/{UID}"].get("holder") is None  # given back


class DeleteAt(DocsBookVault):
    """Runs the owner's Privacy delete at one step of a seal (once)."""

    step = ""
    privacy: BookSealedSource | None = None

    async def _fire(self, step: str, uid: str) -> None:
        if self.step == step and self.privacy is not None:
            self.step = ""
            await self.privacy.delete(uid)


async def test_a_privacy_delete_after_the_encryption_stops_the_seal() -> None:
    w = World()
    w.deploy(1)

    class BeforePending(DeleteAt):
        def _seal_file(self, *a: Any) -> Any:
            out = super()._seal_file(*a)
            self.step = "pending" if self.step == "armed" else self.step
            return out

        async def _change(self, uid: str, fn: Any, **kw: Any) -> Any:
            await self._fire("pending", uid)
            return await super()._change(uid, fn, **kw)

    v = w.new_vault(BeforePending)
    v.privacy, v.step = w.privacy, "armed"
    assert (await w.process(v).ensure(UID)).state == "held"
    assert await w.vault.releases(UID) == () and chunk_paths(w.raw) == []
    assert w.notes.sent == []  # no "sealed", and no "could not be sealed; I'll try again"


async def test_a_privacy_delete_before_the_commit_stops_the_seal_without_a_failure_notice() -> None:
    w = World()
    w.deploy(1)

    class BeforeCommit(DeleteAt):
        async def _commit(self, uid: str, entry: Any, parts: Any) -> Any:
            await self._fire("commit", uid)
            return await super()._commit(uid, entry, parts)

    v = w.new_vault(BeforeCommit)
    v.privacy, v.step = w.privacy, "commit"
    assert (await w.process(v).ensure(UID)).state == "held"
    assert await w.vault.releases(UID) == () and chunk_paths(w.raw) == []
    assert w.notes.sent == []
    w.deploy(2)
    assert (await w.process().ensure(UID)).state == "sealed"  # the next release seals


# ---- told and failed: claimed first, more than one id (python 1, 2; security 6) --------------


async def test_alternating_sealed_releases_never_tell_again() -> None:
    w = World()
    for n in (1, 2):
        w.deploy(n)
        assert (await w.sealer.ensure(UID)).state == "sealed"
    for n in (1, 2, 1, 2):  # a rollback or a traffic split: cold starts of either revision
        w.deploy(n)
        assert (await w.process().ensure(UID)).state == "kept"
    assert w.notes.kinds() == ["book_sealed", "book_sealed"]


async def test_two_runs_at_once_tell_a_failure_once() -> None:
    w = World()
    w.notes.slow = True
    w.source.use(failed_release(1))
    outs = await asyncio.gather(w.process().ensure(UID), w.process().ensure(UID))
    assert [o.state for o in outs] == ["unbuilt", "unbuilt"]
    assert w.notes.kinds() == ["book_seal_failed"]


async def test_two_tampered_reads_at_once_tell_once() -> None:
    w = World()
    rid = w.deploy(1).id
    await w.sealer.ensure(UID)
    w.notes.slow = True
    await asyncio.gather(
        w.process().report_tampered(UID, rid, "R6"), w.process().report_tampered(UID, rid, "R6")
    )
    assert w.notes.kinds() == ["book_sealed", "book_seal_failed"]


async def test_a_failure_notice_that_could_not_go_is_sent_by_the_next_run() -> None:
    w = World()
    w.source.use(failed_release(1))
    w.notes.fail = True
    await w.sealer.ensure(UID)
    w.notes.fail = False
    await w.process().ensure(UID)
    await w.process().ensure(UID)
    assert w.notes.kinds() == ["book_seal_failed"]


async def test_many_failures_never_let_an_old_one_be_told_again() -> None:
    w = World()
    rids = [f"{n:07x}" for n in range(1, 11)]
    for rid in rids:
        await w.sealer.report_tampered(UID, rid, "R6")
    await w.process().report_tampered(UID, rids[0], "R6")
    assert w.notes.kinds() == ["book_seal_failed"] * len(rids)


# ---- making room under the cap (python 3) -------------------------------------------------


async def test_room_is_made_one_release_at_a_time_until_the_new_one_fits() -> None:
    w = World(limit_mb=2)
    ids = []
    for n in (1, 2):
        ids.append(w.deploy(n, source=big_zip(n, 900_000)).id)
        assert (await w.sealer.ensure(UID)).state == "sealed"
    w.deploy(3, source=big_zip(3, 900_000))
    out = await w.sealer.ensure(UID)
    assert out.state == "sealed" and out.removed == (ids[0],) and out.kept == 2
    assert [r.id for r in await w.vault.releases(UID)][1:] == [ids[1]]


async def test_a_release_that_cannot_fit_is_refused_and_nothing_is_pruned() -> None:
    w = World(limit_mb=1)
    first = w.deploy(1, source=big_zip(1, 500_000)).id
    assert (await w.sealer.ensure(UID)).state == "sealed"
    big = w.deploy(2, source=big_zip(2, 700_000))
    for sealer in (w.sealer, w.process()):
        assert (await sealer.ensure(UID)).state == "failed"
    assert [r.id for r in await w.vault.releases(UID)] == [first]
    assert w.notes.kinds() == ["book_sealed", "book_seal_failed"]
    words = w.notes.sent[-1][2]
    assert f"({big.id})" in words and "1 MB storage limit" in words


async def test_a_release_larger_than_the_limit_alone_is_refused_untouched() -> None:
    w = World(limit_mb=1)
    w.deploy(1, source=big_zip(1, 1_200_000))
    assert (await w.sealer.ensure(UID)).state == "failed"
    assert chunk_paths(w.raw) == [] and "storage limit" in w.notes.sent[-1][2]


# ---- a run that blows up is told (python 7) -------------------------------------------------


async def test_a_run_that_blows_up_is_told_once() -> None:
    w = World()
    rid = w.deploy(1).id

    def boom(kind: FileKind) -> bytes:
        raise OSError("package resource")

    w.source.read = boom  # type: ignore[method-assign]
    for _ in range(2):
        assert (await w.sealer.ensure_bounded(UID, within_s=5)).state == "failed"
    assert w.notes.kinds() == ["book_seal_failed"] and f"({rid})" in w.notes.sent[0][2]


async def test_a_vault_outage_is_told_once() -> None:
    w = World()
    w.deploy(1)

    async def down(uid: str) -> Any:
        raise BookError("The vault can't be reached right now.")

    w.vault.releases = down  # type: ignore[method-assign]
    for _ in range(2):
        assert (await w.sealer.ensure(UID)).state == "failed"
    assert w.notes.kinds() == ["book_seal_failed"]


# ---- the empty index goes only while it is still empty (python 5) ----------------------------


class RaceDocs(FlakyDocs):
    """Runs `race` just before the first step that would remove the index document."""

    def __init__(self) -> None:
        super().__init__()
        self.race: Callable[[], Awaitable[None]] | None = None

    async def _maybe_race(self) -> None:
        race, self.race = self.race, None
        if race is not None:
            await race()

    async def write(self, ops: Sequence[Op]) -> None:
        if any(isinstance(o, Delete) and o.path == INDEX for o in ops):
            await self._maybe_race()
        await super().write(ops)

    async def transaction(self, fn: Callable[[DocTx], Awaitable[Any]]) -> Any:
        if self.race is not None:
            probe = _MemoryTx(self.inner)
            try:
                await fn(probe)
            except Exception:  # noqa: BLE001 - a dry run only
                pass
            if any(isinstance(o, Delete) and o.path == INDEX for o in probe.ops):
                await self._maybe_race()
        return await super().transaction(fn)


async def test_a_seal_that_lands_while_everything_is_deleted_keeps_its_index_entry() -> None:
    docs = RaceDocs()
    v = DocsBookVault(docs, ring())
    other = DocsBookVault(docs.inner, ring())
    for n in (1, 2):
        release, files = make_release(n)
        await v.seal(UID, release, files, now=NOW + dt.timedelta(minutes=n))
    late, late_files = make_release(3)

    async def race() -> None:
        await other.seal(UID, late, late_files, now=NOW + dt.timedelta(minutes=3))

    docs.race = race
    assert await v.delete_all(UID) == 2
    assert [r.id for r in await v.releases(UID)] == [late.id]
    assert await v.read(UID, late.id, "source") == late_files["source"]


# ---- an index that won't open can still be deleted (security 2, python 9) -------------------


async def test_an_unreadable_index_is_deleted_with_every_chunk_and_sealing_resumes() -> None:
    w = World()
    for n in (1, 2):
        w.deploy(n)
        await w.sealer.ensure(UID)
    w.raw._data[INDEX]["blob"] = w.raw._data[INDEX]["blob"][:-4] + "AAA="
    view = await w.privacy.describe(UID)
    assert view.delete == "passkey" and view.count is None and "can't be read" in view.note
    assert await w.privacy.delete(UID) >= 1
    assert INDEX not in w.raw._data and chunk_paths(w.raw) == []
    assert (await w.privacy.describe(UID)).count == 0
    w.deploy(3)
    assert (await w.process().ensure(UID)).state == "sealed"


async def test_an_unreadable_index_with_many_chunks_is_swept_completely(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from jarvis.buildbook import seal_chunks

    monkeypatch.setattr(seal_chunks, "LIST_PAGE", 2)  # several pages of listing
    w = World()
    w.deploy(1, source=big_zip(1, 3_000_000))
    await w.sealer.ensure(UID)
    w.raw._data[INDEX]["blob"] = "not a sealed blob"
    assert len(chunk_paths(w.raw)) > 2
    await w.vault.delete_all(UID)
    assert INDEX not in w.raw._data and chunk_paths(w.raw) == []


async def test_an_outage_is_never_taken_for_an_unreadable_index() -> None:
    docs = FlakyDocs()
    w = World(docs)
    w.deploy(1)
    await w.sealer.ensure(UID)
    docs.fail_reads = True
    try:
        await w.vault.delete_all(UID)
        raised = False
    except BookError:
        raised = True
    docs.fail_reads = False
    assert raised and INDEX in w.raw._data and chunk_paths(w.raw)
