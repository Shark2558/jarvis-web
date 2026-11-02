# tests/test_undo_bin.py — slice 11 D1: the "Recently deleted" bin (jarvis.undo) on the Docs port.
# Written before the implementation: snapshots kept per owner for 30 days, fail-closed keep,
# idempotent restore (claimed in a transaction), plain words for unknown / expired ids, the sweep.
from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from jarvis.storage.docs import MemoryDocs
from jarvis.undo.models import (
    RETENTION_DAYS,
    DeletedItem,
    RestoreStatus,
    UndoRef,
    all_owner_authored,
)
from jarvis.undo.service import Restored, SnapshotFailed, StillThere, UndoBin, record_made
from jarvis.undo.store import ClaimResult, DeletedStore

NOW = datetime(2027, 1, 15, 3, 0, tzinfo=UTC)
UID = "u_owner"


class Clock:
    def __init__(self) -> None:
        self.now = NOW

    def __call__(self) -> datetime:
        return self.now


class FakeRestorer:
    def __init__(self, *, fail: Exception | None = None, pause: bool = False) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.outside: list[bool] = []  # slice 11 D8: what the bin said about each restore
        self.fail = fail
        self.pause = pause  # yield to the event loop mid-restore, so a racing call can run

    async def restore(self, uid: str, item: DeletedItem, *, outside: bool = False) -> Restored:
        self.calls.append((uid, item.snapshot))
        self.outside.append(outside)
        if self.pause:
            await asyncio.sleep(0.01)
        if self.fail is not None:
            raise self.fail
        return Restored(new_id=f"new{len(self.calls)}", note="")


class FlakySettleStore(DeletedStore):
    """settle fails the first `fail` times it is asked to mark an item restored."""

    def __init__(self, docs: MemoryDocs, *, fail: int, release_fails: bool = False) -> None:
        super().__init__(docs, prefix="t_")
        self.fail, self.release_fails, self.settles = fail, release_fails, 0

    async def settle(self, uid: str, item_id: str, *, restored_id: str | None, now: Any) -> None:
        self.settles += 1
        if restored_id is None and self.release_fails:
            raise RuntimeError("store down while releasing")
        if restored_id is not None and self.fail > 0:
            self.fail -= 1
            raise RuntimeError("store down")
        await super().settle(uid, item_id, restored_id=restored_id, now=now)


class BrokenDocs(MemoryDocs):
    async def write(self, ops: Any) -> None:
        raise RuntimeError("firestore down")


def _bin(docs: MemoryDocs | None = None) -> tuple[UndoBin, Clock, FakeRestorer]:
    clock = Clock()
    restorer = FakeRestorer()
    b = UndoBin(DeletedStore(docs or MemoryDocs(), prefix="t_"), clock=clock)
    b.register("event", restorer)
    return b, clock, restorer


async def test_keep_stores_a_snapshot_per_owner_for_thirty_days() -> None:
    b, _, _ = _bin()
    item = await b.keep(UID, "event", "Dentist", {"summary": "Dentist"})
    assert item.id.startswith("del_") and item.user_id == UID and item.kind == "event"
    assert item.deleted_at == NOW and item.expires_at == NOW + timedelta(days=RETENTION_DAYS)
    assert RETENTION_DAYS == 30
    listed = await b.recent(UID)
    assert [i.id for i in listed] == [item.id] and listed[0].snapshot == {"summary": "Dentist"}
    assert await b.recent("u_other") == []  # scoped per owner


async def test_owner_authored_is_kept_as_captured_and_read_back() -> None:
    """Plan D8: the flag the deleting tool gave survives storage; a listing is trusted only when
    every item in it is the owner's own words."""
    b, _, _ = _bin()
    mine = await b.keep(UID, "event", "Dentist", {}, owner_authored=True)
    theirs = await b.keep(UID, "task", "From a mail", {})
    got = {i.id: i.owner_authored for i in await b.recent(UID)}
    assert got == {mine.id: True, theirs.id: False}
    assert all_owner_authored([i for i in await b.recent(UID) if i.id == mine.id])
    assert not all_owner_authored(await b.recent(UID))


async def test_titles_are_one_line_and_capped() -> None:
    b, _, _ = _bin()
    item = await b.keep(UID, "task", "Pay‮\nbill " + "x" * 400, {})
    assert "\n" not in item.title and "‮" not in item.title and len(item.title) <= 200


