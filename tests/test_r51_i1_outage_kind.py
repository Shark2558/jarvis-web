# tests/test_r51_i1_outage_kind.py -- R5.1 I1 (Part C note, D3): the KIND of alert that told an
# outage is stored with it (`HomeStore.mark_offline(kind=)` -> `HomeStatus.outage_kind`), so a
# restart or another Cloud Run instance never loses "told as idle, armed not yet": arming after an
# idle alert still sends the urgent one exactly once, whichever instance runs the watchdog.
from __future__ import annotations

from faces_fakes import ROOT
from r51c_fakes import RANG, SEEN, UID, ArmFake, Clock, Scripted

from jarvis.home.store import HomeStore
from jarvis.home.watchdog import OfflineJob
from jarvis.keyring import Keyring
from jarvis.storage.docs import MemoryDocs

AFTER = 360.0
GONE = SEEN + AFTER + 1


async def linked(docs: MemoryDocs) -> HomeStore:
    store = HomeStore(docs, Keyring(ROOT), clock=lambda: SEEN)
    await store.link(UID, "home1", "https://bridge.example", b"s" * 32)
    await store.seen(UID, parts={}, bridge_version="1")
    return store


def restarted(docs: MemoryDocs) -> HomeStore:
    """A fresh instance over the same documents: nothing in process."""
    return HomeStore(docs, Keyring(ROOT), clock=lambda: GONE)


def watchdog(store: HomeStore, notes: Scripted, arm: ArmFake) -> OfflineJob:
    return OfflineJob(
        store, notes, arm, clock=Clock(GONE), offline_after_s=AFTER, tz="Asia/Kolkata"
    )


# ---- the store ---------------------------------------------------------------------------------
async def test_mark_offline_stores_the_kind_and_a_heartbeat_clears_it() -> None:
    docs = MemoryDocs()
    store = await linked(docs)
    await store.mark_offline(UID, alerted=True, kind="idle")
    status = await restarted(docs).status(UID)
    assert status is not None and status.outage_alerted and status.outage_kind == "idle"

    await store.seen(UID, parts={}, bridge_version="1")  # the laptop is back
    status = await store.status(UID)
    assert status is not None and status.outage_kind is None and not status.outage_alerted


async def test_an_untold_outage_has_no_kind_and_an_old_record_reads_as_none() -> None:
    docs = MemoryDocs()
    store = await linked(docs)
    await store.mark_offline(UID, alerted=False, kind="idle")  # nobody was told: no kind
    status = await store.status(UID)
    assert status is not None and status.outage_kind is None
    await store.mark_offline(UID, alerted=True)  # an R3 caller: no kind given
    status = await store.status(UID)
    assert status is not None and status.outage_alerted and status.outage_kind is None


# ---- the watchdog across instances -------------------------------------------------------------
async def test_arming_after_an_idle_alert_rings_once_on_another_instance() -> None:
    docs = MemoryDocs()
    notes = Scripted(RANG)
    arm = ArmFake(False)
    await watchdog(await linked(docs), notes, arm).run([UID])
    assert notes.kinds() == ["home_offline_idle"]

    arm.armed = True  # the owner arms; a DIFFERENT instance runs the next watchdog
    await watchdog(restarted(docs), notes, arm).run([UID])
    await watchdog(restarted(docs), notes, arm).run([UID])  # and another one after it
    assert notes.kinds() == ["home_offline_idle", "home_offline"]
    status = await restarted(docs).status(UID)
    assert status is not None and status.outage_kind == "armed"


async def test_a_restart_while_still_disarmed_tells_nothing_more() -> None:
    docs = MemoryDocs()
    notes = Scripted(RANG)
    await watchdog(await linked(docs), notes, ArmFake(False)).run([UID])
    await watchdog(restarted(docs), notes, ArmFake(False)).run([UID])
    assert notes.kinds() == ["home_offline_idle"]


async def test_an_armed_alert_already_told_is_not_repeated_after_a_restart() -> None:
    docs = MemoryDocs()
    notes = Scripted(RANG)
    await watchdog(await linked(docs), notes, ArmFake(True)).run([UID])
    await watchdog(restarted(docs), notes, ArmFake(True)).run([UID])
    assert notes.kinds() == ["home_offline"]
    status = await restarted(docs).status(UID)
    assert status is not None and status.outage_kind == "armed"


async def test_an_outage_told_before_r51_reads_as_settled() -> None:
    """A record with `outage_alerted` but no kind was told by R3 (armed alerts only)."""
    docs = MemoryDocs()
    store = await linked(docs)
    await store.mark_offline(UID, alerted=True)
    notes = Scripted(RANG)
    await watchdog(restarted(docs), notes, ArmFake(True)).run([UID])
    assert notes.sent == []
