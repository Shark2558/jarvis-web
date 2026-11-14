# tests/test_r14_b_errors.py -- R14 Part B (D5): the errors handler counts ERROR records by hour
# and by logger name only, never its own records, never the notifier's or Telegram's while a
# self-health alert is being sent, never fails out loud, and writes its counts batched.
from __future__ import annotations

import logging
from datetime import timedelta
from zoneinfo import ZoneInfo

import pytest
from r14_fakes_b import NOON, BrokenDocs

from jarvis.selfwatch import errors
from jarvis.selfwatch.errors import ErrorCounter
from jarvis.selfwatch.ports import SENDING
from jarvis.storage.docs import MemoryDocs

IST = ZoneInfo("Asia/Kolkata")
DAY = "20261116"  # NOON is 12:00 IST on 16 Nov


def _record(name: str, level: int = logging.ERROR, at: float | None = None) -> logging.LogRecord:
    rec = logging.LogRecord(name, level, __file__, 1, "secret words %s", ("x",), None)
    if at is not None:
        rec.created = at
    return rec


def _emit(h: ErrorCounter, name: str, n: int = 1, at: float | None = None) -> None:
    for _ in range(n):
        h.handle(_record(name, at=NOON.timestamp() if at is None else at))


def test_it_listens_for_errors_only() -> None:
    h = ErrorCounter(tz=IST)
    assert h.level == logging.ERROR
    h.handle(_record("jarvis.vault", logging.WARNING))
    _emit(h, "jarvis.vault", 2)
    _emit(h, "uvicorn.error")
    assert h.pending() == {
        DAY: {"hours": {"12": 3}, "loggers": {"jarvis.vault": 2, "uvicorn.error": 1}}
    }


def test_its_own_records_never_count() -> None:
    h = ErrorCounter(tz=IST)
    _emit(h, "jarvis.selfwatch.jobs", 5)
    assert h.pending() == {}


def test_the_notifier_and_telegram_are_left_out_only_while_an_alert_is_sent() -> None:
    h = ErrorCounter(tz=IST)
    token = SENDING.set(True)
    try:
        _emit(h, "jarvis.notify.service")
        _emit(h, "jarvis.telegram.bot")
        _emit(h, "jarvis.vault")  # not quiet: counted even while sending
    finally:
        SENDING.reset(token)
    _emit(h, "jarvis.notify.service")  # not sending: counted
    assert h.pending()[DAY]["loggers"] == {"jarvis.vault": 1, "jarvis.notify.service": 1}


def test_odd_logger_names_and_the_fifty_first_name_go_to_other() -> None:
    h = ErrorCounter(tz=IST)
    _emit(h, "has spaces/and slashes")
    for i in range(errors.MAX_NAMES + 3):
        _emit(h, f"pkg.m{i}")
    got = h.pending()[DAY]
    assert len(got["loggers"]) == errors.MAX_NAMES and got["other"] == 4


def test_a_broken_record_never_raises_and_never_logs(caplog: pytest.LogCaptureFixture) -> None:
    h = ErrorCounter(tz=IST)
    rec = _record("jarvis.vault")
    rec.created = float("nan")
    h.handle(rec)  # must not raise
    assert h.broken and not caplog.records
    h.handleError(rec)  # the stdlib's "print a traceback" is switched off too
    assert h.unrecorded == 2  # silent review L1: counted, so the job and the status can say so
    assert h.new_unrecorded() == 2 and h.new_unrecorded() == 0


async def test_counts_are_written_batched_and_merged_per_day() -> None:
    docs = MemoryDocs()
    h = ErrorCounter(tz=IST)
    _emit(h, "jarvis.vault", 2)
    merged = await h.write_counts(docs)
    _emit(h, "jarvis.vault", 3)
    _emit(h, "jarvis.web", 1, at=(NOON + timedelta(hours=1)).timestamp())
    merged = await h.write_counts(docs)
    assert merged[DAY]["hours"] == {"12": 5, "13": 1}
    assert merged[DAY]["loggers"] == {"jarvis.vault": 5, "jarvis.web": 1}
    assert h.pending() == {} and await h.write_counts(docs) == {}
    stored = await docs.get(f"jarvis_selfwatch_errors/{DAY}")
    assert stored is not None and "secret" not in str(stored)


