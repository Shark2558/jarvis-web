# tests/test_r14_b_jobs.py -- R14 Part B (D5, D7, review A6) end to end on fakes: the 5-minute
# `selfwatch_clock` and the morning `selfwatch_daily`, with the real `ticks.run_jobs` and the
# observer, the real alert policy and storm (the ring counter).
from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from r14_fakes_b import TWO_AM, UID, BrokenDocs, FlakyJob, build_world

from jarvis.selfwatch.jobs import CLOCK_NAME, DAILY_NAME, Job, Watch
from jarvis.ticks import FAILED_COUNT, JobOutcome, run_jobs

IST = ZoneInfo("Asia/Kolkata")


def ist(day: int, hh: int, mm: int = 0) -> datetime:
    return datetime(2026, 11, day, hh, mm, tzinfo=IST).astimezone(UTC)


async def _runs(w, n: int, *jobs, every: float = 5) -> None:  # type: ignore[no-untyped-def]
    for _ in range(n):
        await w.watchdog(*jobs)
        w.clock.advance(minutes=every)


def test_the_two_jobs_have_their_planned_names_and_budgets() -> None:
    w = build_world()
    assert (w.watch.clock_job.name, w.watch.daily_job.name) == (CLOCK_NAME, DAILY_NAME)
    assert CLOCK_NAME == "selfwatch_clock" and DAILY_NAME == "selfwatch_daily"
    assert 0 < w.watch.clock_job.budget_s <= 10 and 0 < w.watch.daily_job.budget_s <= 30


async def test_three_failures_in_a_row_make_one_alert_and_it_stays_one() -> None:
    w = build_world()
    job = FlakyJob("vault_reminders")
    await _runs(w, 4, job)  # three failures seen, then the clock reports
    assert w.ring.kinds() == ["job_failing"]
    assert w.ring.sent[0].text.startswith("1 background job keeps failing: vault_reminders.")
    await _runs(w, 36, job)  # three more hours of failing
    assert w.ring.kinds() == ["job_failing"]
    job.failing = False
    await _runs(w, 2, job)
    assert w.ring.kinds() == ["job_failing", "selfwatch_ok"]
    assert w.ring.sent[1].text == "JARVIS's background jobs are working again."


async def test_two_failures_then_ok_are_no_streak() -> None:
    w = build_world()
    job = FlakyJob("memory")
    await _runs(w, 2, job)
    job.failing = False
    await _runs(w, 3, job)
    assert w.ring.sent == []


async def test_skips_never_count() -> None:
    w = build_world()
    for _ in range(10):
        w.watch.observe(JobOutcome("watchdog", "health_check", "skipped", 0.0))
        await w.watch.clock_job.run((UID,))
        w.clock.advance(minutes=5)
    assert w.ring.sent == []


async def test_new_streaks_wait_for_the_hour_then_one_alert_names_them_all() -> None:
    w = build_world()
    a, b = FlakyJob("alpha"), FlakyJob("beta", failing=False)
    await _runs(w, 4, a, b)
    assert len(w.ring.sent) == 1
    b.failing = True
    await _runs(w, 6, a, b)  # beta in a streak 30 minutes after the first alert: it waits
    assert len(w.ring.sent) == 1
    await _runs(w, 8, a, b)
    assert w.ring.kinds() == ["job_failing", "job_failing"]
    assert "2 background jobs keep failing: alpha, beta." in w.ring.sent[1].text
    assert w.ring.sent[1].subject == "jobs"


async def test_a_selfwatch_job_never_reports_its_own_streak() -> None:
    w = build_world()
    for _ in range(4):
        w.watch.observe(JobOutcome("watchdog", CLOCK_NAME, "failed", 1.0))
    await w.watch.clock_job.run((UID,))
    assert w.ring.sent == []  # the clock never reports itself
    await w.watch.daily_job.run((UID,))
    assert w.ring.kinds() == ["job_failing"] and CLOCK_NAME in w.ring.sent[0].text


async def test_a_whole_firestore_outage_rings_at_most_once() -> None:
    w = build_world(docs=BrokenDocs())
    jobs = [FlakyJob(n) for n in ("health_check", "helpers_clock", "mobile_clock", "home_offline")]
    for _ in range(12):  # an hour of 5-minute runs
        got = await w.watchdog(*jobs)
        assert got[CLOCK_NAME] == "failed"  # its own documents can't be kept
        w.clock.advance(minutes=5)
    assert len(w.ring.rings()) <= 1 and w.ring.kinds() == ["job_failing"]