async def test_keep_fails_closed_when_the_store_is_down() -> None:
    b, _, _ = _bin(BrokenDocs())
    with pytest.raises(SnapshotFailed, match="nothing was deleted"):
        await b.keep(UID, "event", "Dentist", {"summary": "Dentist"})


async def test_keep_refuses_a_snapshot_too_large_to_store() -> None:
    b, _, _ = _bin()
    with pytest.raises(SnapshotFailed, match="nothing was deleted"):
        await b.keep(UID, "event", "Big", {"description": "x" * 600_000})


async def test_keep_refuses_an_unsafe_owner_id() -> None:
    b, _, _ = _bin()
    with pytest.raises(SnapshotFailed):
        await b.keep("u/../other", "event", "x", {})


async def test_recent_is_newest_first() -> None:
    b, clock, _ = _bin()
    first = await b.keep(UID, "event", "A", {})
    clock.now = NOW + timedelta(minutes=1)
    second = await b.keep(UID, "task", "B", {})
    assert [i.id for i in await b.recent(UID)] == [second.id, first.id]


async def test_restore_recreates_once_and_a_second_restore_says_already_restored() -> None:
    b, _, restorer = _bin()
    item = await b.keep(UID, "event", "Dentist", {"summary": "Dentist"})
    out = await b.restore(UID, item.id)
    assert out.status is RestoreStatus.RESTORED and out.new_id == "new1"
    assert out.title == "Dentist" and out.kind == "event"
    again = await b.restore(UID, item.id)
    assert again.status is RestoreStatus.ALREADY_RESTORED and again.new_id == "new1"
    assert len(restorer.calls) == 1
    stored = await b.store.get(UID, item.id)
    assert stored is not None and stored.restored is True  # marked restored …
    assert await b.recent(UID) == []  # … and no longer listed as something to restore


async def test_keep_records_the_conversation_and_trace_it_came_from() -> None:
    b, _, _ = _bin()
    item = await b.keep(UID, "event", "Dentist", {}, session_id="sess_1", trace_id="tr_abc")
    [kept] = await b.recent(UID)
    assert (
        (kept.session_id, kept.trace_id)
        == ("sess_1", "tr_abc")
        == (
            item.session_id,
            item.trace_id,
        )
    )


async def test_two_restores_at_once_make_one_copy() -> None:
    b, _, restorer = _bin()
    restorer.pause = True
    item = await b.keep(UID, "event", "Dentist", {})
    one, two = await asyncio.gather(b.restore(UID, item.id), b.restore(UID, item.id))
    statuses = sorted([one.status.value, two.status.value])
    assert statuses in (["busy", "restored"], ["already_restored", "restored"])
    assert len(restorer.calls) == 1


async def test_a_restore_racing_the_sweep_makes_one_copy_and_never_raises() -> None:
    """The 30 days run out while a restore is under way: the sweep removes the item, the restore
    still finishes (one copy, reported), and marking a swept item restored is a no-op."""
    b, clock, restorer = _bin()
    restorer.pause = True
    item = await b.keep(UID, "event", "Dentist", {})
    clock.now = item.expires_at - timedelta(microseconds=1)

    async def sweep_meanwhile() -> int:
        await asyncio.sleep(0.002)  # the restore has claimed the item and is recreating it
        clock.now = item.expires_at + timedelta(seconds=1)
        return await b.sweep([UID])

    out, gone = await asyncio.gather(b.restore(UID, item.id), sweep_meanwhile())
    assert out.status is RestoreStatus.RESTORED and len(restorer.calls) == 1 and gone == 1
    assert await b.store.get(UID, item.id) is None
    again = await b.restore(UID, item.id)  # after the sweep: plain words, nothing made
    assert again.status is RestoreStatus.UNKNOWN and len(restorer.calls) == 1


async def test_a_failed_settle_after_a_restore_is_retried_once() -> None:
    store = FlakySettleStore(MemoryDocs(), fail=1)
    b = UndoBin(store, clock=Clock())
    restorer = FakeRestorer()
    b.register("event", restorer)
    item = await b.keep(UID, "event", "Dentist", {})
    out = await b.restore(UID, item.id)
    assert out.status is RestoreStatus.RESTORED and out.new_id == "new1"
    stored = await store.get(UID, item.id)
    assert stored is not None and stored.restored and stored.restored_id == "new1"


