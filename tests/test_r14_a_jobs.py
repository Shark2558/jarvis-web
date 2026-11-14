# tests/test_r14_a_jobs.py -- R14 Part A (docs/plans/r14-hardening.md D4, D5): the two morning-tick
# jobs. `backup_canary` writes the day's canary (and prunes past 30 days), refreshes the status at
# most every 3 hours and, only after the set-up has run once, tells him once a cause a day when
# the newest copy is older than `backup_max_age_h`, the schedule is gone or the key changed.
# `backup_drill` steps the drill. Neither ever fails for "not set up yet".
from __future__ import annotations

import datetime as dt

from r14_fakes_a import (
    IST,
    OTHER_KEY,
    PREFIX,
    SNAP,
    UID,
    FakeAdmin,
    RecordingNotifier,
    World,
    ring,
)

from jarvis.backup import canary
from jarvis.backup.jobs import STATUS_EVERY, BackupCanaryJob, BackupDrillJob
from jarvis.backup.log import DrillLog
from jarvis.backup.status import BackupStatusService, Teller
from jarvis.config import Settings
from jarvis.keyring import Keyring
from jarvis.ticks import TickJob, run_jobs

OWNERS = (UID,)


class Clock:
    def __init__(self, at: dt.datetime) -> None:
        self.at = at

    def __call__(self) -> dt.datetime:
        return self.at


class Rig:
    def __init__(
        self, s: Settings, world: World, *, keys: Keyring | None = None, admin: bool = True
    ) -> None:
        self.world, self.clock, self.sent = (
            world,
            Clock(SNAP + dt.timedelta(hours=2)),
            RecordingNotifier(),
        )
        self.admin = FakeAdmin(world)
        log = DrillLog(world.live, prefix=PREFIX, clock=self.clock, zone=IST)
        self.status = BackupStatusService(
            world.live, log, prefix=PREFIX, clock=self.clock, zone=IST
        )
        self.canaries = canary.CanaryStore(world.live, prefix=PREFIX, zone=IST)
        self.job = BackupCanaryJob(
            s=s,
            canaries=self.canaries,
            status=self.status,
            teller=Teller(self.status, lambda: self.sent),
            admin=self.admin if admin else None,
            ring=keys,
            clock=self.clock,
        )

    def later(self, **kw: float) -> None:
        self.clock.at += dt.timedelta(**kw)


def test_the_jobs_are_tick_jobs_with_their_planned_names() -> None:
    world = World()
    job = Rig(Settings(_env_file=None), world).job
    assert isinstance(job, TickJob) and job.name == "backup_canary" and 0 < job.budget_s <= 60
    drill_job = BackupDrillJob(None)
    assert isinstance(drill_job, TickJob) and drill_job.name == "backup_drill"


async def test_before_the_set_up_it_writes_the_canary_and_tells_nothing(settings: Settings) -> None:
    rig = Rig(settings, World(denied=True), keys=ring())
    got = await run_jobs((rig.job,), OWNERS)
    assert got == {"backup_canary": "ok"}  # Google's refusal is "not set up", never a failure
    assert len(await rig.canaries.all()) == 1
    rig.later(days=3)
    assert await run_jobs((rig.job,), OWNERS) == {"backup_canary": "ok"}
    assert rig.sent.sent == []


async def test_after_the_set_up_a_stale_backup_is_told_once_a_day(settings: Settings) -> None:
    world = World()
    world.snapshot()
    rig = Rig(settings, world, keys=ring())
    assert (await rig.job.run(OWNERS))["listed"] == 1
    assert rig.sent.sent == []
    rig.later(hours=settings.backup_max_age_h)  # 38 hours after the snapshot
    for _ in range(3):
        await rig.job.run(OWNERS)
        rig.later(minutes=30)
    assert rig.sent.kinds() == [("backup_problem", "stale")]
    rig.later(days=1)
    await rig.job.run(OWNERS)
    assert rig.sent.kinds().count(("backup_problem", "stale")) == 2


async def test_the_status_is_listed_at_most_every_three_hours(settings: Settings) -> None:
    world = World()
    world.snapshot()
    rig = Rig(settings, world, keys=ring())
    await rig.job.run(OWNERS)
    rig.later(minutes=30)
    await rig.job.run(OWNERS)
    assert rig.admin.names().count("list_backups") == 1
    rig.later(seconds=STATUS_EVERY.total_seconds())
    await rig.job.run(OWNERS)
    assert rig.admin.names().count("list_backups") == 2


async def test_a_schedule_that_went_away_is_told(settings: Settings) -> None:
    world = World()
    world.snapshot()
    rig = Rig(settings, world, keys=ring())
    await rig.job.run(OWNERS)
    world.schedules.clear()
    rig.later(hours=4)
    await rig.job.run(OWNERS)
    assert rig.sent.kinds() == [("backup_problem", "no_schedule")]


def _job(rig: Rig, keys: Keyring) -> BackupCanaryJob:
    return BackupCanaryJob(
        s=rig.job._s,  # noqa: SLF001 - the same settings, a new key
        canaries=rig.canaries,
        status=rig.status,
        teller=Teller(rig.status, lambda: rig.sent),
        admin=rig.admin,
        ring=keys,
        clock=rig.clock,
    )


