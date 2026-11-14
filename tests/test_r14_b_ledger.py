# tests/test_r14_b_ledger.py -- R14 Part B (docs/plans/r14-hardening.md D5, review A6): the job
# ledger (failed or timed-out runs in a row; a skip never counts; once per streak) and the
# once-only claims (`selfwatch_told`, written before the send).
from __future__ import annotations

from datetime import timedelta

import pytest
from r14_fakes_b import NOON, UID, BrokenDocs

from jarvis.selfwatch import ledger
from jarvis.selfwatch.ledger import JobLedger, Streak, Told, step
from jarvis.storage.docs import MemoryDocs, Query

T = NOON


def test_a_failure_starts_a_streak_and_another_adds_one() -> None:
    first = step(None, "failed", T)
    assert first == Streak(1, T)
    assert step(first, "timed_out", T + timedelta(minutes=5)) == Streak(2, T)


def test_ok_ends_a_streak_and_a_skip_never_counts() -> None:
    s = Streak(2, T)
    assert step(s, "ok", T) is None
    assert step(s, "skipped", T) == s
    assert step(None, "skipped", T) is None


def _fail(book: JobLedger, name: str, n: int, start=T) -> None:  # type: ignore[no-untyped-def]
    for i in range(n):
        book.observe(name, "failed", start + timedelta(minutes=5 * i))


def test_only_jobs_with_enough_failures_in_a_row_are_failing() -> None:
    book = JobLedger()
    _fail(book, "vault_reminders", 3)
    _fail(book, "memory", 2)
    assert [n for n, _ in book.failing(3)] == ["vault_reminders"]
    assert book.untold(3) == ["vault_reminders"]


def test_skips_between_failures_keep_the_streak_and_never_add() -> None:
    book = JobLedger()
    for outcome in ("failed", "skipped", "failed", "skipped", "skipped"):
        book.observe("health_check", outcome, T)
    assert book.untold(3) == []
    book.observe("health_check", "timed_out", T)
    assert book.untold(3) == ["health_check"]


def test_a_streak_is_told_once_and_its_own_job_is_left_out() -> None:
    book = JobLedger()
    _fail(book, "selfwatch_clock", 3)
    _fail(book, "web", 3)
    assert book.untold(3, exclude="selfwatch_clock") == ["web"]
    book.mark_told(["web"], T)
    _fail(book, "web", 4, T + timedelta(hours=1))
    assert book.untold(3, exclude="selfwatch_clock") == []
    assert book.untold(3, exclude="selfwatch_daily") == ["selfwatch_clock"]
    assert book.has_told()


def test_recovered_only_when_every_told_streak_ended() -> None:
    book = JobLedger()
    _fail(book, "a", 3)
    _fail(book, "b", 3)
    book.mark_told(["a", "b"], T)
    book.observe("a", "ok", T)
    assert not book.take_recovered()
    book.observe("b", "ok", T)
    assert book.take_recovered() and not book.take_recovered()
    assert not book.has_told()


def test_an_untold_streak_ending_is_no_recovery() -> None:
    book = JobLedger()
    _fail(book, "a", 3)
    book.observe("a", "ok", T)
    assert not book.take_recovered()


def test_odd_names_are_ignored_and_the_table_is_bounded() -> None:
    book = JobLedger()
    for bad in ("", "x" * 65, "has space", "sl/ash"):
        book.observe(bad, "failed", T)
    for i in range(ledger.MAX_JOBS + 10):
        book.observe(f"job_{i}", "failed", T)
    assert len(book.failing(1)) == ledger.MAX_JOBS


async def test_the_ledger_is_kept_and_read_back_after_a_restart() -> None:
    docs = MemoryDocs()
    book = JobLedger()
    _fail(book, "vault_reminders", 3)
    book.mark_told(["vault_reminders"], T)
    book.last_alert = T
    assert await book.flush(docs) is True
    assert await book.flush(docs) is False  # nothing changed: no write
    stored = await docs.get("jarvis_selfwatch/jobs")
    assert stored is not None and set(stored) == {"jobs", "last_alert", "recovered"}
    again = JobLedger()
    await again.load(docs)
    assert again.untold(3) == [] and again.has_told() and again.last_alert == T


async def test_what_this_process_saw_wins_over_the_stored_ledger() -> None:
    docs = MemoryDocs()
    old = JobLedger()
    _fail(old, "memory", 2)
    await old.flush(docs)
    fresh = JobLedger()
    fresh.observe("memory", "ok", T)  # seen ok before the first load: the stored 2 is stale
    await fresh.load(docs)
    assert fresh.failing(1) == []


async def test_a_ledger_that_cannot_be_read_or_kept_stays_in_memory() -> None:
    book = JobLedger()
    _fail(book, "a", 3)
    with pytest.raises(RuntimeError):
        await book.flush(BrokenDocs())
    await book.load(BrokenDocs())  # logged, never raised: the ledger keeps what it saw
    assert book.untold(3) == ["a"]


# ---- the once-only claims ------------------------------------------------------------------------
async def test_a_claim_is_made_once_per_kind_and_cause() -> None:
    docs = MemoryDocs()
    told = Told(docs)
    assert await told.claim(UID, "brief_missed", "2026-11-16", T)
    assert not await told.claim(UID, "brief_missed", "2026-11-16", T)
    assert not await Told(docs).claim(UID, "brief_missed", "2026-11-16", T)  # another process
    assert await told.claim(UID, "brief_missed", "2026-11-17", T)
    assert await told.claim("owner-2", "brief_missed", "2026-11-16", T)
    rows = await docs.query(Query("jarvis_selfwatch_told"))
    assert len(rows) == 3
    for key, doc in rows:
        assert key.startswith(doc["uid"] + "_") and set(doc) == {"uid", "kind", "at"}
        assert "2026" not in key  # the cause is hashed, never kept


async def test_a_bad_owner_id_is_never_claimed() -> None:
    assert not await Told(MemoryDocs()).claim("../x", "brief_missed", "d", T)


async def test_with_the_store_down_a_claim_is_kept_in_memory_once() -> None:
    told = Told(BrokenDocs())
    assert await told.claim(UID, "job_failing", "c", T)
    assert not await told.claim(UID, "job_failing", "c", T)


async def test_old_claims_are_swept_after_30_days_and_counted_per_owner() -> None:
    docs = MemoryDocs()
    told = Told(docs)
    await told.claim(UID, "brief_missed", "old", T - timedelta(days=31))
    await told.claim(UID, "brief_missed", "new", T - timedelta(days=1))
    await told.claim("owner-2", "brief_missed", "new", T)
    assert await told.count(UID) == 2
    assert await told.sweep(T) == 1
    assert await told.count(UID) == 1
