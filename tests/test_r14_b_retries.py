# tests/test_r14_b_retries.py -- R14 Part B review follow-ups (silent review H1, L5; code review
# M1, M2; python review M3): an alert that reached nobody commits nothing, so every check raises
# it again and it is said once a channel takes it; the daily spend snapshot is tried again the
# same day after a failure. End to end on fakes (the real run_jobs, policy and storm).
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo

from r14_fakes_b import OTHER, UID, BWorld, FlakyJob, build_world

from jarvis.notify.models import NotifySettings, QuietHours
from jarvis.selfwatch import texts
from jarvis.selfwatch.deploys import DeployWatch
from jarvis.selfwatch.jobs import DAILY_NAME
from jarvis.storage.docs import MemoryDocs

IST = ZoneInfo("Asia/Kolkata")


def ist(day: int, hh: int, mm: int = 0) -> datetime:
    return datetime(2026, 11, day, hh, mm, tzinfo=IST).astimezone(UTC)


async def _runs(w: BWorld, n: int, *jobs: Any) -> None:
    for _ in range(n):
        await w.watchdog(*jobs)
        w.clock.advance(minutes=5)


# ---- job streaks ---------------------------------------------------------------------------------
async def test_a_job_alert_that_reached_nobody_is_said_when_a_channel_takes_it() -> None:
    w = build_world()
    w.ring.dead = True
    job = FlakyJob("vault_reminders")
    await _runs(w, 4, job)  # three failures: tried, no channel took it
    assert w.ring.kinds() == ["job_failing"] and w.ring.took() == []
    assert not w.watch.ledger.has_told() and w.watch.ledger.last_alert is None
    w.ring.dead = False
    await _runs(w, 6, job)  # tried again 30 minutes later
    assert w.ring.took() == ["job_failing"] and w.watch.ledger.has_told()
    await _runs(w, 24, job)
    assert w.ring.took() == ["job_failing"]  # and then once per streak, as before


async def test_a_streak_seen_before_the_notifier_exists_is_said_once_it_does() -> None:
    w = build_world()
    bound: dict[str, Any] = {"n": None}
    w.watch.teller = texts.Teller(lambda: bound["n"], w.watch.told)
    job = FlakyJob("web")
    await _runs(w, 5, job)
    assert not w.watch.ledger.has_told() and w.watch.ledger.last_alert is None
    bound["n"] = w.ring
    await _runs(w, 1, job)
    assert w.ring.took() == ["job_failing"]


async def test_the_all_clear_that_reached_nobody_is_said_later() -> None:
    w = build_world()
    job = FlakyJob("web")
    await _runs(w, 4, job)
    job.failing, w.ring.dead = False, True
    await _runs(w, 2, job)  # "working again": tried, no channel took it
    w.ring.dead = False
    await _runs(w, 7, job)
    assert w.ring.took() == ["job_failing", "selfwatch_ok"]  # silent review L5


async def test_a_capped_job_alert_is_deferred_not_lost() -> None:
    w = build_world()
    for kind in ("brief_missed", "errors_piling", "deploy_changed"):  # the hour's 3 used
        await w.watch.teller.tell((UID,), kind, "x", "x", w.clock())
    await _runs(w, 4, FlakyJob("web"))
    assert w.ring.took().count("job_failing") == 0  # the cap dropped it
    await _runs(w, 12, FlakyJob("web"))
    assert w.ring.took().count("job_failing") == 1  # code review M1


# ---- the clocks ----------------------------------------------------------------------------------
async def test_a_stopped_clock_that_reached_nobody_is_said_at_the_next_tick() -> None:
    w = build_world(now=ist(16, 7, 0))
    await w.watchdog()
    w.ring.dead = True
    w.clock.now = ist(16, 7, 30)
    await w.tick()
    assert (await w.watch.clocks.read(w.docs)).watchdog_outage is None  # nothing committed
    w.ring.dead = False
    w.clock.now = ist(16, 8, 0)
    await w.tick()
    w.clock.now = ist(16, 8, 30)
    await w.tick()
    assert w.ring.took() == ["clock_stopped"]
    w.clock.now = ist(16, 8, 32)
    await w.watchdog()
    assert w.ring.took() == ["clock_stopped", "selfwatch_ok"]


async def test_no_tick_by_five_that_reached_nobody_is_said_again() -> None:
    w = build_world(now=ist(15, 9, 0))
    w.ring.settings = NotifySettings(quiet=QuietHours(on=False))  # 05:00 would be held
    await w.tick()
    w.ring.dead = True
    w.clock.now = ist(16, 5, 0)
    await w.watchdog()
    w.ring.dead = False
    for mm in (5, 10, 15, 20, 25, 30, 35):
        w.clock.now = ist(16, 5, mm)
        await w.watchdog()
    assert w.ring.took() == ["clock_stopped"]