async def test_nothing_rings_at_two_in_the_morning() -> None:
    w = build_world(now=TWO_AM)
    await w.watch.deploys.check(w.docs, TWO_AM)  # an earlier revision was live
    w.watch.deploys = type(w.watch.deploys)(revision="jarvis-00042", version="14.1.0")
    await _runs(w, 5, FlakyJob("web"))
    assert set(w.ring.kinds()) == {"job_failing", "deploy_changed"}
    assert w.ring.rings() == []  # held for the morning summary


async def test_the_errors_alert_once_a_day_after_more_than_the_limit_in_an_hour() -> None:
    w = build_world()
    log = logging.getLogger("jarvis.vault.service")
    root = logging.getLogger()
    root.addHandler(w.watch.errors)
    try:
        for _ in range(30):
            log.error("boom")
        await w.watch.clock_job.run((UID,))
        assert w.ring.sent == []
        log.error("boom")
        await w.watch.clock_job.run((UID,))
        assert w.ring.kinds() == ["errors_piling"]
        assert "jarvis" not in w.ring.sent[0].text and "boom" not in w.ring.sent[0].text
        for _ in range(40):
            log.error("boom")
        await w.watch.clock_job.run((UID,))
        assert w.ring.kinds() == ["errors_piling"]  # once a day
    finally:
        root.removeHandler(w.watch.errors)


async def test_errors_wait_while_failing_jobs_were_told() -> None:
    w = build_world()
    await _runs(w, 4, FlakyJob("web"))
    root = logging.getLogger()
    root.addHandler(w.watch.errors)
    try:
        for _ in range(40):
            logging.getLogger("jarvis.web").error("boom")
        await w.watch.clock_job.run((UID,))
    finally:
        root.removeHandler(w.watch.errors)
    assert w.ring.kinds() == ["job_failing"]  # the same incident, said once


async def test_the_brief_missed_is_said_by_the_five_minute_clock() -> None:
    w = build_world(now=ist(16, 7, 55))
    w.brief.due_at = ist(16, 7, 0).astimezone(IST)
    await _runs(w, 2)
    assert w.ring.kinds() == ["brief_missed"]
    assert (
        w.ring.sent[0].text
        == "Today's morning brief wasn't made by 08:00. Open JARVIS to make it now."
    )


async def test_a_new_revision_is_said_once() -> None:
    docs = __import__("jarvis.storage.docs", fromlist=["MemoryDocs"]).MemoryDocs()
    first = build_world(docs=docs, version="14.0.0")
    await first.watchdog()
    later = build_world(docs=docs, version="14.0.1")
    await _runs(later, 3)
    assert later.ring.kinds() == ["deploy_changed"]
    assert "14.0.1" in later.ring.sent[0].text and first.ring.sent == []


async def test_the_tick_says_the_five_minute_clock_stopped_and_it_says_it_is_back() -> None:
    w = build_world(now=ist(16, 7, 0))
    await w.watchdog()
    w.clock.now = ist(16, 7, 30)
    await w.tick()
    assert w.ring.kinds() == ["clock_stopped"]
    assert "has not run since 07:00" in w.ring.sent[0].text
    w.clock.now = ist(16, 8, 0)
    await w.tick()
    assert w.ring.kinds() == ["clock_stopped"]
    w.clock.now = ist(16, 8, 2)
    await w.watchdog()
    assert w.ring.kinds() == ["clock_stopped", "selfwatch_ok"]


async def test_the_five_minute_clock_says_no_tick_ran_by_five() -> None:
    w = build_world(now=ist(15, 9, 0))
    await w.tick()
    w.clock.now = ist(16, 5, 0)
    await w.watchdog()
    assert w.ring.kinds() == ["clock_stopped"]
    assert "did not run today by 05:00" in w.ring.sent[0].text
    w.clock.now = ist(16, 5, 58)
    await w.watchdog()  # the 5-minute clock keeps running meanwhile
    w.clock.now = ist(16, 6, 0)
    await w.tick()
    assert w.ring.kinds() == ["clock_stopped", "selfwatch_ok"]


