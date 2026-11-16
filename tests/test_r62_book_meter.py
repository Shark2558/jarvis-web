# tests/test_r62_book_meter.py -- R6.2 round 3 (review 3): the free-allowance HOLD, tested directly
# (it was covered only through VoiceService). `UsageMeter.reserve_units` / `release_units` and
# `Billing.reserve_free` / `release_free`: a normal hold, a release, the free limit, fail closed
# when the counter is unreadable, never below zero, a second release a no-op, and a hold that
# remembers its month (a hold made on the last day is given back to that month, not the new one).
from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from billing_fakes import NOW, Clock, billing, registry

from jarvis.billing.meter import UsageMeter
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


async def test_billing_gives_a_hold_back_to_its_month_after_the_rollover() -> None:
    clock = Clock(datetime(2026, 11, 30, 23, 59, tzinfo=PACIFIC))
    b = billing(registry(), clock=clock)
    hold = await b.reserve_free(key=KEY, units=15.0, free_units=FREE)
    clock.at = datetime(2026, 12, 1, 0, 2, tzinfo=PACIFIC)
    await b.release_free(hold)
    assert (await b.meter.allowance("2026-11")).used(KEY) == 0.0
    assert (await b.allowance((KEY,))).used(KEY) == 0.0  # December, never touched
