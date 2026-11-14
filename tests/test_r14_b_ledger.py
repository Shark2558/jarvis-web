# tests/test_r14_b_ledger.py -- R14 Part B (docs/plans/r14-hardening.md D5, review A6): the job
# ledger (failed or timed-out runs in a row; a skip never counts; once per streak) and the
# once-only claims (`selfwatch_told`, written before the send).
from __future__ import annotations

import asyncio
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
    assert not book.recovered()
    book.observe("b", "ok", T)
    assert book.recovered() and book.recovered()  # until its all-clear is said
    book.clear_recovered()
    assert not book.recovered() and not book.has_told()


def test_an_untold_streak_ending_is_no_recovery() -> None:
    book = JobLedger()
    _fail(book, "a", 3)
    book.observe("a", "ok", T)
    assert not book.recovered()


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
    assert await book.flush(BrokenDocs()) is False  # unread: never written over the stored one
    await book.load(BrokenDocs())  # logged, never raised: the ledger keeps what it saw
    assert book.untold(3) == ["a"] and book.dirty


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


# ---- review follow-ups (v14.0.2) -----------------------------------------------------------------
async def test_a_naive_stored_time_reads_as_unknown_never_as_a_time() -> None:
    docs = MemoryDocs()
    docs._data["jarvis_selfwatch/jobs"] = {  # noqa: SLF001 - a hand-edited document
        "jobs": {"web": {"runs": 3, "since": "2026-11-16T06:00:00", "told_at": None}},
        "last_alert": "2026-11-16T06:00:00",
    }
    book = JobLedger()
    await book.load(docs)
    assert book.last_alert is None and book.failing(1) == []  # python review M1


async def test_a_naive_claim_time_is_swept_not_a_crash() -> None:
    docs = MemoryDocs()
    docs._data["jarvis_selfwatch_told/owner-1_abc"] = {"uid": UID, "at": "2026-11-16T06:00:00"}  # noqa: SLF001
    assert await Told(docs).sweep(T) == 1


class _WriteWhileObserving(MemoryDocs):
    """A store whose write lets the other job's observer run meanwhile (python review M2)."""

    def __init__(self, book: JobLedger) -> None:
        super().__init__()
        self.book = book

    async def write(self, ops):  # type: ignore[no-untyped-def]
        self.book.observe("late_job", "failed", T)  # the other clock, during the await
        await super().write(ops)


async def test_a_change_made_while_the_ledger_is_written_stays_to_write() -> None:
    book = JobLedger()
    _fail(book, "web", 1)
    docs = _WriteWhileObserving(book)
    assert await book.flush(docs) is True
    assert book.dirty  # the late change is still to be written
    assert await book.flush(docs) is True
    stored = await docs.get("jarvis_selfwatch/jobs")
    assert stored is not None and "late_job" in stored["jobs"]


async def test_a_write_that_fails_keeps_the_ledger_to_write() -> None:
    book = JobLedger()
    await book.load(MemoryDocs())
    _fail(book, "web", 1)
    with pytest.raises(RuntimeError):
        await book.flush(BrokenDocs())
    assert book.dirty


async def test_failures_seen_before_the_load_join_the_stored_streak() -> None:
    docs = MemoryDocs()
    old = JobLedger()
    _fail(old, "memory", 2)
    old.mark_told(["memory"], T)
    _fail(old, "web", 2)
    await old.flush(docs)
    fresh = JobLedger()  # a restart: one more failure of each before the first load
    fresh.observe("memory", "failed", T + timedelta(hours=1))
    fresh.observe("web", "failed", T + timedelta(hours=1))
    await fresh.load(docs)
    got = dict(fresh.failing(1))
    assert got["web"] == Streak(3, T)  # silent review M5: 2 stored + 1 seen, since kept
    assert got["memory"].runs == 3 and got["memory"].told_at == T  # told: never told again
    assert fresh.untold(3) == ["web"]


