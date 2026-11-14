# tests/test_r14_b_clocks.py -- R14 Part B (D5): the two clocks watch each other. The morning
# tick says when the 5-minute watchdog has not run for 20 minutes; the watchdog says when no
# tick ran by 05:00; each once per outage, and the other clock says when it is back.
from __future__ import annotations

import logging
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import pytest
from r14_fakes_b import BrokenDocs, build_world

from jarvis.selfwatch import texts
from jarvis.selfwatch.clocks import (
    FRESH,
    Clocks,
    ClockState,
    on_tick,
    on_watchdog,
    tick_missing,
    undo,
    watchdog_stopped,
)
from jarvis.storage.docs import MemoryDocs

IST = ZoneInfo("Asia/Kolkata")


def ist(day: int, hh: int, mm: int = 0) -> datetime:
    return datetime(2026, 11, day, hh, mm, tzinfo=IST).astimezone(UTC)


def test_the_watchdog_is_stopped_after_20_minutes_unseen() -> None:
    s = ClockState(watchdog=ist(16, 7, 0))
    assert watchdog_stopped(s, ist(16, 7, 20)) is None
    assert watchdog_stopped(s, ist(16, 7, 21)) == ist(16, 7, 0)
    assert watchdog_stopped(ClockState(), ist(16, 7, 30)) is None  # never seen: no baseline


def test_no_tick_by_five_is_missing_once_a_baseline_exists() -> None:
    yesterday = ClockState(tick=ist(15, 11, 30))
    assert tick_missing(yesterday, ist(16, 4, 59), IST) is None
    assert tick_missing(yesterday, ist(16, 5, 0), IST) == "2026-11-16"
    assert tick_missing(ClockState(tick=ist(16, 4, 0)), ist(16, 5, 5), IST) is None
    assert tick_missing(ClockState(), ist(16, 14, 0), IST) is None  # a fresh install at 14:00


def test_the_watchdog_tells_a_missing_tick_once_per_outage() -> None:
    s = ClockState(tick=ist(15, 11, 30), watchdog=ist(16, 4, 55))
    s, events = on_watchdog(s, ist(16, 5, 0), IST)
    assert [(e.kind, e.clock, e.at) for e in events] == [("clock_stopped", "tick", "05:00")]
    assert s.tick_outage == "2026-11-16" and s.watchdog == ist(16, 5, 0)
    s, again = on_watchdog(s, ist(16, 5, 5), IST)
    s, next_day = on_watchdog(s, ist(17, 5, 5), IST)
    assert again == [] and next_day == []  # one outage, told once


def test_the_tick_is_back_tells_once_and_clears_the_outage() -> None:
    s = ClockState(tick=ist(15, 11, 30), watchdog=ist(16, 9, 0), tick_outage="2026-11-16")
    s, events = on_tick(s, ist(16, 9, 0), IST)
    assert [(e.kind, e.clock) for e in events] == [("selfwatch_ok", "tick")]
    assert s.tick_outage is None and s.tick == ist(16, 9, 0)


def test_the_tick_tells_a_stopped_watchdog_once_and_the_watchdog_says_it_is_back() -> None:
    s = ClockState(tick=ist(16, 7, 0), watchdog=ist(16, 7, 5))
    s, events = on_tick(s, ist(16, 7, 30), IST)
    assert [(e.kind, e.clock, e.at) for e in events] == [("clock_stopped", "watchdog", "07:05")]
    s, again = on_tick(s, ist(16, 8, 0), IST)
    assert again == []
    s, back = on_watchdog(s, ist(16, 8, 3), IST)
    assert [(e.kind, e.clock) for e in back] == [("selfwatch_ok", "watchdog")]
    assert s.watchdog_outage is None
    assert len({e.cause for e in (*events, *back)}) == 2