async def test_a_changed_key_is_told_once_a_day(settings: Settings) -> None:
    world = World()
    world.snapshot()
    rig = Rig(settings, world, keys=ring())
    await rig.job.run(OWNERS)
    rig.later(days=1)
    rig.job = _job(rig, ring(OTHER_KEY))
    await rig.job.run(OWNERS)
    await rig.job.run(OWNERS)
    assert ("backup_problem", "key_changed") in rig.sent.kinds()
    assert rig.sent.kinds().count(("backup_problem", "key_changed")) == 1


async def test_a_changed_key_is_told_each_day_until_a_drill_passes(settings: Settings) -> None:
    world = World()
    world.snapshot()
    rig = Rig(settings, world, keys=ring())
    await rig.job.run(OWNERS)
    rig.later(days=1)
    rig.job = _job(rig, ring(OTHER_KEY))
    await rig.job.run(())  # nobody to tell that morning: the change is kept, not lost
    await rig.job.run(OWNERS)
    rig.later(days=1)  # the next day's canary opens with the new key, yet he is told again
    await rig.job.run(OWNERS)
    assert rig.sent.kinds().count(("backup_problem", "key_changed")) == 2
    await rig.status.clear_key_changed()  # a restore drill passed with the new key
    rig.later(days=1)
    await rig.job.run(OWNERS)
    assert rig.sent.kinds().count(("backup_problem", "key_changed")) == 2


async def test_a_key_change_is_told_until_every_copy_has_the_new_key(settings: Settings) -> None:
    world = World()
    world.snapshot()
    rig = Rig(settings, world, keys=ring())
    await rig.job.run(OWNERS)
    rig.later(days=1)
    rig.job = _job(rig, ring(OTHER_KEY))
    for _ in range(12):
        world.snapshot(f"b{len(world.backups)}", at=rig.clock.at)
        await rig.job.run(OWNERS)
        rig.later(days=1)
    assert rig.sent.kinds().count(("backup_problem", "key_changed")) == 8  # 7-day copies + 1


async def test_a_failing_canary_still_lets_the_alerts_run(settings: Settings) -> None:
    world = World()
    world.snapshot()
    rig = Rig(settings, world, keys=ring())
    await rig.job.run(OWNERS)

    async def broken(*_: object) -> bool:
        raise RuntimeError("a bad canary document")

    rig.canaries.write = broken  # type: ignore[method-assign]
    rig.later(hours=settings.backup_max_age_h)
    got = await rig.job.run(OWNERS)
    assert got["failed"] == 1 and rig.sent.kinds() == [("backup_problem", "stale")]


async def test_a_failing_list_still_tells_stale_from_the_stored_status(
    settings: Settings,
) -> None:
    world = World()
    world.snapshot()
    rig = Rig(settings, world, keys=ring())
    await rig.job.run(OWNERS)

    async def down() -> list[object]:
        raise RuntimeError("Google's admin endpoint is down")

    rig.admin.list_backups = down  # type: ignore[method-assign]
    rig.later(hours=settings.backup_max_age_h)
    got = await run_jobs((rig.job,), OWNERS)
    assert got == {"backup_canary": "failed"}  # counted, so Part B sees a streak
    assert rig.sent.kinds() == [("backup_problem", "stale")]


async def test_switched_off_the_job_does_nothing(settings: Settings) -> None:
    off = settings.model_copy(update={"backup_checks_enabled": False})
    world = World()
    world.snapshot()
    rig = Rig(off, world, keys=ring())
    assert await rig.job.run(OWNERS) == {"canary": 0, "listed": 0, "told": 0, "failed": 0}
    assert rig.admin.calls == [] and await rig.canaries.all() == []


async def test_without_a_key_or_firestore_it_still_runs(settings: Settings) -> None:
    rig = Rig(settings, World(), keys=None, admin=False)
    got = await rig.job.run(OWNERS)
    assert got["failed"] == 0 and got["canary"] == 0


async def test_storage_trouble_is_a_job_failure(settings: Settings) -> None:
    world = World()
    rig = Rig(settings, world, keys=ring())

    async def broken(*_: object) -> None:
        raise RuntimeError("firestore down")

    world.live.write = broken  # type: ignore[method-assign]
    assert await run_jobs((rig.job,), OWNERS) == {"backup_canary": "failed"}


async def test_the_drill_job_steps_the_drill_and_reports_a_raising_check() -> None:
    class Drill:
        def __init__(self, words: list[str]) -> None:
            self.words = words

        async def step(self, owners: object) -> str:
            return self.words.pop(0)

    job = BackupDrillJob(Drill(["started", "error"]))  # type: ignore[arg-type]
    assert await run_jobs((job,), OWNERS) == {"backup_drill": "ok"}
    assert await run_jobs((job,), OWNERS) == {"backup_drill": "failed"}
    assert await BackupDrillJob(None).run(OWNERS) == {"off": 1}
