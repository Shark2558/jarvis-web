# tests/test_r14_b_brief_spend_deploy.py -- R14 Part B (D5): the brief not made 60 minutes after
# his brief time (once a day), the day's AI spend far above normal (after 7 days of history),
# and a new version live (once per revision).
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from r14_fakes_b import OTHER, UID, BrokenDocs, FakeBilling, FakeBrief

from jarvis.selfwatch import spend
from jarvis.selfwatch.brief_check import BriefCheck
from jarvis.selfwatch.deploys import DeployWatch
from jarvis.selfwatch.spend import SpendWatch, day_spends, spike
from jarvis.storage.docs import MemoryDocs

IST = ZoneInfo("Asia/Kolkata")
GRACE = timedelta(minutes=60)


def ist(day: int, hh: int, mm: int = 0) -> datetime:
    return datetime(2026, 11, day, hh, mm, tzinfo=IST).astimezone(UTC)


def _check(brief: FakeBrief | None) -> BriefCheck:
    return BriefCheck(lambda: brief, grace=GRACE, tz=IST)


# ---- the brief -----------------------------------------------------------------------------------
async def test_the_brief_is_missed_an_hour_after_its_time() -> None:
    brief = FakeBrief(status="none", due_at=ist(16, 7, 0).astimezone(IST))
    check = _check(brief)
    assert await check.missed(UID, ist(16, 7, 59)) is None
    assert await check.missed(UID, ist(16, 8, 0)) == ("2026-11-16", "08:00")
    assert await check.missed(UID, ist(16, 8, 5)) is None  # settled for the day


async def test_a_failed_brief_is_missed_too_and_a_ready_one_never() -> None:
    failed = FakeBrief(status="failed", due_at=ist(16, 7, 0).astimezone(IST))
    assert await _check(failed).missed(UID, ist(16, 9, 0)) == ("2026-11-16", "08:00")
    ready = FakeBrief(status="ready", due_at=ist(16, 7, 0).astimezone(IST))
    assert await _check(ready).missed(UID, ist(16, 9, 0)) is None


async def test_a_brief_that_is_off_is_never_missed() -> None:
    assert await _check(FakeBrief(due_at=None)).missed(UID, ist(16, 9, 0)) is None
    assert await _check(None).missed(UID, ist(16, 9, 0)) is None


async def test_the_brief_is_read_rarely_not_every_five_minutes() -> None:
    brief = FakeBrief(status="none", due_at=ist(16, 7, 0).astimezone(IST))
    check = _check(brief)
    at = ist(16, 0, 5)
    while at < ist(16, 12, 0):
        await check.missed(UID, at)
        at += timedelta(minutes=5)
    assert brief.calls == 2  # once to learn its time, once at its time + 60 minutes


async def test_a_new_day_is_checked_again() -> None:
    brief = FakeBrief(status="none", due_at=ist(16, 7, 0).astimezone(IST))
    check = _check(brief)
    assert await check.missed(UID, ist(16, 8, 0)) is not None
    brief.date, brief.due_at = "2026-11-17", ist(17, 7, 0).astimezone(IST)
    assert await check.missed(UID, ist(17, 8, 30)) == ("2026-11-17", "08:00")


async def test_a_brief_that_cannot_be_read_raises_for_the_job_to_count() -> None:
    with pytest.raises(RuntimeError):
        await _check(FakeBrief(raises=True)).missed(UID, ist(16, 9, 0))


# ---- the spend -----------------------------------------------------------------------------------
def _snaps(days: dict[int, float], month: int = 11) -> dict[str, float]:
    return {f"2026-{month:02d}-{d:02d}": v for d, v in days.items()}


def test_a_days_spend_is_the_difference_and_the_first_stands_alone() -> None:
    got = day_spends({"2026-10-30": 100.0, "2026-10-31": 130.0, "2026-11-01": 12.0})
    assert got == [("2026-10-31", 30.0), ("2026-11-01", 12.0)]
    gap = day_spends({"2026-11-03": 10.0, "2026-11-05": 50.0})  # a missing day is no "day"
    assert gap == []


