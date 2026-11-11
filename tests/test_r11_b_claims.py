# tests/test_r11_b_claims.py -- R11 Part B, code review M3: Part B's claims (`house_told`) have a
# lease. A claim is taken before a send and marked told after it; a claim older than the lease
# (15 minutes) whose send never finished (a run cut by the shared clock budget, a process that
# died) is taken again; a send that raises or is cancelled releases its claim at once. A claim
# kept from before this fix (no `sent` field) still counts as told. Hashes only.
from __future__ import annotations

import asyncio
from datetime import timedelta

import pytest
from r11_fakes import NOON_IST, UID
from r11_fakes_b import PLACE, house_ctx, sachet_fetcher

from jarvis.helpers.house import chores, sachet
from jarvis.helpers.house import store as store_mod
from jarvis.helpers.house.models import Place
from jarvis.helpers.house.store import LEASE, HouseStore, OutsideStore, claim_key


def _store() -> tuple[HouseStore, object]:
    hc, _, docs, _ = house_ctx()
    return HouseStore(docs, prefix=hc.prefix), docs


async def test_a_claim_is_new_then_held_within_its_lease_then_new_again() -> None:
    store, _ = _store()
    assert await store.take(UID, "chore", "x", NOON_IST) == "new"
    assert await store.take(UID, "chore", "x", NOON_IST + timedelta(minutes=14)) == "held"
    assert await store.take(UID, "chore", "x", NOON_IST + LEASE) == "new"  # a send never finished
    await store.done(UID, "chore", "x")
    assert await store.take(UID, "chore", "x", NOON_IST + timedelta(days=2)) == "told"
    assert LEASE == timedelta(minutes=15)


async def test_a_claim_from_before_the_lease_counts_as_told() -> None:
    store, docs = _store()
    path = f"jarvis_house_told/{UID}_{claim_key(UID, 'cap', 'old')}"
    docs._data[path] = {"uid": UID, "tag": "cap", "at": NOON_IST.isoformat()}  # type: ignore[attr-defined]  # noqa: SLF001
    assert await store.take(UID, "cap", "old", NOON_IST + timedelta(hours=1)) == "told"


async def test_once_marks_told_releases_on_retry_and_on_any_error() -> None:
    store, docs = _store()

    async def ok() -> bool:
        return True

    async def again() -> bool:
        return False

    async def boom() -> bool:
        raise RuntimeError("the send blew up")

    async def cut() -> bool:
        raise asyncio.CancelledError

    assert await store.once(UID, "wx", "a", NOON_IST, ok) == "done"
    assert await store.once(UID, "wx", "a", NOON_IST, ok) == "told"
    assert await store.once(UID, "wx", "b", NOON_IST, again) == "again"
    assert await store.take(UID, "wx", "b", NOON_IST) == "new"
    with pytest.raises(RuntimeError):
        await store.once(UID, "wx", "c", NOON_IST, boom)
    with pytest.raises(asyncio.CancelledError):
        await store.once(UID, "wx", "d", NOON_IST, cut)
    assert await store.take(UID, "wx", "c", NOON_IST) == "new"
    assert await store.take(UID, "wx", "d", NOON_IST) == "new"
    told = [d for p, d in docs._data.items() if "house_told/" in p]  # type: ignore[attr-defined]  # noqa: SLF001
    assert all(set(d) == {"uid", "tag", "at", "sent"} for d in told)


async def test_a_chore_left_claimed_by_a_cut_run_is_sent_after_the_lease() -> None:
    hc, notifier, docs, clock = house_ctx()
    store = HouseStore(docs, prefix=hc.prefix)
    c = chores.new_chore(cid="0000000a", label="Dishes", freq="daily", at="11:00",
                         today=NOON_IST.date())  # fmt: skip
    await store.change_chores(UID, lambda cs: (c,))
    await store.take(UID, "chore", f"{c.id}|{NOON_IST.date().isoformat()}", NOON_IST)  # cut here
    job = chores.ChoresJob(hc, store)
    await job.run(())
    assert notifier.calls == []  # within the lease: another run may still be sending it
    clock.at += timedelta(minutes=16)
    await job.run(())
    assert len(notifier.calls) == 1
    clock.at += timedelta(minutes=5)
    await job.run(())
    assert len(notifier.calls) == 1  # told once


async def test_a_sachet_item_whose_claim_is_held_stays_queued() -> None:
    hc, notifier, docs, clock = house_ctx()
    outside = OutsideStore(docs, hc.keyring, prefix=hc.prefix)
    await outside.change(UID, lambda o: o.model_copy(update={"place": Place(**PLACE)}))
    store = HouseStore(docs, prefix=hc.prefix)
    await store.take(UID, "cap", "IN-1794300000000102_1", NOON_IST)  # a cut run's claim
    job = sachet.DisasterJob(hc, outside, store, sachet_fetcher())
    await job.run(())
    assert "1794300000000102" in (await outside.read(UID)).sachet.queue
    clock.at += LEASE + timedelta(minutes=1)
    await job.run(())
    assert any("Landslide" in t for _, _, t, _ in notifier.calls)
    assert (await outside.read(UID)).sachet.queue == ()
    assert store_mod.CLAIM_KEEP == timedelta(days=30)
