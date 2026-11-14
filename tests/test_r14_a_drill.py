# tests/test_r14_a_drill.py -- R14 Part A (docs/plans/r14-hardening.md D4 "Drill", review A2, A3):
# the restore drill's state machine on fakes, one morning tick at a time. Due on the drill day from
# 05:00, or after he approves the card (at most 2 a month); never on a backup whose stats are
# empty; refused above the rupee cap at the live rate; a left-over copy is cleaned up first and the
# restore waits for the next tick; restoring is polled; the checks resume; the copy is ALWAYS
# deleted (delete protection off first), whatever the switches say; a copy that can't be deleted
# is told after 2 days, weekly; one drill at a time.
from __future__ import annotations

import datetime as dt
from dataclasses import replace
from typing import Any

import pytest
from r14_fakes_a import (
    GIB,
    PREFIX,
    SNAP,
    UID,
    FakeAdmin,
    FakeWalk,
    RecordingNotifier,
    World,
    ring,
    seed_rest,
    seed_vault,
)

from jarvis.backup import canary
from jarvis.backup.drill import (
    ALREADY,
    CAP_LINE,
    NOT_SET_UP_LINE,
    OFF_LINE,
    REQUESTED,
    Drill,
    DrillDeps,
)
from jarvis.backup.log import DrillLog
from jarvis.backup.ports import DRILL_DB
from jarvis.backup.readonly import read_only
from jarvis.backup.status import BackupStatusService, Teller
from jarvis.config import Settings

DAY1 = dt.datetime(2026, 12, 1, 0, 0, tzinfo=dt.UTC)  # 05:30 in Kolkata
OWNERS = (UID,)


class Clock:
    def __init__(self, at: dt.datetime) -> None:
        self.at = at

    def __call__(self) -> dt.datetime:
        return self.at

    def later(self, **kw: float) -> None:
        self.at += dt.timedelta(**kw)


class Rig:
    def __init__(self, world: World, clock: Clock, s: Settings, **kw: Any) -> None:
        self.world, self.clock, self.sent = world, clock, RecordingNotifier()
        self.admin = FakeAdmin(world)
        self.log = DrillLog(world.live, prefix=PREFIX, clock=clock)
        self.status = BackupStatusService(world.live, self.log, prefix=PREFIX, clock=clock)
        self.walks: list[FakeWalk] = []

        def walk() -> FakeWalk:
            self.walks.append(FakeWalk(world))
            return self.walks[-1]

        async def rate() -> float:
            return 95.24

        self.deps = DrillDeps(
            s=s,
            admin=self.admin,
            walk=walk,
            live=read_only(world.live),
            log=self.log,
            status=self.status,
            teller=Teller(self.status, lambda: self.sent),
            ring=kw.get("keys", ring()),
            rate=rate,
            clock=clock,
            prefix=PREFIX,
            time_left=kw.get("time_left", lambda: None),
        )
        self.drill = Drill(self.deps)

    async def tick(self) -> str:
        return await self.drill.step(OWNERS)

    async def until_idle(self, ticks: int = 10) -> list[str]:
        said = []
        for _ in range(ticks):
            said.append(await self.tick())
            self.clock.later(minutes=30)
            if (await self.log.state()).phase == "idle" and said[-1] in ("done", "refused"):
                break
        return said


@pytest.fixture
def s(settings: Settings) -> Settings:
    return settings.model_copy(update={"user_timezone": "Asia/Kolkata"})


async def _world(**kw: Any) -> World:
    world = World(**kw)
    await seed_vault(world.live, ring())
    await seed_rest(world.live)
    await canary.CanaryStore(world.live, prefix=PREFIX).write(ring(), SNAP - dt.timedelta(hours=2))
    world.snapshot()
    return world


async def _rig(s: Settings, *, at: dt.datetime = DAY1, set_up: bool = True, **kw: Any) -> Rig:
    world = kw.pop("world", None) or await _world()
    rig = Rig(world, Clock(at), s, **kw)
    if set_up:
        await rig.status.refresh(rig.admin)
    rig.admin.calls.clear()
    return rig


async def test_before_the_set_up_nothing_is_asked_of_google(s: Settings) -> None:
    rig = await _rig(s, set_up=False)
    assert await rig.tick() == "not_set_up"
    assert rig.admin.calls == []


async def test_not_due_before_five_in_the_morning_or_before_the_drill_day(s: Settings) -> None:
    rig = await _rig(s, at=dt.datetime(2026, 11, 30, 23, 0, tzinfo=dt.UTC))  # 04:30 on the 1st
    assert await rig.tick() == "idle"
    s2 = s.model_copy(update={"backup_drill_day": 3})
    rig = await _rig(s2)
    assert await rig.tick() == "idle"
    assert "restore" not in rig.admin.names()


