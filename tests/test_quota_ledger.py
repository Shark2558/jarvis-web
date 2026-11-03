# tests/test_quota_ledger.py — slice 12 D2: the deployment-wide allowance ledger for Google's
# free tiers. Per-SKU counters on the Docs port, Pacific-time months (Maps) and days (YouTube),
# reserve in a transaction, refund when the call never reached Google, latch when Google says a
# per-day or per-month quota is gone (a per-day limit closes only that day), fail closed on a
# corrupt counter, and stops at 90 % of the free allowance of the billing account's price list
# (JARVIS_MAPS_PRICING: india or global, global by default — the safe low caps).
from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import pytest

from jarvis.quota.ledger import (
    MAPS_ROUTE,
    MAPS_ROUTE_2W,
    MAPS_ROUTE_WALK,
    MAPS_SEARCH,
    SKUS,
    YOUTUBE_SEARCH,
    YOUTUBE_UNITS,
    HourlyCounter,
    QuotaLedger,
    QuotaReached,
    QuotaUnreadable,
    Reservation,
    skus_for,
)
from jarvis.storage.docs import MemoryDocs, Set

# 2026-11-01 05:30 UTC is still 31 October in California (PDT, UTC-7) — and 1 November in India
EDGE = datetime(2026, 11, 1, 5, 30, tzinfo=UTC)
NOW = datetime(2026, 11, 15, 12, 0, tzinfo=UTC)
# one minute either side of midnight Pacific (PST, UTC-8) on 15/16 November
BEFORE_MIDNIGHT = datetime(2026, 11, 16, 7, 59, tzinfo=UTC)
AFTER_MIDNIGHT = datetime(2026, 11, 16, 8, 1, tzinfo=UTC)
# one minute either side of the Pacific month change, 30 November → 1 December
MONTH_END = datetime(2026, 12, 1, 7, 59, tzinfo=UTC)
NEXT_MONTH = datetime(2026, 12, 1, 8, 1, tzinfo=UTC)


class Clock:
    def __init__(self, at: datetime) -> None:
        self.at = at

    def __call__(self) -> datetime:
        return self.at


def _ledger(
    docs: MemoryDocs | None = None, now: datetime = NOW, pricing: str = "global"
) -> QuotaLedger:
    return QuotaLedger(docs or MemoryDocs(), now=lambda: now, pricing=pricing)  # type: ignore[arg-type]