async def test_a_clock_back_that_reached_nobody_is_said_again() -> None:
    w = build_world(now=ist(16, 7, 0))
    await w.watchdog()
    w.clock.now = ist(16, 7, 30)
    await w.tick()
    w.ring.dead, w.clock.now = True, ist(16, 8, 2)
    await w.watchdog()  # "back": tried, no channel took it
    w.ring.dead = False
    for mm in (7, 12, 17, 22, 27, 32, 37):
        w.clock.now = ist(16, 8, mm)
        await w.watchdog()
    assert w.ring.took() == ["clock_stopped", "selfwatch_ok"]


# ---- the brief, the version, the spend -----------------------------------------------------------
async def test_a_missed_brief_that_reached_nobody_is_said_again() -> None:
    w = build_world(now=ist(16, 8, 0))
    w.brief.due_at = ist(16, 7, 0).astimezone(IST)
    w.ring.dead = True
    await _runs(w, 1)
    w.ring.dead = False
    await _runs(w, 8)
    assert w.ring.took() == ["brief_missed"]


async def test_a_new_version_that_reached_nobody_is_said_again_and_once() -> None:
    docs = MemoryDocs()
    w = build_world(docs=docs)
    await w.watchdog()
    w.watch.deploys = DeployWatch(revision="jarvis-00042", version="14.1.0")
    w.ring.dead = True
    await _runs(w, 1)
    w.ring.dead = False
    await _runs(w, 7)
    assert w.ring.took() == ["deploy_changed"]
    again = build_world(docs=docs)  # a restart of the same revision
    again.watch.deploys = DeployWatch(revision="jarvis-00042", version="14.1.0")
    await _runs(again, 2)
    assert again.ring.sent == []


async def _spend_days(w: BWorld, last_day: float, *, owners: tuple[str, ...] = (UID,)) -> None:
    total: dict[str, float] = {}
    for day in range(2, 11):
        w.clock.now = ist(day, 4, 0)
        for uid in owners:
            total[uid] = total.get(uid, 0.0) + 20.0
            w.billing.inr[uid] = total[uid]
        await w.tick()
    for uid in owners:
        w.billing.inr[uid] = total[uid] + last_day
    w.clock.now = ist(11, 4, 0)


async def test_a_spend_spike_that_reached_nobody_is_said_at_the_next_tick() -> None:
    w = build_world(now=ist(2, 4, 0))
    w.ring.settings = NotifySettings(quiet=QuietHours(on=False))  # 04:00 would be held
    await _spend_days(w, 400.0)
    w.ring.dead = True
    await w.tick()
    w.ring.dead = False
    w.clock.now = ist(11, 4, 30)
    await w.tick()
    w.clock.now = ist(11, 5, 0)
    await w.tick()
    assert w.ring.took() == ["spend_spike"] and "₹400" in w.ring.sent[-1].text


async def test_an_unreadable_spend_fails_the_step_and_is_taken_later_that_day() -> None:
    w = build_world(now=ist(2, 4, 0))
    await _spend_days(w, 400.0)
    w.billing.raises = True
    got = await w.tick()
    assert got[DAILY_NAME] == "failed"  # silent review M2: not "ok" with nothing kept
    w.billing.raises = False
    w.clock.now = ist(11, 4, 30)
    assert (await w.tick())[DAILY_NAME] == "ok"
    assert w.ring.took() == ["spend_spike"]


async def test_without_billing_yet_the_spend_waits_and_never_fails() -> None:
    w = build_world(now=ist(16, 4, 0))
    w.watch.spend = type(w.watch.spend)(
        lambda: None, tz=IST, factor=3.0, min_inr=50.0, prefix="jarvis_"
    )
    assert (await w.tick())[DAILY_NAME] == "ok"
    assert await w.docs.get("jarvis_selfwatch/spend") is None


class _SecondWriteFails(MemoryDocs):
    armed = False
    calls = 0

    async def transaction(self, fn):  # type: ignore[no-untyped-def]
        if self.armed:
            self.calls += 1
            if self.calls == 2:
                raise RuntimeError("firestore: 503")
        return await super().transaction(fn)


async def test_one_owners_failed_write_never_loses_anothers_spike() -> None:
    docs = _SecondWriteFails()
    w = build_world(now=ist(2, 4, 0), docs=docs)
    w.brief.owners = (UID, OTHER)
    await _spend_days(w, 400.0, owners=(UID, OTHER))
    w.billing.inr[OTHER] -= 400.0  # only the first owner spiked
    docs.armed = True
    got = await w.watch.spend.snapshot(docs, (UID, OTHER), w.clock())
    assert set(got.spikes) == {UID} and got.failed  # python review M3
    again = await w.watch.spend.snapshot(docs, (UID, OTHER), w.clock())
    assert set(again.spikes) == {UID} and not again.failed  # the other owner kept now
