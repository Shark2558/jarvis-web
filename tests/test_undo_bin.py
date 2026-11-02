# tests/test_undo_bin.py — slice 11 D1: the "Recently deleted" bin (jarvis.undo) on the Docs port.
# Written before the implementation: snapshots kept per owner for 30 days, fail-closed keep,
# idempotent restore (claimed in a transaction), plain words for unknown / expired ids, the sweep.
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from jarvis.storage.docs import MemoryDocs
from jarvis.undo.models import RETENTION_DAYS, RestoreStatus, UndoRef
from jarvis.undo.service import Restored, SnapshotFailed, UndoBin
from jarvis.undo.store import DeletedStore

NOW = datetime(2027, 1, 15, 3, 0, tzinfo=UTC)
UID = "u_owner"


class Clock:
    def __init__(self) -> None:
        self.now = NOW

    def __call__(self) -> datetime:
        return self.now


class FakeRestorer:
    def __init__(self, *, fail: Exception | None = None) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.fail = fail

    async def restore(self, uid: str, snapshot: dict[str, Any]) -> Restored:
        self.calls.append((uid, snapshot))
        if self.fail is not None:
            raise self.fail
        return Restored(new_id=f"new{len(self.calls)}", note="")


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
    assert (await b.recent(UID))[0].restored is True


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
    assert await b.store.claim(UID, item.id, NOW) is not None  # someone else is restoring it
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