async def test_a_whole_drill_passes_on_fakes_and_the_copy_is_deleted(s: Settings) -> None:
    rig = await _rig(s, world=await _world(restore_polls=2))
    start = len(rig.world.live.log)
    said = await rig.until_idle()
    assert said[0] == "started" and "restoring" in said and said[-1] == "done"
    assert rig.world.drill is None
    last = await rig.log.last_result()
    assert last is not None and last.outcome == "passed" and last.manual is False
    assert last.items == 1 and last.files == 1 and last.samples > 0 and last.canary_ok
    assert last.counted == last.expected and last.inr == pytest.approx(1.86, abs=0.01)
    assert rig.sent.kinds() == [("backup_ok", "drill")]
    state = await rig.log.state()
    assert state.phase == "idle" and state.auto_month == "202612" and state.run is None
    assert await rig.tick() == "idle"  # once a month
    written = {op.path.split("/")[0] for op in rig.world.live.log[start:]}
    assert written <= {f"{PREFIX}backup_drill", f"{PREFIX}backup_drills", f"{PREFIX}backup_status"}


async def test_every_google_call_names_only_the_drill_copy(s: Settings) -> None:
    rig = await _rig(s)
    await rig.until_idle()
    targets = {c[1] for c in rig.admin.calls if len(c) > 1}
    assert targets == {DRILL_DB}


async def test_empty_stats_never_start_a_drill(s: Settings) -> None:
    world = await _world()
    world.backups[-1] = replace(world.backups[-1], size_bytes=None, document_count=None)
    rig = await _rig(s, world=world)
    assert await rig.tick() == "waiting"
    assert "restore" not in rig.admin.names()
    world.backups[-1] = replace(world.backups[-1], size_bytes=10_000, document_count=0)
    assert await rig.tick() == "waiting"
    world.backups[-1] = replace(world.backups[-1], size_bytes=10_000, document_count=11)
    assert await rig.tick() == "started"


async def test_a_backup_over_the_cap_is_refused_before_any_restore(s: Settings) -> None:
    world = await _world()
    world.backups[-1] = replace(world.backups[-1], size_bytes=6 * GIB)  # ≈ ₹114 a restore
    rig = await _rig(s, world=world)
    assert await rig.tick() == "refused"
    assert "restore" not in rig.admin.names()
    last = await rig.log.last_result()
    assert last is not None and (last.outcome, last.reason) == ("failed", "over_cap")
    assert rig.sent.kinds() == [("backup_problem", "drill_failed")]
    assert (await rig.log.state()).auto_month == "202612"


async def test_a_missing_document_fails_the_drill_and_the_copy_still_goes(s: Settings) -> None:
    world = await _world()
    world.drop_on_restore = (f"{PREFIX}notes/n1",)
    rig = await _rig(s, world=world)
    await rig.until_idle()
    last = await rig.log.last_result()
    assert last is not None and (last.outcome, last.reason) == ("failed", "count_mismatch")
    assert world.drill is None and rig.sent.kinds() == [("backup_problem", "drill_failed")]


async def test_a_left_over_copy_is_cleaned_first_and_the_restore_waits(s: Settings) -> None:
    world = await _world()
    world.restore_into_drill(world.backups[-1].name)
    world.drill_protection = True
    rig = await _rig(s, world=world)
    assert await rig.tick() == "done"  # the left-over copy is gone; no result of its own
    assert world.drill is None and "restore" not in rig.admin.names()
    assert rig.admin.names().index("set_delete_protection") < rig.admin.names().index(
        "delete_database"
    )
    assert await rig.log.last_result() is None
    rig.clock.later(minutes=2)
    assert await rig.tick() == "waiting"  # an id is reusable 5 minutes after a delete
    rig.clock.later(minutes=30)
    assert await rig.tick() == "started"


async def test_a_restored_copy_with_delete_protection_is_still_deleted(s: Settings) -> None:
    rig = await _rig(s)
    assert await rig.tick() == "started"
    rig.world.drill_protection = True  # what a restore inherits is not documented
    await rig.until_idle()
    assert rig.world.drill is None


async def test_a_copy_that_cant_be_deleted_is_told_after_two_days_then_weekly(
    s: Settings,
) -> None:
    world = await _world(delete_fails=True)
    rig = await _rig(s, world=world)
    for _ in range(4):
        await rig.tick()
        rig.clock.later(minutes=30)
    assert world.drill is not None and (await rig.log.state()).phase == "cleanup"
    assert ("backup_problem", "copy_left") not in rig.sent.kinds()
    rig.clock.later(days=2, hours=1)
    await rig.tick()
    rig.clock.later(days=1)
    await rig.tick()
    assert rig.sent.kinds().count(("backup_problem", "copy_left")) == 1
    rig.clock.later(days=7)
    await rig.tick()
    assert rig.sent.kinds().count(("backup_problem", "copy_left")) == 2
    world.delete_fails = False
    rig.clock.later(minutes=30)
    assert await rig.tick() == "done" and world.drill is None


async def test_the_clean_up_runs_whatever_the_switches_say(s: Settings) -> None:
    world = await _world()
    world.restore_into_drill(world.backups[-1].name)
    off = s.model_copy(update={"backup_drill_enabled": False, "backup_checks_enabled": False})
    rig = await _rig(off, world=world)
    assert await rig.tick() == "done" and world.drill is None
    assert "restore" not in rig.admin.names()
    assert await rig.tick() == "idle" and rig.admin.names().count("get_database") == 2


