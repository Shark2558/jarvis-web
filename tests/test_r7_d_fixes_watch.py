# tests/test_r7_d_fixes_watch.py -- R7 Part D's review follow-ups for the watch: a sync never drops
# a night he typed (even racing it), the stale-watch alert fires for a phone whose syncs are all
# refused or whose days are old or empty, told only once and only for a real delivery, a notifier
# that is missing is said, and a phone cannot send a night "typed by you".
from __future__ import annotations

import asyncio
import json
import logging
from datetime import date, timedelta
from typing import Any

import pytest
from r7_fakes_d import UID
from test_r7_d_fixes_sos import Held
from test_r7_d_part import HEALTH, Rig
from test_r7_d_watch_store import DAY12, _body, _world

from jarvis.storage.docs import MemoryDocs
from jarvis.watch.jobs import DATA_STALE_DAYS, STALE_AFTER, WatchStale
from jarvis.watch.models import IntakeRefused, Session, parse_health

DAY = date(2026, 11, 12)


class Yielding(MemoryDocs):
    """A Docs twin whose reads give the loop a turn, so two writers really interleave."""

    async def get(self, path: str) -> Any:
        await asyncio.sleep(0)
        return await super().get(path)

    async def transaction(self, fn: Any) -> Any:
        async def slow(tx: Any) -> Any:
            await asyncio.sleep(0)
            return await fn(tx)

        return await super().transaction(slow)


@pytest.mark.parametrize("typed_first", [True, False])
async def test_a_sync_racing_a_typed_night_never_drops_it(typed_first: bool) -> None:
    svc, store, _, clock = _world(docs=Yielding())
    await svc.intake(UID, _body([DAY12]))
    typed = Session(
        start="2026-11-11T23:00:00+05:30", end="2026-11-12T06:00:00+05:30", writer="typed"
    )
    jobs = [store.set_typed(UID, DAY, typed), svc.intake(UID, _body([DAY12]))]
    await asyncio.gather(*(jobs if typed_first else jobs[::-1]))
    day = await store.day(UID, DAY)
    assert day is not None and day.typed == typed and day.steps is not None


async def test_two_syncs_at_once_both_land() -> None:
    svc, store, _, _ = _world(docs=Yielding())
    other = {**DAY12, "date": "2026-11-11"}
    await asyncio.gather(svc.intake(UID, _body([DAY12])), svc.intake(UID, _body([other])))
    assert await store.day(UID, DAY) is not None and await store.day(UID, date(2026, 11, 11))


async def test_a_phone_cannot_send_a_night_as_typed_by_you() -> None:
    bad = {**DAY12, "sleep": [{**DAY12["sleep"][0], "writer": "typed"}]}
    with pytest.raises(IntakeRefused):
        parse_health(_body([bad]), DAY)


async def test_a_corrupt_stored_day_is_replaced_by_the_next_sync_rather_than_blocking_it() -> None:
    svc, store, docs, _ = _world()
    await svc.intake(UID, _body([DAY12]))
    path = store._day_path(UID, DAY)  # noqa: SLF001
    docs._data[path] = {**docs._data[path], "blob": "garbage"}
    assert await svc.intake(UID, _body([DAY12])) == 1  # the phone's data replaces what cannot open
    assert (await store.day(UID, DAY)) is not None


# ---- the stale-watch alert ----
def _job(rig: Rig) -> WatchStale:
    (job,) = rig.part.clock_jobs
    return job  # type: ignore[no-any-return]


async def test_a_phone_whose_syncs_are_all_refused_is_told_once() -> None:
    rig = Rig()
    job = _job(rig)
    assert (await rig.door.call("health", b'{"v":1,"days":[]}')).status == 422
    assert (await job.run([UID]))["told"] == 0  # not yet 26 hours
    rig.clock.move(hours=27)
    assert (await job.run([UID]))["told"] == 1
    assert (await job.run([UID]))["told"] == 0
    kind, words = rig.notes.sent[0][1:]
    assert kind == "watch_stale" and "refus" in words.lower() and "Sir" in words
    await rig.door.call("health", json.dumps(HEALTH).encode())  # a good sync ends it
    assert (await rig.part.services["watch"].state(UID)).first_refused is None


async def test_a_phone_that_never_tried_is_never_told() -> None:
    rig = Rig()
    rig.clock.move(days=30)
    assert (await _job(rig).run([UID]))["told"] == 0


