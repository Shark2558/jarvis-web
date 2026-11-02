# tests/test_quota_ledger.py — slice 12 D2: the deployment-wide allowance ledger for Google's
# free tiers. Per-SKU counters on the Docs port, Pacific-time months (Maps) and days (YouTube),
# reserve in a transaction, refund when the call never reached Google, latch when Google says the
# quota is gone, fail closed on a corrupt counter, and the 90 % stops from the plan.
from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import pytest

from jarvis.quota.ledger import (
    MAPS_GEOCODE,
    MAPS_ROUTE,
    MAPS_SEARCH,
    SKUS,
    YOUTUBE_SEARCH,
    YOUTUBE_UNITS,
    HourlyCounter,
    QuotaLedger,
    QuotaReached,
    QuotaUnreadable,
)
from jarvis.storage.docs import MemoryDocs, Set

# 2026-11-01 05:30 UTC is still 31 October in California (PDT, UTC-7) — and 1 November in India
EDGE = datetime(2026, 11, 1, 5, 30, tzinfo=UTC)
NOW = datetime(2026, 11, 15, 12, 0, tzinfo=UTC)


def _ledger(docs: MemoryDocs | None = None, now: datetime = NOW) -> QuotaLedger:
    return QuotaLedger(docs or MemoryDocs(), now=lambda: now)


def test_the_stops_are_ninety_percent_of_googles_free_allowances() -> None:
    assert MAPS_SEARCH.cap == 31_500 and MAPS_SEARCH.period == "month"
    assert MAPS_ROUTE.cap == 31_500 and MAPS_ROUTE.period == "month"
    assert MAPS_GEOCODE.cap == 63_000 and MAPS_GEOCODE.period == "month"
    assert YOUTUBE_SEARCH.cap == 90 and YOUTUBE_SEARCH.period == "day"
    assert YOUTUBE_UNITS.cap == 9_000 and YOUTUBE_UNITS.period == "day"
    assert set(SKUS) == {
        "maps_search",
        "maps_route",
        "maps_geocode",
        "youtube_search",
        "youtube_units",
    }


def test_periods_follow_pacific_time_as_google_bills_and_resets() -> None:
    led = _ledger(now=EDGE)
    assert led.period_key(MAPS_SEARCH) == "2026-10"
    assert led.period_key(YOUTUBE_SEARCH) == "2026-10-31"
    assert led.tz_name == "America/Los_Angeles"


async def test_reserve_counts_and_stores_one_document_per_sku_and_period() -> None:
    docs = MemoryDocs()
    led = _ledger(docs)
    r = await led.reserve(MAPS_SEARCH)
    await led.reserve(MAPS_SEARCH)
    await led.reserve(YOUTUBE_UNITS, 2)
    assert r.sku is MAPS_SEARCH and r.n == 1 and r.period == "2026-11"
    assert (await led.use(MAPS_SEARCH)).used == 2
    assert (await led.use(YOUTUBE_UNITS)).used == 2
    stored = await docs.get("jarvis_api_quota/maps_search@2026-11")
    assert stored is not None and stored["used"] == 2 and stored["tz"] == "America/Los_Angeles"
    assert await docs.get("jarvis_api_quota/youtube_units@2026-11-15") is not None


async def test_reaching_the_stop_refuses_in_plain_words_and_takes_nothing() -> None:
    led = _ledger()
    for _ in range(YOUTUBE_SEARCH.cap):
        await led.reserve(YOUTUBE_SEARCH)
    with pytest.raises(QuotaReached) as exc:
        await led.reserve(YOUTUBE_SEARCH)
    msg = str(exc.value)
    assert "90" in msg and "YouTube" in msg and "$" not in msg and "₹" not in msg
    assert (await led.use(YOUTUBE_SEARCH)).used == 90


async def test_a_multi_unit_reservation_that_would_pass_the_stop_is_refused_whole() -> None:
    led = _ledger()
    for _ in range(4):
        await led.reserve(YOUTUBE_UNITS, 2_000)
    with pytest.raises(QuotaReached):
        await led.reserve(YOUTUBE_UNITS, 1_001)
    assert (await led.use(YOUTUBE_UNITS)).used == 8_000