async def test_access_taken_away_after_the_set_up_is_no_job_failure(s: Settings) -> None:
    off = s.model_copy(update={"backup_drill_enabled": False})
    rig = await _rig(off)
    rig.world.denied = True  # the canary job tells "no schedule, or JARVIS's access to it"
    assert await rig.tick() == "idle"


async def test_switched_off_mid_drill_it_stops_and_cleans_up_without_an_alert(s: Settings) -> None:
    rig = await _rig(s, world=await _world(restore_polls=3))
    assert await rig.tick() == "started"
    rig.drill = Drill(replace(rig.deps, s=s.model_copy(update={"backup_drill_enabled": False})))
    rig.clock.later(minutes=30)
    assert await rig.tick() == "done"
    last = await rig.log.last_result()
    assert last is not None and (last.outcome, last.reason) == ("skipped", "switched_off")
    assert rig.world.drill is None and rig.sent.sent == []


async def test_a_restore_that_makes_no_database_fails(s: Settings) -> None:
    rig = await _rig(s, world=await _world(restore_fails=True))
    await rig.until_idle()
    last = await rig.log.last_result()
    assert last is not None and (last.outcome, last.reason) == ("failed", "restore")


async def test_a_drill_stuck_for_three_days_fails_and_cleans_up(s: Settings) -> None:
    rig = await _rig(s, world=await _world(restore_polls=10_000))
    assert await rig.tick() == "started"
    rig.clock.later(days=3, minutes=1)
    assert await rig.tick() == "done"
    last = await rig.log.last_result()
    assert last is not None and last.reason == "stuck" and rig.world.drill is None


async def test_without_a_key_no_drill_spends_anything(s: Settings) -> None:
    rig = await _rig(s, keys=None)
    assert await rig.tick() == "refused"
    last = await rig.log.last_result()
    assert last is not None and last.reason == "no_key" and "restore" not in rig.admin.names()


async def test_the_checks_resume_across_ticks(s: Settings) -> None:
    left = iter([60.0, 1.0] * 400)
    rig = await _rig(s, time_left=lambda: next(left))
    said = await rig.until_idle(ticks=60)
    assert said.count("verifying") > 3 and said[-1] == "done"
    last = await rig.log.last_result()
    assert last is not None and last.outcome == "passed"


async def test_a_check_that_keeps_raising_ends_the_drill(s: Settings) -> None:
    rig = await _rig(s)

    class Broken(FakeWalk):
        async def count(self, collection_group: str) -> int:
            raise RuntimeError("aggregation refused")

    rig.drill = Drill(replace(rig.deps, walk=lambda: Broken(rig.world)))
    said = await rig.until_idle()
    assert said[-1] == "done"
    last = await rig.log.last_result()
    assert last is not None and (last.outcome, last.reason) == ("failed", "unknown")
    assert rig.world.drill is None


# ---- a drill he starts himself (the card's run) ---------------------------------------------
async def test_he_can_ask_for_a_drill_at_most_twice_a_month(s: Settings) -> None:
    rig = await _rig(s, at=dt.datetime(2026, 12, 10, 3, 0, tzinfo=dt.UTC))
    await rig.log.save((await rig.log.state()).model_copy(update={"auto_month": "202612"}))
    assert await rig.drill.request() == REQUESTED
    assert await rig.drill.request() == ALREADY
    said = await rig.until_idle()
    assert said[0] == "started" and said[-1] == "done"
    last = await rig.log.last_result()
    assert last is not None and last.manual is True
    assert await rig.drill.request() == REQUESTED
    await rig.until_idle()
    third = await rig.drill.request()
    assert third == CAP_LINE.format(n=2, day=1)
    rig.clock.at = dt.datetime(2027, 1, 10, 3, 0, tzinfo=dt.UTC)
    assert await rig.drill.request() == REQUESTED  # a new month


async def test_a_drill_he_asked_for_counts_as_the_months_drill(s: Settings) -> None:
    rig = await _rig(s, at=dt.datetime(2026, 12, 10, 3, 0, tzinfo=dt.UTC))
    assert await rig.drill.request() == REQUESTED
    await rig.until_idle()
    assert (await rig.log.state()).auto_month == "202612"
    assert await rig.tick() == "idle"  # no second restore the same month


async def test_no_manual_drill_before_the_set_up_or_when_switched_off(s: Settings) -> None:
    rig = await _rig(s, set_up=False)
    assert await rig.drill.request() == NOT_SET_UP_LINE
    rig = await _rig(s.model_copy(update={"backup_drill_enabled": False}))
    assert await rig.drill.request() == OFF_LINE
    rig = await _rig(s.model_copy(update={"backup_drill_manual_per_month": 0}))
    assert await rig.drill.request() == CAP_LINE.format(n=0, day=1)


async def test_one_drill_at_a_time(s: Settings) -> None:
    rig = await _rig(s, world=await _world(restore_polls=3))
    assert await rig.tick() == "started"
    assert await rig.drill.request() == ALREADY
