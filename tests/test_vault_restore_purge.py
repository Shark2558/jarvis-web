# tests/test_vault_restore_purge.py -- R2 review C1: an old bin entry never shreds a live item
from __future__ import annotations

import datetime as dt

from vault_fakes import NOW, PDF, UID, make

from jarvis.storage.docs import MemoryDocs
from jarvis.undo.models import DeletedItem
from jarvis.undo.service import UndoBin
from jarvis.undo.store import DeletedStore
from jarvis.vault.service import VaultPurger, VaultRestorer


class Clock:
    def __init__(self) -> None:
        self.now = NOW

    def __call__(self) -> dt.datetime:
        return self.now


def real_bin(svc, clock):  # type: ignore[no-untyped-def]
    undo = UndoBin(DeletedStore(MemoryDocs(), prefix="t_"), clock=clock)
    undo.register("vault_item", VaultRestorer(svc), VaultPurger(svc))
    svc._undo = undo
    return undo


async def test_sweep_after_restore_keeps_live_item() -> None:
    clock = Clock()
    svc, _, _ = make(clock=clock)
    undo = real_bin(svc, clock)
    item = (await svc.add_file(UID, PDF)).item
    undo_id = await svc.remove(UID, item.id)
    assert (await undo.restore(UID, undo_id)).status.value == "restored"
    clock.now = NOW + dt.timedelta(days=31)
    await undo.sweep([UID])
    index = await svc.index(UID)
    assert [i.id for i in index.live_items()] == [item.id]
    assert index.live_items()[0].files


async def test_old_bin_entry_cannot_purge_a_redeleted_item() -> None:
    clock = Clock()
    svc, _, _ = make(clock=clock)
    undo = real_bin(svc, clock)
    item = (await svc.add_file(UID, PDF)).item
    first = await svc.remove(UID, item.id)
    await undo.restore(UID, first)
    clock.now = NOW + dt.timedelta(days=1)
    second = await svc.remove(UID, item.id)
    old = await undo.store.get(UID, first)
    assert old is not None
    await VaultPurger(svc).purge(UID, old)  # the stale entry: tombstone time differs
    assert (await svc.index(UID)).item(item.id) is not None
    new = await undo.store.get(UID, second)
    assert new is not None
    await VaultPurger(svc).purge(UID, new)
    assert (await svc.index(UID)).item(item.id) is None


async def test_purge_of_a_live_item_or_legacy_snapshot_does_nothing() -> None:
    svc, _, _ = make()
    item = (await svc.add_file(UID, PDF)).item
    rec = DeletedItem(
        id="del_" + "0" * 20, user_id=UID, kind="vault_item", title="t",
        snapshot={"ref": item.id, "deleted_at": NOW.isoformat()}, deleted_at=NOW, expires_at=NOW,
    )  # fmt: skip
    await VaultPurger(svc).purge(UID, rec)  # live: nothing to purge
    assert (await svc.index(UID)).item(item.id) is not None
    await svc.remove(UID, item.id)
    legacy = rec.model_copy(update={"snapshot": {"ref": item.id}})
    await VaultPurger(svc).purge(UID, legacy)  # no tombstone time to match: no-op
    assert (await svc.index(UID)).item(item.id) is not None
