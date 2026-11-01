# tests/test_billing_meter.py — slice 7b: the monthly usage meter (owner's month, transactional)
from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import anyio
import httpx
import pytest
from billing_fakes import NOW, RATE, UID, BrokenDocs, Clock, billing, put_raw, registry
from brief_fakes import SlowDocs

from jarvis.billing.fx import FxRates
from jarvis.billing.meter import UsageMeter, UsageUnreadable
from jarvis.storage.docs import MemoryDocs


async def test_add_then_read_this_month() -> None:
    docs = MemoryDocs()
    m = UsageMeter(docs, tz="Asia/Kolkata")
    await m.add(UID, brain_id="anthropic", cost_usd=0.01, cost_inr=0.9524, now=NOW)
    await m.add(UID, brain_id="anthropic", cost_usd=0.02, cost_inr=1.9048, now=NOW)
    await m.add(UID, brain_id="custom", cost_usd=0.005, cost_inr=0.4762, now=NOW)
    u = await m.get(UID, "2026-11")
    assert u.month == "2026-11" and u.calls == 3
    assert u.usd_total == pytest.approx(0.035) and u.inr_total == pytest.approx(3.3334)
    assert u.by_brain == pytest.approx({"anthropic": 0.03, "custom": 0.005})
    assert u.by_brain_inr == pytest.approx({"anthropic": 2.8572, "custom": 0.4762})
    doc = await docs.get(f"jarvis_usage/{UID}_2026-11")
    assert doc is not None
    assert {"user_id", "month", "usd_total", "inr_total", "calls", "by_brain", "updated_at"} <= set(
        doc
    )
    assert doc["user_id"] == UID and doc["month"] == "2026-11"


async def test_an_empty_month_reads_as_zero() -> None:
    u = await UsageMeter(MemoryDocs()).get(UID, "2026-11")
    assert (u.inr_total, u.usd_total, u.calls, u.by_brain) == (0.0, 0.0, 0, {})


@pytest.mark.parametrize(
    ("at", "month"),
    [
        (datetime(2026, 11, 30, 18, 29, 59, tzinfo=UTC), "2026-11"),  # 23:59:59 IST, 30 Nov
        (datetime(2026, 11, 30, 18, 30, 0, tzinfo=UTC), "2026-12"),  # 00:00 IST, 1 Dec
        (datetime(2026, 12, 31, 18, 30, 0, tzinfo=UTC), "2027-01"),  # new year in India
        (datetime(2027, 2, 28, 18, 30, 0, tzinfo=UTC), "2027-03"),
    ],
)
def test_the_month_is_the_owners_month(at: datetime, month: str) -> None:
    assert UsageMeter(MemoryDocs(), tz="Asia/Kolkata").month_of(at) == month


async def test_rollover_at_ist_midnight_on_the_last_day_starts_a_fresh_month() -> None:
    m = UsageMeter(MemoryDocs(), tz="Asia/Kolkata")
    before = datetime(2026, 11, 30, 18, 29, 59, tzinfo=UTC)
    await m.add(UID, brain_id="anthropic", cost_usd=1.0, cost_inr=95.24, now=before)
    await m.add(
        UID, brain_id="anthropic", cost_usd=0.5, cost_inr=47.62, now=before + timedelta(seconds=1)
    )
    assert (await m.get(UID, "2026-11")).inr_total == pytest.approx(95.24)
    assert (await m.get(UID, "2026-12")).inr_total == pytest.approx(47.62)


async def test_an_unknown_time_zone_falls_back_to_utc() -> None:
    m = UsageMeter(MemoryDocs(), tz="Not/AZone")
    assert m.month_of(datetime(2026, 11, 30, 20, 0, tzinfo=UTC)) == "2026-11"


@pytest.mark.parametrize("docs", [MemoryDocs(), SlowDocs()])
async def test_concurrent_increments_are_never_lost(docs: MemoryDocs) -> None:
    m = UsageMeter(docs)

    async def one(i: int) -> None:
        brain = "anthropic" if i % 2 else "custom"
        await m.add(UID, brain_id=brain, cost_usd=0.001, cost_inr=0.09524, now=NOW)

    await asyncio.gather(*(one(i) for i in range(40)))
    u = await m.get(UID, "2026-11")
    assert u.calls == 40
    assert u.usd_total == pytest.approx(0.04) and u.inr_total == pytest.approx(3.8096)
    assert u.by_brain == pytest.approx({"anthropic": 0.02, "custom": 0.02})