async def test_a_streak_that_ended_here_and_began_again_is_this_processs_own() -> None:
    docs = MemoryDocs()
    old = JobLedger()
    _fail(old, "web", 2)
    await old.flush(docs)
    fresh = JobLedger()
    fresh.observe("web", "ok", T)
    fresh.observe("web", "failed", T + timedelta(minutes=5))
    await fresh.load(docs)
    assert dict(fresh.failing(1))["web"] == Streak(1, T + timedelta(minutes=5))


async def test_skips_before_the_load_never_hide_the_stored_streak() -> None:
    docs = MemoryDocs()
    old = JobLedger()
    _fail(old, "web", 2)
    await old.flush(docs)
    fresh = JobLedger()
    fresh.observe("web", "skipped", T)
    await fresh.load(docs)
    assert dict(fresh.failing(1))["web"] == Streak(2, T)


async def test_the_ledger_is_never_written_over_a_stored_one_it_could_not_read() -> None:
    docs = MemoryDocs()
    old = JobLedger()
    _fail(old, "web", 2)
    await old.flush(docs)
    fresh = JobLedger()
    await fresh.load(BrokenDocs())  # the first read failed
    _fail(fresh, "web", 1)
    assert await fresh.flush(docs) is True  # it reads (and joins) the stored one first
    assert dict(fresh.failing(1))["web"].runs == 3


async def test_a_released_claim_can_be_made_again() -> None:
    docs = MemoryDocs()
    told = Told(docs)
    assert await told.claim(UID, "job_failing", "c", T)
    await told.release(UID, "job_failing", "c")
    assert await docs.query(Query("jarvis_selfwatch_told")) == []
    assert await told.claim(UID, "job_failing", "c", T)


class _NoDelete(MemoryDocs):
    async def write(self, ops):  # type: ignore[no-untyped-def]
        raise RuntimeError("firestore: 503")


async def test_a_claim_whose_delete_failed_is_still_released_in_this_process() -> None:
    docs = _NoDelete()
    told = Told(docs)
    assert await told.claim(UID, "job_failing", "c", T)
    await told.release(UID, "job_failing", "c")  # logged, never raised
    assert len(await docs.query(Query("jarvis_selfwatch_told"))) == 1  # still stored
    assert await told.claim(UID, "job_failing", "c", T)  # but made again here
    assert not await told.claim(UID, "job_failing", "c", T)


class _SlowBroken(BrokenDocs):
    async def transaction(self, fn):  # type: ignore[no-untyped-def]
        await asyncio.sleep(0)  # the other claim runs meanwhile
        raise self._down()


async def test_two_claims_at_once_with_the_store_down_make_one() -> None:
    told = Told(_SlowBroken())
    got = await asyncio.gather(*(told.claim(UID, "job_failing", "c", T) for _ in range(3)))
    assert sorted(got) == [False, False, True]  # python review L4


class _SlowDocs(MemoryDocs):
    async def transaction(self, fn):  # type: ignore[no-untyped-def]
        await asyncio.sleep(10)
        return await super().transaction(fn)


async def test_a_claim_cancelled_mid_transaction_is_not_kept() -> None:
    told = Told(_SlowDocs())
    with pytest.raises(TimeoutError):
        async with asyncio.timeout(0.01):
            await told.claim(UID, "job_failing", "c", T)
    told._docs = MemoryDocs()  # noqa: SLF001 - the store answers again
    assert await told.claim(UID, "job_failing", "c", T)


async def test_the_claims_kept_in_memory_are_bounded() -> None:
    told = Told(BrokenDocs())
    for i in range(ledger.MAX_MEMORY_CLAIMS + 10):
        await told.claim(UID, "job_failing", f"c{i}", T + timedelta(seconds=i))
    assert len(told._memory) <= ledger.MAX_MEMORY_CLAIMS  # noqa: SLF001
    assert not await told.claim(UID, "job_failing", f"c{ledger.MAX_MEMORY_CLAIMS + 9}", T)