async def test_both_clocks_stamps_are_kept_side_by_side() -> None:
    docs = MemoryDocs()
    tick, dog = Clocks(), Clocks()  # two processes (an overlap during a deploy)
    await tick.update(docs, lambda s: on_tick(s, ist(16, 7, 0), IST)[0])
    await dog.update(docs, lambda s: on_watchdog(s, ist(16, 7, 2), IST)[0])
    got = await Clocks().read(docs)
    assert (got.tick, got.watchdog) == (ist(16, 7, 0), ist(16, 7, 2))


async def test_the_observer_stamps_reach_the_store_on_the_next_update() -> None:
    docs = MemoryDocs()
    c = Clocks()
    c.seen("tick", ist(16, 7, 0))  # any tick outcome proves the tick ran
    c.seen("elsewhere", ist(16, 7, 0))  # not a clock: ignored
    state, ok = await c.update(docs, lambda s: s)
    assert ok and state.tick == ist(16, 7, 0) and state.watchdog is None


async def test_with_the_store_down_the_clocks_run_on_memory() -> None:
    c = Clocks()
    c.seen("watchdog", ist(16, 7, 0))
    state, ok = await c.update(BrokenDocs(), lambda s: on_tick(s, ist(16, 7, 30), IST)[0])
    assert not ok and state.watchdog_outage == ist(16, 7, 0) and state.tick == ist(16, 7, 30)
    assert (await c.read(BrokenDocs())).watchdog_outage == ist(16, 7, 0)


async def test_a_damaged_stored_document_reads_as_nothing_known() -> None:
    docs = MemoryDocs()
    await docs.write([])
    docs._data["jarvis_selfwatch/clocks"] = {"tick": "not a time", "watchdog": 7}  # noqa: SLF001
    got = await Clocks().read(docs)
    assert got == ClockState()


def test_an_event_that_reached_nobody_is_undone_and_raised_again() -> None:
    s = ClockState(tick=ist(15, 11, 30), watchdog=ist(16, 4, 55))
    after, (stopped,) = on_watchdog(s, ist(16, 5, 0), IST)
    s = undo(after, stopped)
    assert s.tick_outage is None
    _, again = on_watchdog(s, ist(16, 5, 5), IST)
    assert [e.cause for e in again] == [stopped.cause]  # the same outage, raised again
    dog = ClockState(tick=ist(16, 7, 0), watchdog=ist(16, 7, 5))
    after, (gone,) = on_tick(dog, ist(16, 7, 30), IST)
    assert undo(after, gone).watchdog_outage is None
    told, _ = on_tick(dog, ist(16, 7, 30), IST)
    after, (back,) = on_watchdog(told, ist(16, 8, 3), IST)
    restored = undo(after, back)
    assert restored.watchdog_outage == ist(16, 7, 5) and restored.watchdog == ist(16, 8, 3)
    _, (back_again,) = on_watchdog(restored, ist(16, 8, 8), IST)
    assert back_again.cause == back.cause
    tick_back = on_tick(ClockState(tick_outage="2026-11-16"), ist(16, 9, 0), IST)
    assert undo(tick_back[0], tick_back[1][0]).tick_outage == "2026-11-16"


def test_undo_never_touches_a_newer_outage() -> None:
    s = ClockState(tick_outage="2026-11-17")
    after, (e,) = on_watchdog(ClockState(tick=ist(15, 11, 30)), ist(16, 5, 0), IST)
    assert undo(s, e) == s  # another day's outage stays
    assert undo(ClockState(watchdog_outage=ist(16, 9, 0)), e) == ClockState(
        watchdog_outage=ist(16, 9, 0)
    )


# ---- a clock never seen (silent review M3, code review L1) ---------------------------------------
def test_a_morning_clock_never_seen_is_missing_at_its_first_five_oclock_an_hour_on() -> None:
    s = ClockState(watchdog=ist(16, 14, 0), first_seen=ist(16, 14, 0))  # installed at 14:00
    assert tick_missing(s, ist(16, 23, 0), IST) is None
    assert tick_missing(s, ist(17, 4, 59), IST) is None
    assert tick_missing(s, ist(17, 5, 0), IST) == "2026-11-17"
    late = ClockState(watchdog=ist(17, 4, 30), first_seen=ist(17, 4, 30))  # within its hour
    assert tick_missing(late, ist(17, 5, 0), IST) is None
    assert tick_missing(late, ist(18, 5, 0), IST) == "2026-11-18"
    assert FRESH.total_seconds() == 3600