async def test_old_or_empty_days_do_not_hide_a_silent_watch() -> None:
    rig = Rig()
    job = _job(rig)
    await rig.door.call("health", json.dumps(HEALTH).encode())  # data for 12 Nov
    empty = {"v": 1, "days": [{"date": "2026-11-12", "steps": None, "heart": None, "sleep": []}]}
    for _ in range(DATA_STALE_DAYS + 1):  # the phone syncs every 6 hours, with nothing new
        for _ in range(4):
            rig.clock.move(hours=6)
            await rig.door.call("health", json.dumps(empty).encode())
    state = await rig.part.services["watch"].state(UID)
    assert rig.clock() - state.last_sync < STALE_AFTER  # the phone itself is syncing fine
    assert (await job.run([UID]))["told"] == 1
    assert "no watch data" in rig.notes.sent[-1][2].lower()
    assert (await job.run([UID]))["told"] == 0


async def test_a_fresh_watch_and_a_fresh_phone_are_quiet() -> None:
    rig = Rig()
    await rig.door.call("health", json.dumps(HEALTH).encode())
    rig.clock.move(hours=20)
    assert (await _job(rig).run([UID]))["told"] == 0


async def test_a_held_notice_is_not_told_and_is_not_repeated_every_five_minutes() -> None:
    rig = Rig()
    held = Held("hold")
    rig = _with_notifier(rig, held)
    job = _job(rig)
    await rig.door.call("health", json.dumps(HEALTH).encode())
    rig.clock.move(hours=27)
    assert (await job.run([UID]))["told"] == 0
    rig.clock.move(minutes=5)
    await job.run([UID])
    assert held.calls == 1  # not again for an hour
    rig.clock.move(hours=1)
    await job.run([UID])
    assert held.calls == 2  # then tried again, until it is really delivered


def _with_notifier(rig: Rig, notifier: Any) -> Rig:
    from jarvis.mobile.ports import MobileContext
    from jarvis.watch import part as part_mod

    ctx = MobileContext(
        s=rig.ctx.s, docs=rig.docs, audit=rig.audit, state=rig.ctx.state, notifier=lambda: notifier
    )
    rig.part = part_mod.build(ctx)
    return rig


async def test_a_mark_told_that_fails_never_tells_again_every_five_minutes() -> None:
    rig = Rig()
    job = _job(rig)
    await rig.door.call("health", json.dumps(HEALTH).encode())
    rig.clock.move(hours=27)
    watch = rig.part.services["watch"]

    async def boom(uid: str, at: Any) -> None:
        raise RuntimeError("store down")

    watch.store.mark_told = boom
    first = await job.run([UID])
    assert first["told"] == 1 and first["failed"] == 1  # told; the failure to note it is counted
    for _ in range(3):
        rig.clock.move(minutes=5)
        again = await job.run([UID])
        assert again["told"] == 0
    assert len(rig.notes.sent) == 1


async def test_a_sync_between_the_notice_and_mark_told_does_not_hide_the_next_silence() -> None:
    rig = Rig()
    job = _job(rig)
    await rig.door.call("health", json.dumps(HEALTH).encode())
    rig.clock.move(hours=27)
    watch = rig.part.services["watch"]
    real = watch.store.mark_told

    async def late(uid: str, at: Any) -> None:
        await rig.door.call("health", json.dumps(HEALTH).encode())  # lands before the mark
        await real(uid, at)

    watch.store.mark_told = late
    await job.run([UID])
    rig.clock.move(hours=27)
    assert (await job.run([UID]))["told"] == 1  # the new silence is told too


async def test_a_missing_notifier_is_logged_and_counted(caplog: pytest.LogCaptureFixture) -> None:
    rig = _with_notifier(Rig(), None)
    await rig.door.call("health", json.dumps(HEALTH).encode())
    rig.clock.move(hours=27)
    with caplog.at_level(logging.WARNING):
        got = await _job(rig).run([UID])
    assert got["told"] == 0 and got["no_notifier"] == 1 and "no notifier" in caplog.text


async def test_a_naive_clock_does_not_hide_every_owner() -> None:
    rig = Rig()
    job = _job(rig)
    await rig.door.call("health", json.dumps(HEALTH).encode())
    rig.clock.at = (rig.clock.at + timedelta(hours=27)).replace(tzinfo=None)
    got = await job.run([UID])
    assert got["failed"] == 0 and got["told"] == 1


async def test_the_off_path_returns_the_same_keys() -> None:
    rig = Rig(watch_enabled=False)
    assert await _job(rig).run([UID]) == {"told": 0, "no_notifier": 0, "failed": 0}


# ---- small things ----
async def test_the_week_and_the_night_read_their_days_in_one_pass() -> None:
    svc, store, docs, _ = _world()
    await svc.intake(UID, _body([DAY12]))
    docs.reads = 0
    await svc.week(UID, DAY)
    assert docs.reads <= 8 + 1  # eight days once, never eleven sequential reads
