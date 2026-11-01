# tests/test_web_allowance.py — slice 10 B: the monthly web-search allowance (900 Tavily credits per
# IST month for the whole deployment), reserved before each call, fail closed on a bad counter.
from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import pytest

from jarvis.storage.docs import MemoryDocs, Set
from jarvis.web.allowance import (
    MONTHLY_CREDITS,
    AllowanceReached,
    AllowanceUnreadable,
    WebAllowance,
)

NOW = datetime(2026, 11, 15, 6, 0, tzinfo=UTC)


def _allowance(docs: MemoryDocs, now: datetime = NOW, cap: int = MONTHLY_CREDITS) -> WebAllowance:
    return WebAllowance(docs, prefix="jarvis_", tz="Asia/Kolkata", cap=cap, now=lambda: now)


async def test_cap_is_ninety_percent_of_the_free_thousand() -> None:
    assert MONTHLY_CREDITS == 900
    use = await _allowance(MemoryDocs()).usage()
    assert (use.month, use.credits, use.cap, use.left) == ("2026-11", 0, 900, 900)


async def test_reserve_counts_credits_and_kinds_in_one_document_per_month() -> None:
    docs = MemoryDocs()
    a = _allowance(docs)
    await a.reserve(1, kind="search")
    await a.reserve(1, kind="read")
    doc = await docs.get("jarvis_web_usage/2026-11")
    assert doc is not None
    assert (doc["credits"], doc["searches"], doc["reads"], doc["tz"]) == (2, 1, 1, "Asia/Kolkata")
    use = await a.usage()
    assert (use.credits, use.left) == (2, 898)


async def test_the_month_is_the_owners_ist_month() -> None:
    docs = MemoryDocs()
    late = datetime(2026, 11, 30, 19, 0, tzinfo=UTC)  # 00:30 IST on 1 December
    await _allowance(docs, now=late).reserve(1, kind="search")
    assert await docs.get("jarvis_web_usage/2026-12") is not None
    assert await docs.get("jarvis_web_usage/2026-11") is None


async def test_stops_at_the_cap_and_writes_nothing_more() -> None:
    docs = MemoryDocs()
    a = _allowance(docs, cap=3)
    for _ in range(3):
        await a.reserve(1, kind="search")
    with pytest.raises(AllowanceReached) as e:
        await a.reserve(1, kind="search")
    assert "3" in str(e.value) and "$" not in str(e.value)
    assert (await a.usage()).credits == 3


async def test_concurrent_reservations_never_pass_the_cap() -> None:
    a = _allowance(MemoryDocs(), cap=5)
    got = await asyncio.gather(
        *(a.reserve(1, kind="search") for _ in range(12)), return_exceptions=True
    )
    assert sum(not isinstance(g, BaseException) for g in got) == 5
    assert all(isinstance(g, AllowanceReached) for g in got if isinstance(g, BaseException))


async def test_refund_gives_back_a_reservation_in_its_own_month() -> None:
    docs = MemoryDocs()
    a = _allowance(docs)
    r = await a.reserve(1, kind="read")
    await a.refund(r)
    use = await a.usage()
    assert use.credits == 0 and use.reads == 0
    await a.refund(r)  # a second refund never goes below zero
    assert (await a.usage()).credits == 0


async def test_settle_adds_what_the_vendor_actually_charged_beyond_the_reservation() -> None:
    a = _allowance(MemoryDocs())
    r = await a.reserve(1, kind="search")
    await a.settle(r, charged=2)
    assert (await a.usage()).credits == 2
    await a.settle(r, charged=1)  # never less than reserved
    await a.settle(r, charged=None)
    assert (await a.usage()).credits == 2


@pytest.mark.parametrize("bad", ["12", -1, float("nan"), float("inf"), True, None, [3]])
async def test_a_corrupt_counter_fails_closed(bad: object) -> None:
    docs = MemoryDocs()
    await docs.write([Set("jarvis_web_usage/2026-11", {"month": "2026-11", "credits": bad})])
    a = _allowance(docs)
    with pytest.raises(AllowanceUnreadable):
        await a.reserve(1, kind="search")
    with pytest.raises(AllowanceUnreadable):
        await a.usage()
    doc = await docs.get("jarvis_web_usage/2026-11")
    assert doc is not None and repr(doc["credits"]) == repr(bad)  # kept as it is, never reset


async def test_a_document_that_is_not_a_map_fails_closed() -> None:
    docs = MemoryDocs()
    docs._data["jarvis_web_usage/2026-11"] = ["nope"]  # type: ignore[assignment]
    with pytest.raises(AllowanceUnreadable):
        await _allowance(docs).usage()


async def test_lenient_side_counters_never_block() -> None:
    docs = MemoryDocs()
    await docs.write(
        [Set("jarvis_web_usage/2026-11", {"credits": 4, "searches": "x", "reads": -2})]
    )
    use = await _allowance(docs).usage()
    assert (use.credits, use.searches, use.reads) == (4, 0, 0)
