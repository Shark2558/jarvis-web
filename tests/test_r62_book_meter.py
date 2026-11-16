# tests/test_r62_book_meter.py -- R6.2 round 3 (review 3): the free-allowance HOLD, tested directly
# (it was covered only through VoiceService). `UsageMeter.reserve_units` / `release_units` and
# `Billing.reserve_free` / `release_free`: a normal hold, a release, the free limit, fail closed
# when the counter is unreadable, never below zero, a second release a no-op, and a hold that
# remembers its month (a hold made on the last day is given back to that month, not the new one).
from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
from billing_fakes import NOW, BrokenDocs, Clock, billing, put_raw, registry

from jarvis.billing.meter import UsageMeter, UsageUnreadable
from jarvis.billing.service import BudgetUnavailable, FreeAllowanceUsed
from jarvis.storage.docs import MemoryDocs

KEY = "stt_v2_seconds"
FREE = 60.0
MONTH = "2026-11"  # NOW is 15 Nov 2026
PACIFIC = ZoneInfo("America/Los_Angeles")


def _meter(docs: MemoryDocs | None = None) -> UsageMeter:
    return UsageMeter(docs or MemoryDocs())


async def _used(m: UsageMeter, month: str = MONTH) -> float:
    return (await m.allowance(month)).used(KEY)


async def _hold(m: UsageMeter, units: float, now: datetime = NOW):  # type: ignore[no-untyped-def]
    return await m.reserve_units(key=KEY, units=units, free_units=FREE, now=now)


# ---- the meter -----------------------------------------------------------------------------------
async def test_a_hold_counts_at_once_and_says_what_it_holds() -> None:
    m = _meter()
    hold = await _hold(m, 15.0)
    assert hold is not None and (hold.key, hold.units, hold.month) == (KEY, 15.0, MONTH)
    assert await _used(m) == 15.0


async def test_a_release_leaves_exactly_the_count_before_the_hold() -> None:
    m = _meter()
    await _hold(m, 5.0)
    hold = await _hold(m, 15.0)
    assert hold is not None and await _used(m) == 20.0
    await m.release_units(hold, now=NOW)
    assert await _used(m) == 5.0


async def test_a_hold_fits_exactly_up_to_the_free_limit_and_not_a_unit_past_it() -> None:
    m = _meter()
    assert await _hold(m, 45.0) is not None
    assert await _hold(m, 15.0) is not None and await _used(m) == FREE  # exactly full
    assert await _hold(m, 0.001) is None and await _used(m) == FREE  # refused, nothing written


async def test_a_hold_that_does_not_fit_writes_nothing() -> None:
    docs = MemoryDocs()
    m = _meter(docs)
    await _hold(m, 50.0)
    before = await docs.get(f"jarvis_allowance/{MONTH}")
    assert await _hold(m, 15.0) is None
    assert await docs.get(f"jarvis_allowance/{MONTH}") == before


async def test_an_unreadable_counter_fails_closed_and_writes_nothing() -> None:
    docs = MemoryDocs()
    bad = {"month": MONTH, "units": {KEY: "lots"}}
    await put_raw(docs, f"jarvis_allowance/{MONTH}", bad)
    with pytest.raises(UsageUnreadable):
        await _hold(_meter(docs), 15.0)
    assert await docs.get(f"jarvis_allowance/{MONTH}") == bad


async def test_a_release_never_takes_the_count_below_zero() -> None:
    docs = MemoryDocs()
    m = _meter(docs)
    hold = await _hold(m, 15.0)
    assert hold is not None
    # the counter drops behind the hold's back (a month reset, a hand edit): 15 asked, 5 there
    await put_raw(docs, f"jarvis_allowance/{MONTH}", {"month": MONTH, "units": {KEY: 5.0}})
    await m.release_units(hold, now=NOW)
    assert await _used(m) == 0.0


async def test_releasing_where_nothing_is_counted_leaves_zero() -> None:
    docs = MemoryDocs()
    m = _meter(docs)
    hold = await _hold(m, 15.0)
    assert hold is not None
    await put_raw(docs, f"jarvis_allowance/{MONTH}", {"month": MONTH, "units": {}})
    await m.release_units(hold, now=NOW)
    assert await _used(m) == 0.0


