# tests/test_r14_b_held.py -- R14 Part B, plan D13 item 7: a held overnight `home_offline_idle` is
# dropped when the laptop is back before the morning summary; an armed `home_offline` is never
# dropped. `NotifyStore.held_drop` and the laptop-back path (`home/heartbeat.py`).
from __future__ import annotations

from typing import Any

import pytest

from jarvis.home.heartbeat import DROP_WHEN_BACK, LAPTOP_BACK, HeartbeatHandler
from jarvis.home.ports import Heartbeat
from jarvis.home.store import Seen
from jarvis.keyring import Keyring
from jarvis.notify.held import summary
from jarvis.notify.ports import Delivery, Signal
from jarvis.notify.store import NotifyStore, NotifyUnavailable
from jarvis.storage.docs import MemoryDocs

UID = "owner-1"
ROOT = bytes(range(1, 33))
HB = Heartbeat(id="hb-2", type="heartbeat", at=1.0, bridge_version="0.1.0", state_rev=0)


def _store() -> NotifyStore:
    return NotifyStore(MemoryDocs(), Keyring(ROOT))


async def _hold(store: NotifyStore, *kinds: str) -> None:
    for i, kind in enumerate(kinds):
        await store.held_add(UID, {"kind": kind, "at": f"2026-11-16T0{i}:00:00+05:30"})


async def test_dropping_a_held_kind_keeps_every_other_item() -> None:
    store = _store()
    await _hold(store, "home_offline_idle", "vault_expiry", "home_offline_idle", "home_offline")
    assert await store.held_drop(UID, ("home_offline_idle",)) == 2
    assert [i["kind"] for i in await store.held_list(UID)] == ["vault_expiry", "home_offline"]
    assert await store.held_drop(UID, ("home_offline_idle",)) == 0


async def test_dropping_the_last_items_removes_the_document() -> None:
    store = _store()
    await _hold(store, "home_offline_idle")
    assert await store.held_drop(UID, DROP_WHEN_BACK) == 1
    assert await store.held_list(UID) == [] and await store.held_owners() == []
    assert await _store().held_drop(UID, DROP_WHEN_BACK) == 0  # nothing held: nothing written


async def test_dropping_needs_a_good_owner_id_and_never_shows_the_cause() -> None:
    with pytest.raises(ValueError):
        await _store().held_drop("../x", DROP_WHEN_BACK)

    class Down(MemoryDocs):
        async def transaction(self, fn: Any) -> Any:
            raise RuntimeError("secret backend words")

    with pytest.raises(NotifyUnavailable) as got:
        await NotifyStore(Down(), Keyring(ROOT)).held_drop(UID, DROP_WHEN_BACK)
    assert "secret" not in str(got.value)


def test_only_the_idle_alert_is_dropped_when_back() -> None:
    assert DROP_WHEN_BACK == ("home_offline_idle",)
    assert "home_offline" not in DROP_WHEN_BACK


class _HomeStore:
    def __init__(self, seen: Seen | None) -> None:
        self._seen = seen

    async def seen(self, uid: str, **kw: Any) -> Seen | None:
        return self._seen


class _Notifier:
    """A NotifyService stand-in: its `store` is the real NotifyStore; it records the alerts."""

    def __init__(self, store: Any) -> None:
        self.store = store
        self.sent: list[tuple[str, str]] = []

    async def notify(self, uid: str, signal: Signal, message: str, **kw: Any) -> Delivery:
        self.sent.append((signal.kind, message))
        return Delivery(action="drop", reason="feed_only")


async def test_the_laptop_back_drops_the_held_idle_alert_before_the_morning_summary() -> None:
    store = _store()
    await _hold(store, "home_offline_idle", "vault_expiry")
    notes = _Notifier(store)
    back = HeartbeatHandler(_HomeStore(Seen(previous="offline", outage_alerted=True)), notes)  # type: ignore[arg-type]
    await back.handle(UID, HB)
    held = await store.held_list(UID)
    assert [i["kind"] for i in held] == ["vault_expiry"]
    assert summary(held).startswith("While you were resting, 1 alert were held (1 document")
    assert notes.sent == [("home_online", LAPTOP_BACK)]


async def test_an_armed_offline_alert_held_or_not_is_never_dropped() -> None:
    store = _store()
    await _hold(store, "home_offline", "home_offline_idle")
    back = HeartbeatHandler(
        _HomeStore(Seen(previous="offline", outage_alerted=True)), _Notifier(store)
    )  # type: ignore[arg-type]
    await back.handle(UID, HB)
    assert [i["kind"] for i in await store.held_list(UID)] == ["home_offline"]


async def test_no_outage_told_means_nothing_is_dropped() -> None:
    store = _store()
    await _hold(store, "home_offline_idle")
    for seen in (Seen(previous="online", outage_alerted=False), None):
        await HeartbeatHandler(_HomeStore(seen), _Notifier(store)).handle(UID, HB)  # type: ignore[arg-type]
    assert len(await store.held_list(UID)) == 1


async def test_a_store_that_fails_never_stops_the_back_online_alert() -> None:
    class Broken:
        async def held_drop(self, uid: str, kinds: Any) -> int:
            raise NotifyUnavailable("plain words")

    notes = _Notifier(Broken())
    handler = HeartbeatHandler(_HomeStore(Seen(previous="offline", outage_alerted=True)), notes)  # type: ignore[arg-type]
    await handler.handle(UID, HB)
    assert notes.sent == [("home_online", LAPTOP_BACK)]


async def test_a_plain_notifier_without_a_store_still_says_back() -> None:
    notes = _Notifier(None)
    handler = HeartbeatHandler(_HomeStore(Seen(previous="offline", outage_alerted=True)), notes)  # type: ignore[arg-type]
    await handler.handle(UID, HB)
    assert notes.sent == [("home_online", LAPTOP_BACK)]


async def test_with_the_real_notifier_the_morning_summary_never_reports_a_finished_outage() -> None:
    from notify_fakes import MIDNIGHT, NOON, build
    from telegram_fakes import UID as TG_UID

    w = await build(MIDNIGHT)
    idle = Signal(source="home", kind="home_offline_idle")
    got = await w.service.notify(TG_UID, idle, "Your home laptop stopped answering at 00:20.")
    assert got.action == "hold" and len(await w.store.held_list(TG_UID)) == 1
    back = HeartbeatHandler(_HomeStore(Seen(previous="offline", outage_alerted=True)), w.service)  # type: ignore[arg-type]
    await back.handle(TG_UID, HB)
    assert await w.store.held_list(TG_UID) == []
    w.clock.now = NOON
    assert await w.service.flush_held(TG_UID) is False  # nothing left to summarise