async def test_unreadable_display_fields_count_as_zero() -> None:
    """Fields only shown (never used by the limit) are read leniently; the month's rupee total,
    which the limit compares against, is not (next test)."""
    docs = MemoryDocs()
    path = f"jarvis_usage/{UID}_2026-11"
    await put_raw(
        docs,
        path,
        {
            "usd_total": "lots",
            "inr_total": 2.5,
            "calls": "x",
            "by_brain": {"anthropic": float("nan"), "ok": 0.5},
            "by_brain_inr": [1],
        },
    )
    m = UsageMeter(docs)
    u = await m.get(UID, "2026-11")
    assert (u.usd_total, u.inr_total, u.calls) == (0.0, 2.5, 0)
    assert u.by_brain == {"ok": 0.5} and u.by_brain_inr == {}
    await m.add(UID, brain_id="anthropic", cost_usd=0.01, cost_inr=0.95, now=NOW)
    assert (await m.get(UID, "2026-11")).inr_total == pytest.approx(3.45)


@pytest.mark.parametrize("bad", ["500", float("nan"), float("inf"), -5, True, None, [1], "missing"])
async def test_an_unreadable_month_total_is_never_read_as_zero_nor_overwritten(
    bad: object,
) -> None:
    """₹0 would open the limit; resetting it on the next reply would lose the month's spend."""
    docs = MemoryDocs()
    path = f"jarvis_usage/{UID}_2026-11"
    doc: dict[str, object] = {"usd_total": 3.0, "calls": 9}
    if bad != "missing":
        doc["inr_total"] = bad
    await put_raw(docs, path, doc)
    m = UsageMeter(docs)
    with pytest.raises(UsageUnreadable):
        await m.get(UID, "2026-11")
    with pytest.raises(UsageUnreadable):
        await m.add(UID, brain_id="anthropic", cost_usd=0.01, cost_inr=0.95, now=NOW)
    assert await docs.get(path) == doc  # left as it was, for the owner to see and fix
    # Billing.record still never raises (the reply goes out); it logs and writes nothing
    b = billing(registry(), docs=docs)
    assert await b.record(UID, "anthropic", 0.01) == pytest.approx(0.9524)
    assert await docs.get(path) == doc


@pytest.mark.parametrize("uid", ["", "../x", "a/b", "x" * 200])
async def test_a_bad_user_id_is_refused(uid: str) -> None:
    with pytest.raises(ValueError):
        await UsageMeter(MemoryDocs()).get(uid, "2026-11")


async def test_record_adds_rupees_at_the_rate_of_the_moment() -> None:
    """Past spend never changes when the rate moves: each call is converted when it happens."""
    clock = Clock()
    answers = iter([{"date": "2026-11-14", "rate": 90.0}, {"date": "2026-11-16", "rate": 100.0}])

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=next(answers))

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    b = billing(registry(), clock=clock)
    b.fx = FxRates(docs=None, default_rate=RATE, http=http, clock=clock)
    await b.fx.refresh()
    assert await b.record(UID, "anthropic", 0.10) == pytest.approx(9.0)
    clock.at = NOW + timedelta(days=1, hours=1)
    await b.fx.refresh()
    assert await b.record(UID, "anthropic", 0.10) == pytest.approx(10.0)
    u = await b.meter.get(UID, "2026-11")
    assert u.inr_total == pytest.approx(19.0) and u.usd_total == pytest.approx(0.2)


@pytest.mark.parametrize("cost", [0.0, -1.0, float("nan"), float("inf")])
async def test_record_writes_nothing_for_a_free_or_broken_cost(cost: float) -> None:
    docs = BrokenDocs()
    b = billing(registry(), docs=docs)
    assert await b.record(UID, "anthropic", cost) == 0.0
    assert docs.tx_calls == 0


async def test_record_finishes_even_when_its_caller_is_being_cancelled() -> None:
    """Starlette cancels a streaming response when the client goes away (an anyio cancel scope,
    re-delivered at every await). The spend already happened: the meter write must still land."""
    docs = SlowDocs()  # every database call really waits, like Firestore
    b = billing(registry(), docs=docs)
    with anyio.CancelScope() as scope:
        scope.cancel()
        assert await b.record(UID, "anthropic", 0.01) == pytest.approx(0.9524)
    u = await b.meter.get(UID, "2026-11")
    assert u.calls == 1 and u.inr_total == pytest.approx(0.9524)


async def test_record_never_raises_when_the_write_fails() -> None:
    b = billing(registry(), docs=BrokenDocs(fail_tx=True))
    assert await b.record(UID, "anthropic", 0.01) == pytest.approx(0.9524)  # still converted