def test_a_five_minute_clock_never_seen_is_stopped_an_hour_after_the_first_tick() -> None:
    s = ClockState(tick=ist(16, 4, 0), first_seen=ist(16, 4, 0))
    assert watchdog_stopped(s, ist(16, 5, 0)) is None
    assert watchdog_stopped(s, ist(16, 5, 1)) == ist(16, 4, 0)


def test_the_tick_says_a_never_seen_five_minute_clock_once_and_back() -> None:
    s, ev = on_tick(ClockState(), ist(16, 4, 0), IST)
    assert ev == [] and s.first_seen == ist(16, 4, 0)
    s, ev = on_tick(s, ist(16, 4, 30), IST)
    assert ev == []
    s, ev = on_tick(s, ist(16, 5, 30), IST)
    assert [(e.kind, e.clock, e.never) for e in ev] == [("clock_stopped", "watchdog", True)]
    s, again = on_tick(s, ist(16, 6, 0), IST)
    s, back = on_watchdog(s, ist(16, 6, 2), IST)
    assert again == [] and [e.kind for e in back] == ["selfwatch_ok"]


def test_the_never_seen_text_says_it_never_ran() -> None:
    text = texts.clock_stopped("watchdog", "04:00", never=True)
    assert "has not run at all since 04:00" in text and len(text) <= texts.MAX_TEXT


async def test_a_fresh_install_says_nothing_in_its_first_hour() -> None:
    w = build_world(now=ist(16, 14, 0))
    for _ in range(14):
        await w.watchdog()
        w.clock.advance(minutes=5)
    assert w.ring.sent == []


async def test_a_morning_clock_that_never_starts_after_a_deploy_is_said() -> None:
    w = build_world(now=ist(16, 14, 0))
    while w.clock() < ist(17, 5, 10):
        await w.watchdog()
        w.clock.advance(minutes=5)
    assert w.ring.kinds() == ["clock_stopped"]
    assert "did not run today by 05:00" in w.ring.sent[0].text


async def test_the_first_seen_is_kept_and_the_earliest_wins() -> None:
    docs = MemoryDocs()
    a, b = Clocks(), Clocks()
    await a.update(docs, lambda s: on_watchdog(s, ist(16, 7, 5), IST)[0])
    await b.update(docs, lambda s: on_tick(s, ist(16, 9, 0), IST)[0])
    assert (await Clocks().read(docs)).first_seen == ist(16, 7, 5)


class _SeenDuringWrite(MemoryDocs):
    def __init__(self, clocks: Clocks) -> None:
        super().__init__()
        self.clocks = clocks

    async def transaction(self, fn):  # type: ignore[no-untyped-def]
        got = await super().transaction(fn)
        self.clocks.seen("tick", ist(16, 7, 1))  # an observer stamp while the write was awaited
        return got


async def test_a_stamp_seen_during_the_update_is_kept() -> None:
    c = Clocks()
    state, ok = await c.update(_SeenDuringWrite(c), lambda s: on_watchdog(s, ist(16, 7, 0), IST)[0])
    assert ok and state.watchdog == ist(16, 7, 0)
    assert c.mine.tick == ist(16, 7, 1)  # python review L1: not overwritten by the older result


def test_a_damaged_stored_field_is_logged(caplog: pytest.LogCaptureFixture) -> None:
    from jarvis.selfwatch.clocks import decode

    caplog.set_level(logging.WARNING, logger="jarvis.selfwatch.clocks")
    assert decode({"tick": "2026-11-16T07:00:00", "watchdog": 7}) == ClockState()
    assert any("unreadable" in r.getMessage() for r in caplog.records)  # silent review L4
    caplog.clear()
    decode({})
    assert caplog.records == []