async def test_a_second_release_of_the_same_hold_is_a_no_op() -> None:
    m = _meter()
    await _hold(m, 20.0)
    hold = await _hold(m, 15.0)
    assert hold is not None
    await m.release_units(hold, now=NOW)
    await m.release_units(hold, now=NOW)  # must not take the other 20 s away
    assert await _used(m) == 20.0


async def test_a_release_that_could_not_be_written_can_be_tried_again() -> None:
    docs = BrokenDocs()
    m = _meter(docs)
    hold = await _hold(m, 15.0)
    assert hold is not None
    docs.fail_tx = True
    with pytest.raises(RuntimeError):
        await m.release_units(hold, now=NOW)
    docs.fail_tx = False
    await m.release_units(hold, now=NOW)
    assert await _used(m) == 0.0


# ---- month drift: a hold goes back to the month it was made in -----------------------------------
async def test_a_hold_made_on_the_last_day_is_given_back_to_that_month() -> None:
    m = _meter()
    last = datetime(2026, 11, 30, 23, 59, tzinfo=PACIFIC)
    first = datetime(2026, 12, 1, 0, 1, tzinfo=PACIFIC)
    await _hold(m, 10.0, now=first)  # December's own use, made after the rollover
    hold = await _hold(m, 15.0, now=last)
    assert hold is not None and hold.month == "2026-11"
    await m.release_units(hold, now=NOW)  # the call failed after midnight
    assert await _used(m, "2026-11") == 0.0
    assert await _used(m, "2026-12") == 10.0  # December's use is untouched


# ---- Billing -------------------------------------------------------------------------------------
async def test_billing_holds_and_releases_through_the_meter() -> None:
    b = billing(registry())
    hold = await b.reserve_free(key=KEY, units=15.0, free_units=FREE)
    assert (await b.allowance((KEY,))).used(KEY) == 15.0
    await b.release_free(hold)
    assert (await b.allowance((KEY,))).used(KEY) == 0.0


async def test_billing_refuses_a_hold_past_the_free_limit() -> None:
    b = billing(registry())
    await b.reserve_free(key=KEY, units=50.0, free_units=FREE)
    with pytest.raises(FreeAllowanceUsed):
        await b.reserve_free(key=KEY, units=15.0, free_units=FREE)
    assert (await b.allowance((KEY,))).used(KEY) == 50.0


@pytest.mark.parametrize("storage_down", [False, True])
async def test_billing_fails_closed_when_the_counter_is_unreadable(storage_down: bool) -> None:
    docs = BrokenDocs()
    await put_raw(docs, f"jarvis_allowance/{MONTH}", {"month": MONTH, "units": {KEY: "x"}})
    docs.fail_tx = storage_down  # a corrupted counter, or storage itself down
    with pytest.raises(BudgetUnavailable):
        await billing(registry(), docs=docs).reserve_free(key=KEY, units=15.0, free_units=FREE)


async def test_billing_release_never_raises_even_when_storage_is_down() -> None:
    docs = BrokenDocs()
    b = billing(registry(), docs=docs)
    hold = await b.reserve_free(key=KEY, units=15.0, free_units=FREE)
    docs.fail_tx = True
    await b.release_free(hold)  # answers nothing, raises nothing
    docs.fail_tx = False
    assert (await b.allowance((KEY,))).used(KEY) == 15.0  # the safe side: still counted


async def test_billing_gives_a_hold_back_to_its_month_after_the_rollover() -> None:
    clock = Clock(datetime(2026, 11, 30, 23, 59, tzinfo=PACIFIC))
    b = billing(registry(), clock=clock)
    hold = await b.reserve_free(key=KEY, units=15.0, free_units=FREE)
    clock.at = datetime(2026, 12, 1, 0, 2, tzinfo=PACIFIC)
    await b.release_free(hold)
    assert (await b.meter.allowance("2026-11")).used(KEY) == 0.0
    assert (await b.allowance((KEY,))).used(KEY) == 0.0  # December, never touched