async def test_the_daily_job_says_a_spend_spike_with_its_rupees() -> None:
    w = build_world(now=ist(2, 4, 0))
    total = 0.0
    for day in range(2, 12):
        w.clock.now = ist(day, 4, 0)
        total += 400.0 if day == 11 else 20.0
        w.billing.inr[UID] = total
        await w.watchdog()  # the 5-minute clock runs alongside
        await w.tick()
    assert w.ring.kinds() == ["spend_spike"]
    assert "₹400" in w.ring.sent[0].text


async def test_the_jobs_answer_counts_and_the_observer_never_raises() -> None:
    w = build_world()
    got = await w.watch.clock_job.run((UID, "../bad"))
    assert all(isinstance(v, int) for v in got.values()) and got[FAILED_COUNT] == 0
    assert got["owners"] == 1
    w.watch.observe(object())  # type: ignore[arg-type]
    w.watch.observe(JobOutcome("watchdog", "x" * 500, "failed", 0.0))
    assert w.watch.observer_failures == 1  # silent review L2: counted, never silent


async def test_an_observer_that_failed_is_logged_once_by_the_next_run(
    caplog: pytest.LogCaptureFixture,
) -> None:
    w = build_world()
    caplog.set_level(logging.WARNING, logger="jarvis.selfwatch.jobs")
    w.watch.observe(object())  # type: ignore[arg-type]
    await w.watch.clock_job.run((UID,))
    await w.watch.clock_job.run((UID,))
    assert len([r for r in caplog.records if "observer" in r.getMessage()]) == 1


def test_the_watch_reads_its_settings() -> None:
    w = build_world(selfwatch_fail_streak=5, selfwatch_errors_per_hour=99)
    assert isinstance(w.watch, Watch)
    assert (w.watch.streak, w.watch.errors_limit) == (5, 99)
    assert w.watch.tz == IST and w.clock.now - timedelta(0) == w.clock()


async def test_errors_from_just_before_midnight_count_for_their_own_day() -> None:
    w = build_world(now=ist(16, 0, 5))
    for _ in range(31):
        rec = logging.LogRecord("jarvis.web", logging.ERROR, __file__, 1, "boom", (), None)
        rec.created = ist(15, 23, 50).timestamp()
        w.watch.errors.handle(rec)
    await w.watch.clock_job.run((UID,))
    assert w.ring.kinds() == ["errors_piling"]


# ---- time shares (silent review M4) --------------------------------------------------------------
async def _hangs(owners, now, me):  # type: ignore[no-untyped-def]
    await asyncio.sleep(60)
    return 0, True


def _job(w, budget: float, *steps):  # type: ignore[no-untyped-def]
    return Job(CLOCK_NAME, budget, w.watch, steps)


async def test_a_hung_step_starves_neither_the_others_nor_the_ledger() -> None:
    w = build_world()
    seen: list[str] = []

    async def after(owners, now, me):  # type: ignore[no-untyped-def]
        seen.append(me)
        return 0, True

    w.watch.observe(JobOutcome("watchdog", "web", "failed", 0.0))
    job = _job(w, 1.0, w.watch.load, _hangs, after)
    got = await run_jobs((job,), (UID,), clock="watchdog", total_budget_s=50.0)
    assert got == {CLOCK_NAME: "failed"}  # its own step failed, never "timed_out"
    assert seen == [CLOCK_NAME] and job.last[FAILED_COUNT] == 1
    stored = await w.docs.get("jarvis_selfwatch/jobs")
    assert stored is not None and "web" in stored["jobs"]  # the ledger was kept


async def test_the_ledger_is_kept_even_when_the_job_is_cut_from_outside() -> None:
    w = build_world()
    w.watch.observe(JobOutcome("watchdog", "web", "failed", 0.0))
    job = _job(w, 10.0, w.watch.load, _hangs)
    with pytest.raises(TimeoutError):
        async with asyncio.timeout(0.2):  # what the tick had left was less than the budget
            await job.run((UID,))
    stored = await w.docs.get("jarvis_selfwatch/jobs")
    assert stored is not None and "web" in stored["jobs"]


def test_the_brief_is_checked_before_the_errors_are_written() -> None:
    names = build_world().watch.clock_job.step_names
    assert names.index("report_jobs") < names.index("errors_step")  # the incident said first
    assert names.index("briefs_step") < names.index("errors_step")