async def test_two_calls_racing_for_the_last_one_cannot_both_get_it() -> None:
    docs = MemoryDocs()
    led = _ledger(docs)
    await docs.write([Set("jarvis_api_quota/youtube_search@2026-11-15", {"used": 89})])
    results = await asyncio.gather(
        led.reserve(YOUTUBE_SEARCH), led.reserve(YOUTUBE_SEARCH), return_exceptions=True
    )
    assert sum(isinstance(r, QuotaReached) for r in results) == 1
    assert (await led.use(YOUTUBE_SEARCH)).used == 90


async def test_refund_gives_a_clear_failure_back_never_below_zero() -> None:
    led = _ledger()
    r = await led.reserve(MAPS_ROUTE)
    await led.refund(r)
    assert (await led.use(MAPS_ROUTE)).used == 0
    await led.refund(r)  # twice: still 0
    assert (await led.use(MAPS_ROUTE)).used == 0


async def test_latch_marks_the_period_used_up_when_google_says_so() -> None:
    led = _ledger()
    await led.reserve(YOUTUBE_UNITS, 3)
    await led.latch(YOUTUBE_UNITS)
    use = await led.use(YOUTUBE_UNITS)
    assert use.used == YOUTUBE_UNITS.cap and use.left == 0 and use.reached
    with pytest.raises(QuotaReached):
        await led.reserve(YOUTUBE_UNITS)


@pytest.mark.parametrize(
    "stored",
    [
        {"used": -1},
        {"used": 1.5},
        {"used": "12"},
        {"used": True},
        {"used": float("nan")},
        {"used": float("inf")},
        {"used": None},
        "not a document",
    ],
)
async def test_a_corrupt_counter_fails_closed_and_is_never_reset(stored: object) -> None:
    docs = MemoryDocs()
    docs._data["jarvis_api_quota/maps_search@2026-11"] = stored  # type: ignore[assignment]
    led = _ledger(docs)
    with pytest.raises(QuotaUnreadable):
        await led.reserve(MAPS_SEARCH)
    with pytest.raises(QuotaUnreadable):
        await led.use(MAPS_SEARCH)
    assert docs._data["jarvis_api_quota/maps_search@2026-11"] == stored  # untouched


async def test_a_missing_used_field_reads_as_zero_but_other_skus_are_independent() -> None:
    docs = MemoryDocs()
    docs._data["jarvis_api_quota/maps_search@2026-11"] = {"used": "bad"}
    led = _ledger(docs)
    await led.reserve(MAPS_ROUTE)  # a corrupt search counter does not stop routes
    docs._data["jarvis_api_quota/maps_geocode@2026-11"] = {}
    assert (await led.use(MAPS_GEOCODE)).used == 0


async def test_refund_and_latch_never_raise_on_a_store_error() -> None:
    class Broken(MemoryDocs):
        async def transaction(self, fn):  # type: ignore[no-untyped-def,override]
            raise RuntimeError("store down")

    led = QuotaLedger(Broken(), now=lambda: NOW)
    from jarvis.quota.ledger import Reservation

    await led.refund(Reservation(MAPS_SEARCH, "2026-11", 1))
    await led.latch(MAPS_SEARCH)


async def test_view_lists_every_sku_and_says_unreadable_instead_of_zero() -> None:
    docs = MemoryDocs()
    led = _ledger(docs)
    await led.reserve(MAPS_SEARCH)
    docs._data["jarvis_api_quota/youtube_search@2026-11-15"] = {"used": -4}
    view = await led.view()
    assert view["maps_search"] == {
        "period": "2026-11",
        "used": 1,
        "limit": 31_500,
        "left": 31_499,
        "reached": False,
        "unreadable": False,
    }
    assert view["youtube_search"]["unreadable"] is True and view["youtube_search"]["used"] is None
    assert set(view) == set(SKUS)


def test_hourly_counter_forgets_calls_older_than_an_hour_per_owner() -> None:
    t = [1_000.0]
    c = HourlyCounter(clock=lambda: t[0])
    for _ in range(3):
        c.count("u1")
    c.count("u2")
    assert c.last_hour("u1") == 3 and c.last_hour("u2") == 1
    t[0] += 3_600
    assert c.last_hour("u1") == 0