async def test_counts_survive_a_store_that_is_down() -> None:
    h = ErrorCounter(tz=IST)
    _emit(h, "jarvis.vault", 2)
    with pytest.raises(RuntimeError):
        await h.write_counts(BrokenDocs())
    assert h.pending()[DAY]["hours"] == {"12": 2}
    merged = await h.write_counts(MemoryDocs())
    assert merged[DAY]["hours"] == {"12": 2}


def test_more_than_the_threshold_in_one_hour_is_piling() -> None:
    assert errors.worst_hour({"hours": {"07": 30, "08": 12}}) == 30
    assert not errors.over({"hours": {"07": 30}}, 30)
    assert errors.over({"hours": {"07": 31}}, 30)
    assert not errors.over({}, 30) and not errors.over({"hours": {"07": "x"}}, 30)


async def test_today_counts_the_stored_and_the_pending() -> None:
    docs = MemoryDocs()
    h = ErrorCounter(tz=IST)
    _emit(h, "jarvis.vault", 2)
    await h.write_counts(docs)
    _emit(h, "jarvis.vault", 1)
    assert await h.today(docs, NOON) == 3


async def test_days_older_than_14_are_swept() -> None:
    docs = MemoryDocs()
    h = ErrorCounter(tz=IST)
    for back in (0, 13, 15, 40):
        _emit(h, "jarvis.vault", 1, at=(NOON - timedelta(days=back)).timestamp())
    await h.write_counts(docs)
    assert await h.sweep(docs, NOON) == 2
    assert await h.sweep(docs, NOON) == 0


def test_the_stdlib_flush_and_close_stay_harmless() -> None:
    h = ErrorCounter(tz=IST)  # logging.shutdown calls both at exit
    _emit(h, "jarvis.vault")
    h.flush()
    h.close()
    assert h.pending()[DAY]["hours"] == {"12": 1}


def test_only_its_own_package_is_left_out_never_a_lookalike() -> None:
    h = ErrorCounter(tz=IST)  # python review L2
    _emit(h, "jarvis.selfwatch")
    _emit(h, "jarvis.selfwatchfoo")
    token = SENDING.set(True)
    try:
        _emit(h, "jarvis.notify")
        _emit(h, "jarvis.notifyx")
    finally:
        SENDING.reset(token)
    assert h.pending()[DAY]["loggers"] == {"jarvis.selfwatchfoo": 1, "jarvis.notifyx": 1}


def test_the_hot_hours_are_those_over_the_limit() -> None:
    assert errors.hot_hours({"hours": {"07": 31, "08": 30, "09": "x"}}, 30) == {"07"}
    assert errors.hot_hours({}, 30) == set()


def test_a_pile_seen_during_a_told_incident_is_never_owed_and_others_are() -> None:
    piles = errors.Piles()
    piles.see({DAY: {"hours": {"07": 40}}}, 30, held=True)  # the incident's own errors
    piles.see({DAY: {"hours": {"07": 45}}}, 30, held=False)  # the same hour, after it
    assert piles.owed() == []
    piles.see({DAY: {"hours": {"07": 45, "09": 31}}}, 30, held=False)  # a new hour piles up
    assert piles.owed() == [DAY]
    piles.settle(DAY)
    assert piles.owed() == []


def test_the_piles_remember_a_week_at_most() -> None:
    piles = errors.Piles()
    for d in range(1, 20):
        piles.see({f"202611{d:02d}": {"hours": {"07": 40}}}, 30, held=d % 2 == 0)
    assert len(piles.owed()) <= errors.MAX_PENDING_DAYS
    assert piles.owed()[-1] == "20261119"
