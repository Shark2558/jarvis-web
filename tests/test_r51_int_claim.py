# tests/test_r51_int_claim.py -- R5.1 integrated fix (int-sec LOW 6): two watchdog runs on two
# instances (a Scheduler retry racing a slow first run) can't both send the "laptop stopped
# answering" alert: the alert slot is taken with a compare-and-set in the store BEFORE the send,
# given back when no channel took the alert, and a claim left by a crashed run expires.
from __future__ import annotations

import asyncio

from faces_fakes import ROOT
from r51c_fakes import RANG, SEEN, UID, UNHEARD, ArmFake, Clock, Scripted

from jarvis.home.store import CLAIM_TTL_S, HomeStore
from jarvis.home.watchdog import OfflineJob
from jarvis.keyring import Keyring
from jarvis.notify.ports import Delivery, Signal
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


class SlowNotes(Scripted):
    """A notifier that lets the other instance run while this one is mid-send."""

    async def notify(self, uid: str, signal: Signal, message: str, **kw: object) -> Delivery:
        await asyncio.sleep(0.01)
        return await super().notify(uid, signal, message, **kw)  # type: ignore[arg-type]


async def test_two_instances_running_at_once_send_one_alert() -> None:
    docs = MemoryDocs()
    notes = SlowNotes(RANG)
    await linked(docs)
    a = watchdog(restarted(docs), notes, ArmFake(False))
    b = watchdog(restarted(docs), notes, ArmFake(False))
    await asyncio.gather(a.run([UID]), b.run([UID]))
    assert notes.kinds() == ["home_offline_idle"]


async def test_two_instances_running_at_once_send_one_armed_alert() -> None:
    docs = MemoryDocs()
    notes = SlowNotes(RANG)
    await linked(docs)
    a = watchdog(restarted(docs), notes, ArmFake(True))
    b = watchdog(restarted(docs), notes, ArmFake(True))
    await asyncio.gather(a.run([UID]), b.run([UID]))
    assert notes.kinds() == ["home_offline"]


async def test_an_alert_no_channel_took_gives_the_slot_back_for_the_retry() -> None:
    docs = MemoryDocs()
    notes = Scripted(UNHEARD, RANG)
    await watchdog(await linked(docs), notes, ArmFake(True)).run([UID])
    status = await restarted(docs).status(UID)
    assert status is not None and not status.outage_alerted
    await watchdog(restarted(docs), notes, ArmFake(True)).run([UID])
    assert notes.kinds() == ["home_offline", "home_offline"]  # tried, then told
    status = await restarted(docs).status(UID)
    assert status is not None and status.outage_alerted and status.outage_kind == "armed"


async def test_the_claim_is_compare_and_set() -> None:
    store = await linked(MemoryDocs())
    assert await store.claim_alert(UID, "idle") is True
    assert await store.claim_alert(UID, "idle") is False  # held by someone else
    assert await store.claim_alert(UID, "armed") is False  # any live claim blocks
    await store.release_claim(UID)
    assert await store.claim_alert(UID, "idle") is True


async def test_a_stale_claim_from_a_crashed_run_expires() -> None:
    now = [SEEN]
    docs = MemoryDocs()
    store = HomeStore(docs, Keyring(ROOT), clock=lambda: now[0])
    await store.link(UID, "home1", "https://bridge.example", b"s" * 32)
    assert await store.claim_alert(UID, "armed") is True
    now[0] += CLAIM_TTL_S - 1
    assert await store.claim_alert(UID, "armed") is False
    now[0] += 2
    assert await store.claim_alert(UID, "armed") is True


async def test_a_claim_for_a_kind_already_told_is_refused() -> None:
    store = await linked(MemoryDocs())
    await store.mark_offline(UID, alerted=True, kind="idle")
    assert await store.claim_alert(UID, "idle") is False
    assert await store.claim_alert(UID, "armed") is True  # arming after an idle alert still rings


async def test_the_claim_clears_when_the_laptop_is_back_and_when_the_outage_is_marked() -> None:
    store = await linked(MemoryDocs())
    assert await store.claim_alert(UID, "idle") is True
    await store.mark_offline(UID, alerted=True, kind="idle")
    assert await store.claim_alert(UID, "armed") is True  # the idle claim was cleared by the mark
    await store.seen(UID, parts={}, bridge_version="1")  # back online
    assert await store.claim_alert(UID, "idle") is True


async def test_a_missing_home_cannot_be_claimed() -> None:
    store = HomeStore(MemoryDocs(), Keyring(ROOT), clock=lambda: SEEN)
    assert await store.claim_alert("nobody", "idle") is False