def test_a_spike_needs_seven_days_three_times_the_average_and_fifty_rupees() -> None:
    steady = {d: 20.0 * (d - 1) for d in range(2, 11)}  # ₹20 a day from the 3rd to the 10th
    snaps = _snaps({**steady, 11: steady[10] + 100.0})
    assert spike(snaps, "2026-11-11", 3.0, 50) == pytest.approx(100.0)
    assert spike(snaps, "2026-11-11", 6.0, 50) is None  # not 6 times
    assert spike(snaps, "2026-11-11", 3.0, 150) is None  # under the floor
    short = _snaps({d: 20.0 * d for d in range(5, 11)} | {11: 1000.0})
    assert spike(short, "2026-11-11", 3.0, 50) is None  # only 5 days of history
    assert spike(snaps, "2026-11-12", 3.0, 50) is None  # no figure for that day


async def test_the_snapshot_is_taken_once_a_day_and_kept_16_days() -> None:
    docs = MemoryDocs()
    billing = FakeBilling({UID: 10.0, OTHER: 5.0})
    watch = SpendWatch(lambda: billing, tz=IST, factor=3.0, min_inr=50)
    for d in range(1, 21):
        billing.inr[UID] = 10.0 * d
        await watch.snapshot(docs, (UID, OTHER), ist(d, 4, 0))
        billing.inr[UID] = 99_999.0  # a later tick the same day takes no second snapshot
        await watch.snapshot(docs, (UID, OTHER), ist(d, 4, 30))
    doc = await docs.get("jarvis_selfwatch/spend")
    assert doc is not None
    mine = doc["owners"][UID]
    assert len(mine) == spend.KEEP and max(mine) == "2026-11-20" and mine["2026-11-20"] == 200.0


async def test_a_spike_is_reported_with_its_rupees() -> None:
    docs = MemoryDocs()
    billing = FakeBilling()
    watch = SpendWatch(lambda: billing, tz=IST, factor=3.0, min_inr=50)
    total = 0.0
    got: dict[str, float] = {}
    for d in range(2, 12):
        total += 100.0 if d == 11 else 20.0
        billing.inr[UID] = total
        got = await watch.snapshot(docs, (UID,), ist(d, 4, 0))
    assert got == {UID: pytest.approx(100.0)}


async def test_unreadable_spend_skips_that_owner_only() -> None:
    watch = SpendWatch(lambda: FakeBilling(raises=True), tz=IST, factor=3.0, min_inr=50)
    assert await watch.snapshot(MemoryDocs(), (UID,), ist(16, 4, 0)) == {}
    none = SpendWatch(lambda: None, tz=IST, factor=3.0, min_inr=50)
    assert await none.snapshot(MemoryDocs(), (UID,), ist(16, 4, 0)) == {}


# ---- the version ---------------------------------------------------------------------------------
async def test_the_first_run_only_remembers_the_revision() -> None:
    docs = MemoryDocs()
    assert (
        await DeployWatch(revision="jarvis-00041", version="14.0.0").check(docs, ist(16, 9)) is None
    )
    doc = await docs.get("jarvis_selfwatch/deploy")
    assert doc is not None and doc["revision"] == "jarvis-00041" and doc["version"] == "14.0.0"


async def test_a_new_revision_is_told_once_and_an_old_one_coming_back_never() -> None:
    docs = MemoryDocs()
    await DeployWatch(revision="jarvis-00041", version="14.0.0").check(docs, ist(16, 9))
    new = DeployWatch(revision="jarvis-00042", version="14.1.0")
    assert await new.check(docs, ist(16, 10)) == ("jarvis-00042|14.1.0", "14.1.0")
    assert await new.check(docs, ist(16, 10, 5)) is None  # once per process
    restart = DeployWatch(revision="jarvis-00042", version="14.1.0")
    assert await restart.check(docs, ist(16, 11)) is None  # the same revision after a restart
    old = DeployWatch(revision="jarvis-00041", version="14.0.0")  # an old instance in a deploy
    assert await old.check(docs, ist(16, 11)) is None
    assert (await DeployWatch.current(docs))["revision"] == "jarvis-00042"


async def test_without_a_revision_the_version_decides() -> None:
    docs = MemoryDocs()
    await DeployWatch(revision=None, version="14.0.0").check(docs, ist(16, 9))
    got = await DeployWatch(revision=None, version="14.0.1").check(docs, ist(16, 9))
    assert got == ("-|14.0.1", "14.0.1")


async def test_a_store_that_is_down_is_tried_again_next_run() -> None:
    watch = DeployWatch(revision="jarvis-00042", version="14.1.0")
    with pytest.raises(RuntimeError):
        await watch.check(BrokenDocs(), ist(16, 9))
    assert await watch.check(MemoryDocs(), ist(16, 9)) is None  # first run on a new store
