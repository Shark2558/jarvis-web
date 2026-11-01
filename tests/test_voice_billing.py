# tests/test_voice_billing.py — slice 9 D9: voice usage counted per IST month in the existing meter
# (TTS characters per voice type, STT seconds), priced only above the free allowance at list price
# × the day's rate, gated by the owner's limit only when a call would be priced, and included in
# the month total that GET /v1/usage shows.
from __future__ import annotations

import pytest
from billing_fakes import NOW, RATE, UID, BrokenDocs, billing, put_raw, registry

from jarvis.billing import BudgetPatch, BudgetReached, BudgetUnavailable
from jarvis.billing.meter import UsageMeter, priced_units
from jarvis.storage.docs import MemoryDocs

KEY = "tts_chirp3-hd"
FREE = 1_000_000.0
USD_PER_CHAR = 30.0 / 1_000_000
PATH = f"jarvis_usage/{UID}_2026-11"


@pytest.mark.parametrize(
    ("used", "units", "free", "want"),
    [
        (0, 100, 1000, 0),
        (950, 100, 1000, 50),
        (1000, 100, 1000, 100),
        (5000, 100, 1000, 100),
        (0, 100, 0, 100),
        (999.5, 1, 1000, 0.5),
    ],
)
def test_priced_units_is_the_part_above_the_allowance(
    used: float, units: float, free: float, want: float
) -> None:
    assert priced_units(used, units, free) == pytest.approx(want)


async def test_within_the_allowance_is_counted_but_free() -> None:
    m = UsageMeter(MemoryDocs())
    c = await m.add_units(
        UID,
        key=KEY,
        units=500,
        free_units=FREE,
        usd_per_unit=USD_PER_CHAR,
        inr_per_usd=RATE,
        label="voice",
        now=NOW,
    )
    assert (c.units, c.priced_units, c.usd, c.inr) == (500, 0, 0, 0)
    u = await m.get(UID, "2026-11")
    assert u.units == {KEY: 500} and u.inr_total == 0 and u.calls == 0 and u.by_brain == {}


async def test_crossing_the_allowance_prices_only_the_excess() -> None:
    docs = MemoryDocs()
    await put_raw(docs, PATH, {"inr_total": 0, "units": {KEY: FREE - 100}})
    m = UsageMeter(docs)
    c = await m.add_units(
        UID,
        key=KEY,
        units=400,
        free_units=FREE,
        usd_per_unit=USD_PER_CHAR,
        inr_per_usd=RATE,
        label="voice",
        now=NOW,
    )
    assert c.priced_units == 300
    assert c.usd == pytest.approx(300 * USD_PER_CHAR)
    assert c.inr == pytest.approx(300 * USD_PER_CHAR * RATE)
    u = await m.get(UID, "2026-11")
    assert u.units[KEY] == FREE + 300
    assert u.inr_total == pytest.approx(c.inr) and u.calls == 1
    assert u.by_brain == pytest.approx({"voice": c.usd})
    assert u.by_brain_inr == pytest.approx({"voice": c.inr})


async def test_chat_spend_after_voice_keeps_the_voice_counters() -> None:
    docs = MemoryDocs()
    m = UsageMeter(docs)
    for key in (KEY, "stt_seconds"):
        await m.add_units(
            UID,
            key=key,
            units=7,
            free_units=FREE,
            usd_per_unit=0.0,
            inr_per_usd=RATE,
            label="voice",
            now=NOW,
        )
    await m.add(UID, brain_id="anthropic", cost_usd=0.01, cost_inr=0.95, now=NOW)
    u = await m.get(UID, "2026-11")
    assert u.units == {KEY: 7, "stt_seconds": 7} and u.calls == 1
    doc = await docs.get(PATH)
    assert doc is not None and doc["units"] == {KEY: 7, "stt_seconds": 7}


async def test_unit_counters_are_read_leniently() -> None:
    docs = MemoryDocs()
    await put_raw(docs, PATH, {"inr_total": 1.0, "units": {KEY: float("nan"), "ok": 3, "x": -1}})
    u = await UsageMeter(docs).get(UID, "2026-11")
    assert u.units == {"ok": 3} and u.inr_total == 1.0


async def test_a_bad_unit_key_is_refused() -> None:
    with pytest.raises(ValueError):
        await UsageMeter(MemoryDocs()).add_units(
            UID,
            key="tts.chirp/../x",
            units=1,
            free_units=0,
            usd_per_unit=0,
            inr_per_usd=RATE,
            label="voice",
            now=NOW,
        )


# ---- the gate --------------------------------------------------------------------------------