def test_the_stops_are_ninety_percent_of_googles_free_allowances_per_price_list() -> None:
    """Google's price lists (checked 2026-11-03): India — Text Search Pro 35,000, Compute Routes
    Pro 35,000, Enterprise 7,000, Essentials 70,000 a month; everywhere else 5,000, 5,000, 1,000,
    10,000. YouTube: 100 searches and 10,000 units a day, whatever the billing country."""
    india, world = skus_for("india"), skus_for("global")
    assert {k: s.cap for k, s in india.items()} == {
        "maps_search": 31_500,
        "maps_route": 31_500,
        "maps_route_2w": 6_300,
        "maps_route_walk": 63_000,
        "youtube_search": 90,
        "youtube_units": 9_000,
    }
    assert {k: s.cap for k, s in world.items()} == {
        "maps_search": 4_500,
        "maps_route": 4_500,
        "maps_route_2w": 900,
        "maps_route_walk": 9_000,
        "youtube_search": 90,
        "youtube_units": 9_000,
    }
    assert {k: s.free for k, s in india.items() if k.startswith("maps")} == {
        "maps_search": 35_000,
        "maps_route": 35_000,
        "maps_route_2w": 7_000,
        "maps_route_walk": 70_000,
    }
    for table in (india, world):
        assert all(s.cap == s.free * 9 // 10 for s in table.values())
        assert {s.period for k, s in table.items() if k.startswith("maps")} == {"month"}
        assert table["youtube_search"].period == table["youtube_units"].period == "day"
    # the module's own constants and SKUS are the safe (global) ones
    assert SKUS == world
    assert MAPS_SEARCH.cap == 4_500 and MAPS_ROUTE_2W.cap == 900
    assert MAPS_ROUTE.cap == 4_500 and MAPS_ROUTE_WALK.cap == 9_000


def test_an_unknown_price_list_is_refused() -> None:
    with pytest.raises(ValueError):
        skus_for("mars")  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        QuotaLedger(MemoryDocs(), pricing="usa")  # type: ignore[arg-type]


@pytest.mark.parametrize("pricing", ["india", "global"])
def test_every_reached_message_is_built_from_its_own_cap(pricing: str) -> None:
    for sku in skus_for(pricing).values():  # type: ignore[arg-type]
        msg = sku.reached
        assert f"{sku.cap:,}" in msg and sku.label in msg
        assert "$" not in msg and "₹" not in msg
        other = 31_500 if sku.cap != 31_500 else 4_500
        assert f"{other:,}" not in msg


def test_the_ledger_uses_the_configured_price_list_whatever_constant_is_passed() -> None:
    led = _ledger(pricing="india")
    assert led.sku(MAPS_SEARCH).cap == 31_500  # MAPS_SEARCH itself is the global one
    assert led.sku("maps_route_2w").cap == 6_300
    assert _ledger().sku(MAPS_SEARCH).cap == 4_500


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
    assert r.sku.id == "maps_search" and r.n == 1 and r.period == "2026-11"
    assert r.day == "2026-11-15"
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


async def test_the_india_stop_is_higher_than_the_global_one() -> None:
    docs = MemoryDocs()
    await docs.write([Set("jarvis_api_quota/maps_search@2026-11", {"used": 4_500})])
    with pytest.raises(QuotaReached) as exc:
        await _ledger(docs).reserve(MAPS_SEARCH)
    assert "4,500" in str(exc.value)
    r = await _ledger(docs, pricing="india").reserve(MAPS_SEARCH)
    assert r.left == 31_500 - 4_501


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


async def test_a_per_month_latch_marks_the_period_used_up() -> None:
    led = _ledger()
    r = await led.reserve(MAPS_SEARCH, 3)
    await led.latch(r, "month")
    use = await led.use(MAPS_SEARCH)
    assert use.used == MAPS_SEARCH.cap and use.left == 0 and use.reached
    with pytest.raises(QuotaReached):
        await led.reserve(MAPS_SEARCH)


async def test_a_per_day_latch_on_a_youtube_bucket_closes_that_day() -> None:
    clock = Clock(NOW)
    led = QuotaLedger(MemoryDocs(), now=clock)
    r = await led.reserve(YOUTUBE_UNITS, 3)
    await led.latch(r, "day")
    assert (await led.use(YOUTUBE_UNITS)).reached
    with pytest.raises(QuotaReached):
        await led.reserve(YOUTUBE_UNITS)
    clock.at = datetime(2026, 11, 16, 12, 0, tzinfo=UTC)  # the next Pacific day
    assert (await led.reserve(YOUTUBE_UNITS)).left == YOUTUBE_UNITS.cap - 1


async def test_a_per_day_limit_on_a_monthly_sku_closes_only_today() -> None:
    clock = Clock(NOW)
    docs = MemoryDocs()
    led = QuotaLedger(docs, now=clock)
    r = await led.reserve(MAPS_SEARCH, 5)
    await led.latch(r, "day")
    use = await led.use(MAPS_SEARCH)
    assert use.used == 5 and use.left == MAPS_SEARCH.cap - 5  # the month is NOT used up
    with pytest.raises(QuotaReached) as exc:
        await led.reserve(MAPS_SEARCH)
    assert "today" in str(exc.value) and "Pacific" in str(exc.value)
    view = (await led.view())["maps_search"]
    assert view["paused_today"] is True and view["reached"] is True and view["used"] == 5
    clock.at = datetime(2026, 11, 16, 12, 0, tzinfo=UTC)  # tomorrow, same month
    again = await led.reserve(MAPS_SEARCH)
    assert again.left == MAPS_SEARCH.cap - 6
    assert (await led.view())["maps_search"]["paused_today"] is False


async def test_a_latch_after_pacific_midnight_closes_the_day_the_call_was_made() -> None:
    """The call was reserved at 23:59 Pacific; Google's per-day "used up" is handled at 00:01.
    The day that is closed is the reservation's, not the new one."""
    clock = Clock(BEFORE_MIDNIGHT)
    led = QuotaLedger(MemoryDocs(), now=clock)
    r = await led.reserve(MAPS_ROUTE)
    assert r.day == "2026-11-15"
    clock.at = AFTER_MIDNIGHT
    await led.latch(r, "day")
    fresh = await led.reserve(MAPS_ROUTE)  # 16 November is open
    assert fresh.day == "2026-11-16"
    yt = Clock(BEFORE_MIDNIGHT)
    led2 = QuotaLedger(MemoryDocs(), now=yt)
    r2 = await led2.reserve(YOUTUBE_SEARCH)
    yt.at = AFTER_MIDNIGHT
    await led2.latch(r2, "day")
    assert (await led2.reserve(YOUTUBE_SEARCH)).period == "2026-11-16"
    yt.at = BEFORE_MIDNIGHT
    assert (await led2.use(YOUTUBE_SEARCH)).reached  # the 15th is the one used up


async def test_latch_and_refund_after_the_month_changes_touch_the_old_month() -> None:
    clock = Clock(MONTH_END)
    docs = MemoryDocs()
    led = QuotaLedger(docs, now=clock)
    latched = await led.reserve(MAPS_SEARCH)
    refunded = await led.reserve(MAPS_ROUTE)
    assert latched.period == refunded.period == "2026-11"
    clock.at = NEXT_MONTH
    await led.latch(latched, "month")
    await led.refund(refunded)
    nov_search = await docs.get("jarvis_api_quota/maps_search@2026-11")
    nov_route = await docs.get("jarvis_api_quota/maps_route@2026-11")
    assert nov_search is not None and nov_search["used"] == MAPS_SEARCH.cap
    assert nov_route is not None and nov_route["used"] == 0
    assert await docs.get("jarvis_api_quota/maps_search@2026-12") is None
    r = await led.reserve(MAPS_SEARCH)  # December is open
    assert r.period == "2026-12" and r.left == MAPS_SEARCH.cap - 1


async def test_a_per_day_latch_across_the_month_change_closes_only_the_old_day() -> None:
    clock = Clock(MONTH_END)
    led = QuotaLedger(MemoryDocs(), now=clock)
    r = await led.reserve(MAPS_SEARCH)
    clock.at = NEXT_MONTH
    await led.latch(r, "day")
    assert (await led.reserve(MAPS_SEARCH)).period == "2026-12"
    clock.at = MONTH_END
    with pytest.raises(QuotaReached):
        await led.reserve(MAPS_SEARCH)  # 30 November stays closed


async def test_refund_keeps_a_closed_day() -> None:
    led = _ledger()
    a = await led.reserve(MAPS_SEARCH)
    b = await led.reserve(MAPS_SEARCH)
    await led.latch(a, "day")
    await led.refund(b)
    with pytest.raises(QuotaReached):
        await led.reserve(MAPS_SEARCH)


async def test_a_late_latch_for_yesterday_never_reopens_today() -> None:
    """Code review CR-2: A reserves at 23:59:59 Pacific, B at 00:00:01. B's per-day "used up"
    closes today; A's, handled later, is for yesterday — it must not move closed_day back and
    reopen today."""
    clock = Clock(BEFORE_MIDNIGHT)
    led = QuotaLedger(MemoryDocs(), now=clock)
    a = await led.reserve(MAPS_SEARCH)
    clock.at = AFTER_MIDNIGHT
    b = await led.reserve(MAPS_SEARCH)
    assert (a.day, b.day) == ("2026-11-15", "2026-11-16")
    await led.latch(b, "day")
    await led.latch(a, "day")  # the late answer for yesterday's call
    with pytest.raises(QuotaReached):
        await led.reserve(MAPS_SEARCH)
    assert (await led.view())["maps_search"]["paused_today"] is True


async def test_a_refund_after_a_whole_period_latch_never_reopens_a_slot() -> None:
    """Code review CR-2: once Google said the period's quota is gone, a refund of another call
    (one that never reached Google) gives nothing back."""
    for sku, limit in ((MAPS_SEARCH, "month"), (YOUTUBE_SEARCH, "day"), (MAPS_ROUTE, "month")):
        led = _ledger()
        latched = await led.reserve(sku)
        other = await led.reserve(sku)
        await led.latch(latched, limit)  # type: ignore[arg-type]
        await led.refund(other)
        with pytest.raises(QuotaReached):
            await led.reserve(sku)
        assert (await led.use(sku)).used >= sku.cap


async def test_a_latched_counter_stays_latched_when_repaired_from_unreadable() -> None:
    docs = MemoryDocs()
    docs._data["jarvis_api_quota/maps_search@2026-11"] = {"used": "bad"}
    led = _ledger(docs)
    r = Reservation(MAPS_SEARCH, "2026-11", 1, day="2026-11-15")
    await led.latch(r, "month")
    await led.refund(r)
    with pytest.raises(QuotaReached):
        await led.reserve(MAPS_SEARCH)


@pytest.mark.parametrize("latched", ["yes", 1, None])
async def test_a_latched_flag_that_is_not_a_boolean_fails_closed(latched: object) -> None:
    docs = MemoryDocs()
    docs._data["jarvis_api_quota/maps_search@2026-11"] = {"used": 3, "latched": latched}
    with pytest.raises(QuotaUnreadable):
        await _ledger(docs).reserve(MAPS_SEARCH)


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
        {"used": 3, "closed_day": 5},
        {"used": 3, "closed_day": "yesterday"},
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
    docs._data["jarvis_api_quota/maps_route_2w@2026-11"] = {}
    assert (await led.use(MAPS_ROUTE_2W)).used == 0


async def test_a_latch_repairs_an_unreadable_counter_to_used_up() -> None:
    docs = MemoryDocs()
    docs._data["jarvis_api_quota/maps_search@2026-11"] = {"used": "bad"}
    led = _ledger(docs)
    await led.latch(Reservation(MAPS_SEARCH, "2026-11", 1, day="2026-11-15"), "day")
    assert (await led.use(MAPS_SEARCH)).reached


async def test_refund_and_latch_never_raise_on_a_store_error() -> None:
    class Broken(MemoryDocs):
        async def transaction(self, fn):  # type: ignore[no-untyped-def,override]
            raise RuntimeError("store down")

    led = QuotaLedger(Broken(), now=lambda: NOW)
    r = Reservation(MAPS_SEARCH, "2026-11", 1, day="2026-11-15")
    await led.refund(r)
    await led.latch(r, "month")
    await led.latch(r, "day")


async def test_view_lists_every_sku_and_says_unreadable_instead_of_zero() -> None:
    docs = MemoryDocs()
    led = _ledger(docs)
    await led.reserve(MAPS_SEARCH)
    docs._data["jarvis_api_quota/youtube_search@2026-11-15"] = {"used": -4}
    view = await led.view()
    assert view["maps_search"] == {
        "period": "2026-11",
        "used": 1,
        "limit": 4_500,
        "left": 4_499,
        "reached": False,
        "paused_today": False,
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
