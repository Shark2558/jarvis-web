# tests/test_r14_b_clocks.py -- R14 Part B (D5): the two clocks watch each other. The morning
# tick says when the 5-minute watchdog has not run for 20 minutes; the watchdog says when no
# tick ran by 05:00; each once per outage, and the other clock says when it is back.
from __future__ import annotations

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from r14_fakes_b import BrokenDocs

from jarvis.selfwatch.clocks import (
    Clocks,
    ClockState,
    on_tick,
    on_watchdog,
    tick_missing,
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