async def test_settle_failing_twice_still_reports_the_restore_and_logs_only_the_class(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The event IS back: the owner is told so (with its new id), and the log carries the error
    class only. The item stays claimed, so a click within 5 minutes says "busy"."""
    store = FlakySettleStore(MemoryDocs(), fail=2)
    b = UndoBin(store, clock=Clock())
    restorer = FakeRestorer()
    b.register("event", restorer)
    item = await b.keep(UID, "event", "Dentist", {})
    with caplog.at_level(logging.ERROR):
        out = await b.restore(UID, item.id)
    assert out.status is RestoreStatus.RESTORED and out.new_id == "new1"
    logged = [r for r in caplog.records if r.name == "jarvis.undo.service"]
    assert [getattr(r, "error", None) for r in logged] == ["RuntimeError", "RuntimeError"]
    assert all("store down" not in str(r.__dict__) for r in logged)
    assert (await b.restore(UID, item.id)).status is RestoreStatus.BUSY
    assert len(restorer.calls) == 1


async def test_a_failing_release_never_hides_the_restorers_own_words() -> None:
    store = FlakySettleStore(MemoryDocs(), fail=0, release_fails=True)
    b = UndoBin(store, clock=Clock())
    b.register("event", FakeRestorer(fail=ValueError("Google said no, in plain words")))
    item = await b.keep(UID, "event", "Dentist", {})
    with pytest.raises(ValueError, match="plain words"):
        await b.restore(UID, item.id)


async def test_an_item_that_is_still_there_is_not_copied_and_says_so() -> None:
    b, _, restorer = _bin()
    restorer.fail = StillThere("That event is still on your calendar, so nothing was restored.")
    item = await b.keep(UID, "event", "Dentist", {})
    out = await b.restore(UID, item.id)
    assert out.status is RestoreStatus.STILL_THERE and "still on your calendar" in out.message
    stored = await b.store.get(UID, item.id)
    assert stored is not None and not stored.restored and stored.restoring_since is None


async def test_remove_now_purges_only_my_item() -> None:
    b, _, _ = _bin()
    item = await b.keep(UID, "event", "Dentist", {})
    assert await b.purge("u_other", item.id) is False
    assert await b.purge(UID, "del_00000000000000000000") is False
    assert await b.purge(UID, "../x") is False
    assert await b.purge(UID, item.id) is True
    assert await b.store.get(UID, item.id) is None
    assert (await b.restore(UID, item.id)).status is RestoreStatus.UNKNOWN


async def test_unknown_and_expired_ids_get_plain_messages() -> None:
    b, clock, restorer = _bin()
    unknown = await b.restore(UID, "del_00000000000000000000")
    assert unknown.status is RestoreStatus.UNKNOWN and "Recently deleted" in unknown.message
    bad = await b.restore(UID, "../../x")
    assert bad.status is RestoreStatus.UNKNOWN
    item = await b.keep(UID, "event", "Dentist", {})
    clock.now = NOW + timedelta(days=RETENTION_DAYS, seconds=1)
    old = await b.restore(UID, item.id)
    assert old.status is RestoreStatus.EXPIRED and "30 days" in old.message
    assert restorer.calls == []


async def test_another_owner_cannot_restore_my_item() -> None:
    b, _, restorer = _bin()
    item = await b.keep(UID, "event", "Dentist", {})
    out = await b.restore("u_other", item.id)
    assert out.status is RestoreStatus.UNKNOWN and restorer.calls == []


async def test_a_failed_restore_releases_the_claim_so_it_can_be_tried_again() -> None:
    b, _, restorer = _bin()
    item = await b.keep(UID, "event", "Dentist", {})
    restorer.fail = RuntimeError("Google could not be reached")
    with pytest.raises(RuntimeError):
        await b.restore(UID, item.id)
    restorer.fail = None
    out = await b.restore(UID, item.id)
    assert out.status is RestoreStatus.RESTORED


async def test_a_restore_under_way_is_not_started_twice() -> None:
    b, clock, restorer = _bin()
    item = await b.keep(UID, "event", "Dentist", {})
    claimed, _ = await b.store.claim(UID, item.id, NOW)  # someone else is restoring it
    assert claimed is ClaimResult.CLAIMED
    busy = await b.restore(UID, item.id)
    assert busy.status is RestoreStatus.BUSY and restorer.calls == []
    clock.now = NOW + timedelta(minutes=10)  # a claim left by a crash goes stale
    assert (await b.restore(UID, item.id)).status is RestoreStatus.RESTORED


async def test_no_restorer_for_a_kind_is_a_plain_message() -> None:
    b, _, _ = _bin()
    item = await b.keep(UID, "task", "Pay bill", {})
    out = await b.restore(UID, item.id)
    assert out.status is RestoreStatus.UNAVAILABLE and "Google" in out.message


async def test_discard_removes_a_snapshot_whose_delete_did_not_happen() -> None:
    b, _, _ = _bin()
    item = await b.keep(UID, "event", "Dentist", {})
    await b.discard(UID, item.id)
    assert await b.recent(UID) == []


async def test_sweep_deletes_only_expired_items_and_never_raises() -> None:
    docs = MemoryDocs()
    b, clock, _ = _bin(docs)
    old = await b.keep(UID, "event", "Old", {})
    clock.now = NOW + timedelta(days=20)
    young = await b.keep(UID, "event", "Young", {})
    clock.now = NOW + timedelta(days=RETENTION_DAYS, hours=1)
    assert await b.sweep([UID, "u_nobody"]) == 1
    assert [i.id for i in await b.recent(UID)] == [young.id]
    assert old.id not in {i.id for i in await b.recent(UID)}
    broken, _, _ = _bin(BrokenDocs())
    assert await broken.sweep([UID]) == 0


def test_undo_ref_is_read_only_from_a_delete_result() -> None:
    uid = "del_0123456789abcdef0123"
    ok = UndoRef.from_result({"deleted": True, "undo_id": uid, "kind": "task"})
    assert ok == UndoRef(undo_id=uid, kind="task")
    assert UndoRef.from_result({"undo_id": "evil<script>"}) is None
    assert UndoRef.from_result({"deleted": True}) is None
    assert UndoRef.from_result("not a dict") is None


class MadeThenCrash(FakeRestorer):
    """Makes the root copy, tells the bin so, then dies before the bin hears it finished."""

    def __init__(self, *, error: BaseException) -> None:
        super().__init__()
        self.error = error

    async def restore(self, uid: str, item: DeletedItem, *, outside: bool = False) -> Restored:
        self.calls.append((uid, item.snapshot))
        await record_made("new1")
        raise self.error


@pytest.mark.parametrize("error", [asyncio.CancelledError(), RuntimeError("store down")])
async def test_a_restore_that_made_the_copy_then_died_is_never_made_twice(
    error: BaseException,
) -> None:
    """Review LOW: the claim carries the new id as soon as the root exists, so a click after the
    stale-claim window (or after a release) says "already restored" instead of a duplicate."""
    clock = Clock()
    restorer = MadeThenCrash(error=error)
    b = UndoBin(DeletedStore(MemoryDocs(), prefix="t_"), clock=clock)
    b.register("task", restorer)
    item = await b.keep(UID, "task", "Call plumber", {})
    with pytest.raises(type(error)):
        await b.restore(UID, item.id)
    clock.now = NOW + timedelta(minutes=10)  # past the stale-claim window
    again = await b.restore(UID, item.id)
    assert again.status is RestoreStatus.ALREADY_RESTORED and again.new_id == "new1"
    assert len(restorer.calls) == 1
    kept = await b.store.get(UID, item.id)
    assert kept is not None and kept.restored is True and kept.restoring_since is None


async def test_a_claim_with_a_new_id_still_in_its_window_is_busy_not_restored() -> None:
    clock = Clock()
    restorer = MadeThenCrash(error=asyncio.CancelledError())
    b = UndoBin(DeletedStore(MemoryDocs(), prefix="t_"), clock=clock)
    b.register("task", restorer)
    item = await b.keep(UID, "task", "Call plumber", {})
    with pytest.raises(asyncio.CancelledError):
        await b.restore(UID, item.id)
    assert (await b.restore(UID, item.id)).status is RestoreStatus.BUSY


async def test_record_made_outside_a_restore_is_a_no_op() -> None:
    await record_made("anything")
