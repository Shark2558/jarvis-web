# tests/test_r14_a_status.py -- R14 Part A (docs/plans/r14-hardening.md D3, D4, D5): the daily
# canary (a sealed random nonce, its hash and the key's fingerprint, kept 30 days), the backups'
# status (`backup_status/current`, read by B and Vitals only through `BackupStatus`), the drill's
# log (`backup_drill/current`, `backup_drills/{yyyymm}`, 13 months), the costs in rupees and the
# fixed alert texts (once per cause a day, the left-over copy weekly, the claim before the send).
from __future__ import annotations

import datetime as dt
from zoneinfo import ZoneInfo

import pytest
from r14_fakes_a import (
    GIB,
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
from jarvis.backup.log import DrillLog, DrillResult
from jarvis.backup.ports import NOT_SET_UP, BackupFacts, BackupStatus
from jarvis.backup.status import (
    TEXTS,
    BackupStatusService,
    Teller,
    monthly_inr,
    restore_inr,
)
from jarvis.storage.docs import MemoryDocs

NOW = dt.datetime(2026, 11, 14, 5, 30, tzinfo=dt.UTC)
IST = ZoneInfo("Asia/Kolkata")


class Clock:
    def __init__(self, at: dt.datetime = NOW) -> None:
        self.at = at

    def __call__(self) -> dt.datetime:
        return self.at


# ---- the canary -----------------------------------------------------------------------------
def test_a_canary_opens_only_with_the_key_that_sealed_it() -> None:
    keys = ring()
    doc = canary.make(keys, "20261114", NOW)
    assert set(doc) == {"hash", "sealed", "fp", "v", "at"}
    assert len(doc["fp"]) == 16 and doc["fp"] == canary.fingerprint(keys)
    assert canary.opens(keys, doc, "20261114") == "ok"
    assert canary.opens(ring(OTHER_KEY), doc, "20261114") == "key"
    assert canary.opens(keys, doc, "20261113") == "key"  # the AAD names the day
    assert canary.opens(keys, {**doc, "hash": "0" * 64}, "20261114") == "mismatch"
    assert canary.opens(keys, {"at": "x"}, "20261114") == "unreadable"
    assert canary.make(keys, "20261114", NOW)["hash"] != doc["hash"]  # a new nonce each time


async def test_the_canary_is_written_once_a_day_and_kept_thirty_days() -> None:
    docs = MemoryDocs()
    store = canary.CanaryStore(docs, prefix=PREFIX, zone=IST)
    keys = ring()
    for back in (40, 31, 30, 1):
        old = NOW - dt.timedelta(days=back)
        assert await store.write(keys, old) is True
    assert await store.write(keys, NOW) is True
    assert await store.write(keys, NOW) is False  # today's is there already
    assert await store.prune(NOW) == 2
    days = [d for d, _ in await store.all()]
    assert days == ["20261015", "20261113", "20261114"]
    before = await store.latest_before("20261114")
    assert before is not None and before[0] == "20261113"
    assert await store.key_changed(keys, "20261114") is False
    assert await store.key_changed(ring(OTHER_KEY), "20261114") is True


async def test_the_canary_day_is_his_day_not_utcs() -> None:
    store = canary.CanaryStore(MemoryDocs(), prefix=PREFIX, zone=IST)
    keys = ring()
    before = dt.datetime(2026, 11, 13, 23, 59, tzinfo=dt.UTC)  # 05:29 on the 14th in Kolkata
    assert await store.write(keys, before) is True
    assert await store.write(keys, before + dt.timedelta(minutes=2)) is False  # 05:31: same day
    assert [d for d, _ in await store.all()] == ["20261114"]
    assert store.today(before) == "20261114"


async def test_no_canary_before_means_no_key_change() -> None:
    store = canary.CanaryStore(MemoryDocs(), prefix=PREFIX, zone=IST)
    assert await store.key_changed(ring(), "20261114") is False


# ---- the costs (S2, at the live rate) -------------------------------------------------------
def test_the_costs_in_rupees() -> None:
    assert restore_inr(GIB, 95.24) == pytest.approx(19.05, abs=0.01)
    assert restore_inr(int(5.25 * GIB), 95.24) == pytest.approx(100.0, abs=0.1)
    assert monthly_inr(100 * 1024 * 1024, 95.24) == pytest.approx(3.86, abs=0.05)
    assert monthly_inr(GIB, 95.24) == pytest.approx(39.1, abs=0.2)
    assert monthly_inr(GIB, 95.24, drills=0) == pytest.approx(20.0, abs=0.1)


# ---- the status -----------------------------------------------------------------------------
def _service(docs: MemoryDocs, clock: Clock) -> BackupStatusService:
    log = DrillLog(docs, prefix=PREFIX, clock=clock, zone=IST)
    return BackupStatusService(docs, log, prefix=PREFIX, clock=clock, zone=IST)


async def test_before_the_set_up_the_facts_say_not_set_up() -> None:
    docs, world = MemoryDocs(), World(denied=True)
    status: BackupStatus = _service(docs, Clock())  # the port, as B and Vitals read it
    assert callable(getattr(status, "facts", None))
    assert await status.facts() == NOT_SET_UP
    assert isinstance(status, BackupStatusService)
    doc = await status.refresh(FakeAdmin(world))
    assert doc.set_up is False and doc.schedule_now is False
    assert await status.facts() == NOT_SET_UP


async def test_the_status_keeps_the_newest_ready_backup_and_when_the_schedule_was_first_seen() -> (
    None
):
    docs, world, clock = MemoryDocs(), World(), Clock()
    world.snapshot("b-old", at=SNAP - dt.timedelta(days=1), size_bytes=10, document_count=5)
    world.snapshot("b-new", at=SNAP, size_bytes=None, document_count=None)  # stats not filled
    status = _service(docs, clock)
    doc = await status.refresh(FakeAdmin(world))
    assert doc.set_up and doc.schedule_seen_at == NOW and doc.copies == 2
    assert (doc.newest_name, doc.newest_at) == ("b-new", SNAP)
    assert (doc.size_bytes, doc.document_count) == (10, 5)  # the newest with its stats
    clock.at = NOW + dt.timedelta(days=1)
    world.schedules.clear()
    doc = await status.refresh(FakeAdmin(world))
    assert doc.schedule_seen_at == NOW and doc.schedule_now is False
    got = await status.facts()
    assert got == BackupFacts(
        set_up=True, schedule_seen_at=NOW, newest_at=SNAP, size_bytes=10, document_count=5
    )


async def test_the_facts_carry_the_last_drills_result() -> None:
    docs, clock = MemoryDocs(), Clock()
    log = DrillLog(docs, prefix=PREFIX, clock=clock, zone=IST)
    await log.record(DrillResult(outcome="failed", reason="count_mismatch", at=NOW))
    status = BackupStatusService(docs, log, prefix=PREFIX, clock=clock, zone=IST)
    got = await status.facts()
    assert got.drill == "failed: count_mismatch" and got.drill_at == NOW
    await log.record(DrillResult(outcome="passed", at=NOW + dt.timedelta(days=30)))
    assert (await status.facts()).drill == "passed"
    await log.record(DrillResult(outcome="skipped", reason="no_vault", at=NOW + dt.timedelta(40)))
    assert (await status.facts()).drill == "skipped: no vault"


async def test_a_drill_result_is_kept_under_his_month_not_utcs() -> None:
    docs = MemoryDocs()
    log = DrillLog(docs, prefix=PREFIX, clock=Clock(), zone=IST)
    await log.record(DrillResult(outcome="passed", at=dt.datetime(2026, 11, 3, 1, tzinfo=dt.UTC)))
    first = dt.datetime(2026, 11, 30, 23, 30, tzinfo=dt.UTC)  # 05:00 on 1 Dec in Kolkata
    await log.record(DrillResult(outcome="failed", reason="over_cap", at=first))
    months = dict(await log.results())
    assert months["202611"].outcome == "passed"  # November's real result is kept
    assert months["202612"].reason == "over_cap"


async def test_drill_results_are_kept_thirteen_months() -> None:
    docs = MemoryDocs()
    log = DrillLog(docs, prefix=PREFIX, clock=Clock(), zone=IST)
    start = dt.datetime(2025, 9, 1, tzinfo=dt.UTC)
    for n in range(15):
        at = (start + dt.timedelta(days=31 * n)).replace(day=1)
        await log.record(DrillResult(outcome="passed", at=at))
    months = [m for m, _ in await log.results()]
    assert len(months) == 13 and months[-1] == "202611" and months[0] == "202511"


# ---- the fixed texts and the claims ---------------------------------------------------------
async def test_a_problem_is_told_once_a_cause_a_day_and_the_claim_comes_first() -> None:
    docs, clock = MemoryDocs(), Clock()
    status, sent = _service(docs, clock), RecordingNotifier()
    teller = Teller(status, lambda: sent)
    assert await teller.problem((UID,), "stale") == 1
    assert await teller.problem((UID,), "stale") == 0
    assert await teller.problem((UID,), "no_schedule") == 1
    clock.at = NOW + dt.timedelta(days=1, minutes=1)
    assert await teller.problem((UID,), "stale") == 1
    assert sent.kinds() == [
        ("backup_problem", "stale"),
        ("backup_problem", "no_schedule"),
        ("backup_problem", "stale"),
    ]
    assert all(m == TEXTS[s.subject or ""] for _, s, m in sent.sent)


async def test_once_a_day_is_his_day_not_utcs() -> None:
    # the morning tick runs 04:00-11:30 in Kolkata; UTC midnight (05:30 there) is inside it
    docs, clock = MemoryDocs(), Clock(dt.datetime(2026, 11, 13, 22, 45, tzinfo=dt.UTC))  # 04:15
    status, sent = _service(docs, clock), RecordingNotifier()
    teller = Teller(status, lambda: sent)
    assert await teller.problem((UID,), "stale") == 1
    clock.at = dt.datetime(2026, 11, 14, 0, 15, tzinfo=dt.UTC)  # 05:45 the same morning
    assert await teller.problem((UID,), "stale") == 0
    clock.at = dt.datetime(2026, 11, 14, 22, 45, tzinfo=dt.UTC)  # 04:15 the next morning
    assert await teller.problem((UID,), "stale") == 1


async def test_the_left_over_copy_is_told_weekly() -> None:
    docs, clock = MemoryDocs(), Clock()
    status, sent = _service(docs, clock), RecordingNotifier()
    teller = Teller(status, lambda: sent)
    assert await teller.problem((UID,), "copy_left") == 1
    clock.at = NOW + dt.timedelta(days=3)
    assert await teller.problem((UID,), "copy_left") == 0
    clock.at = NOW + dt.timedelta(days=7, minutes=1)
    assert await teller.problem((UID,), "copy_left") == 1


async def test_a_failed_send_is_no_failure_and_is_not_sent_again_that_day() -> None:
    class Broken(RecordingNotifier):
        async def notify(self, *a: object, **k: object) -> object:  # type: ignore[override]
            raise RuntimeError("telegram down")

    docs, clock = MemoryDocs(), Clock()
    teller = Teller(_service(docs, clock), lambda: Broken())
    assert await teller.problem((UID,), "stale") == 0
    ok = RecordingNotifier()
    teller = Teller(_service(docs, clock), lambda: ok)
    assert await teller.problem((UID,), "stale") == 0 and ok.sent == []  # claimed before the send


async def test_no_notifier_means_nothing_is_sent_and_nothing_breaks() -> None:
    teller = Teller(_service(MemoryDocs(), Clock()), lambda: None)
    assert await teller.problem((UID,), "stale") == 0
    assert await teller.passed((UID,)) == 0


async def test_a_passed_drill_is_an_info_line_and_a_failure_names_its_reason_in_fixed_words() -> (
    None
):
    docs, clock = MemoryDocs(), Clock()
    sent = RecordingNotifier()
    teller = Teller(_service(docs, clock), lambda: sent)
    assert await teller.passed((UID,)) == 1
    assert await teller.failed((UID,), "count_mismatch") == 1
    assert sent.kinds() == [("backup_ok", "drill"), ("backup_problem", "drill_failed")]
    failed = sent.sent[1][2]
    assert "count" in failed and len(failed) <= 300
    for text in TEXTS.values():
        assert len(text) <= 300 and "₹" not in text and "{" not in text


def test_every_cause_has_its_text() -> None:
    assert set(TEXTS) == {"stale", "no_schedule", "key_changed", "copy_left", "drill_ok"}