async def _at_limit(docs: MemoryDocs, *, used: float = FREE) -> None:
    await put_raw(docs, PATH, {"inr_total": 600.0, "units": {KEY: used}})
    await put_raw(docs, f"jarvis_budget/{UID}", {"monthly_limit_inr": 500})


async def test_no_limit_means_no_gate() -> None:
    b = billing(registry())
    await b.ensure_units_allowed(UID, key=KEY, units=10**9, free_units=FREE)


async def test_free_calls_still_work_at_the_limit() -> None:
    docs = MemoryDocs()
    await _at_limit(docs, used=FREE - 1000)
    b = billing(registry(), docs=docs)
    await b.ensure_units_allowed(UID, key=KEY, units=1000, free_units=FREE)


async def test_priced_calls_are_refused_at_the_limit_with_a_voice_message() -> None:
    docs = MemoryDocs()
    await _at_limit(docs, used=FREE - 10)
    b = billing(registry(), docs=docs)
    with pytest.raises(BudgetReached) as e:
        await b.ensure_units_allowed(UID, key=KEY, units=11, free_units=FREE)
    assert e.value.limit_inr == 500 and "₹500" in str(e.value)
    assert "browser" in str(e.value).lower() and "$" not in str(e.value)


async def test_priced_calls_below_the_limit_go_ahead() -> None:
    docs = MemoryDocs()
    await put_raw(docs, PATH, {"inr_total": 10.0, "units": {KEY: FREE}})
    await put_raw(docs, f"jarvis_budget/{UID}", {"monthly_limit_inr": 500})
    await billing(registry(), docs=docs).ensure_units_allowed(
        UID, key=KEY, units=100, free_units=FREE
    )


async def test_unreadable_limit_blocks_priced_but_not_free_calls() -> None:
    docs = MemoryDocs()
    await put_raw(docs, PATH, {"inr_total": 1.0, "units": {KEY: FREE - 5}})
    await put_raw(docs, f"jarvis_budget/{UID}", {"monthly_limit_inr": "lots"})
    b = billing(registry(), docs=docs)
    await b.ensure_units_allowed(UID, key=KEY, units=5, free_units=FREE)
    with pytest.raises(BudgetUnavailable):
        await b.ensure_units_allowed(UID, key=KEY, units=6, free_units=FREE)


async def test_unreadable_month_fails_closed_only_when_a_limit_is_set() -> None:
    docs = MemoryDocs()
    await put_raw(docs, PATH, {"inr_total": "corrupt"})
    b = billing(registry(), docs=docs)
    await b.ensure_units_allowed(UID, key=KEY, units=5, free_units=FREE)  # no limit: no gate
    await b.budgets.update(UID, BudgetPatch(monthly_limit_inr=500))
    with pytest.raises(BudgetUnavailable):
        await b.ensure_units_allowed(UID, key=KEY, units=5, free_units=FREE)


async def test_storage_down_fails_closed_when_it_cannot_tell() -> None:
    b = billing(registry(), docs=BrokenDocs(fail_reads=True))
    with pytest.raises(BudgetUnavailable):
        await b.ensure_units_allowed(UID, key=KEY, units=5, free_units=FREE)


# ---- recording and the month view ------------------------------------------------------------


async def test_record_units_prices_at_the_days_rate_and_shows_in_usage() -> None:
    docs = MemoryDocs()
    await put_raw(docs, PATH, {"inr_total": 0.0, "units": {KEY: FREE}})
    b = billing(registry(), docs=docs)
    c = await b.record_units(
        UID, key=KEY, units=1000, free_units=FREE, usd_per_unit=USD_PER_CHAR, label="voice"
    )
    assert c.inr == pytest.approx(1000 * USD_PER_CHAR * RATE)
    view = await b.usage(UID)
    assert view.used_inr == pytest.approx(round(c.inr, 2))
    entry = next(x for x in view.by_brain if x.brain == "voice")
    assert entry.label == "Voice" and entry.used_inr == pytest.approx(round(c.inr, 2))


async def test_record_units_never_raises() -> None:
    b = billing(registry(), docs=BrokenDocs(fail_tx=True))
    c = await b.record_units(
        UID, key=KEY, units=10, free_units=0, usd_per_unit=USD_PER_CHAR, label="voice"
    )
    assert c.units == 10 and c.inr == 0


async def test_month_usage_for_the_voice_view() -> None:
    docs = MemoryDocs()
    await put_raw(docs, PATH, {"inr_total": 2.0, "units": {KEY: 42}, "by_brain_inr": {"voice": 2}})
    m = await billing(registry(), docs=docs).month(UID)
    assert m.units == {KEY: 42} and m.by_brain_inr == {"voice": 2}
