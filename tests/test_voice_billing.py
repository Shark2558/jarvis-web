# tests/test_voice_billing.py — slice 9 D9 (as fixed by the backend review): Google's free speech
# allowance is per billing account and resets on Pacific-time months, so JARVIS counts it ONCE for
# the whole deployment ({prefix}allowance/{YYYY-MM}, America/Los_Angeles) — TTS characters per
# voice type, STT seconds. Rupees stay in each owner's IST month. Only the part above the
# allowance is priced (list price × the day's rate), the owner's limit gates only a call that would
# be priced, and a corrupt counter fails closed for priced calls.
from __future__ import annotations

from datetime import UTC, datetime

import pytest
from billing_fakes import NOW, RATE, UID, BrokenDocs, Clock, billing, put_raw, registry

from jarvis.billing import BudgetPatch, BudgetReached, BudgetUnavailable
from jarvis.billing.meter import (
    ALLOWANCE_TZ,
    UsageMeter,
    UsageUnreadable,
    decode_allowance,
    priced_units,
)
from jarvis.storage.docs import MemoryDocs

KEY = "tts_chirp3-hd"
FREE = 900_000.0
USD_PER_CHAR = 30.0 / 1_000_000
PATH = f"jarvis_usage/{UID}_2026-11"  # the owner's IST month at NOW
ALLOW = "jarvis_allowance/2026-11"  # the deployment's Pacific month at NOW
OTHER = "u_other"


async def _add(m: UsageMeter, *, uid: str = UID, key: str = KEY, units: float = 500, now=NOW):  # type: ignore[no-untyped-def]
    return await m.add_units(
        uid,
        key=key,
        units=units,
        free_units=FREE,
        usd_per_unit=USD_PER_CHAR,
        inr_per_usd=RATE,
        label="voice",
        now=now,
    )


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


async def test_within_the_allowance_is_counted_once_for_the_deployment_and_free() -> None:
    docs = MemoryDocs()
    m = UsageMeter(docs)
    c = await _add(m)
    assert (c.units, c.priced_units, c.usd, c.inr) == (500, 0, 0, 0)
    assert (await m.allowance("2026-11")).used(KEY) == 500
    doc = await docs.get(ALLOW)
    assert doc is not None and doc["units"] == {KEY: 500} and doc["tz"] == ALLOWANCE_TZ
    assert await docs.get(PATH) is None  # a free call writes no rupees anywhere


async def test_crossing_the_allowance_prices_only_the_excess_in_the_owners_month() -> None:
    docs = MemoryDocs()
    await put_raw(docs, ALLOW, {"units": {KEY: FREE - 100}})
    m = UsageMeter(docs)
    c = await _add(m, units=400)
    assert c.priced_units == 300
    assert c.usd == pytest.approx(300 * USD_PER_CHAR)
    assert c.inr == pytest.approx(300 * USD_PER_CHAR * RATE)
    assert (await m.allowance("2026-11")).used(KEY) == FREE + 300
    u = await m.get(UID, "2026-11")
    assert u.inr_total == pytest.approx(c.inr) and u.calls == 1
    assert u.by_brain == pytest.approx({"voice": c.usd})
    assert u.by_brain_inr == pytest.approx({"voice": c.inr})


async def test_the_allowance_is_shared_by_every_owner() -> None:
    """Google's free tier is per billing account: two owners draw on ONE allowance."""
    docs = MemoryDocs()
    m = UsageMeter(docs)
    await _add(m, uid=UID, units=FREE - 100)
    c = await _add(m, uid=OTHER, units=300)
    assert c.priced_units == 200  # the other owner pays for crossing what the first one used
    assert (await m.get(OTHER, "2026-11")).inr_total == pytest.approx(c.inr)
    assert (await m.get(UID, "2026-11")).inr_total == 0


async def test_the_allowance_month_is_pacific_while_rupees_stay_in_the_ist_month() -> None:
    docs = MemoryDocs()
    m = UsageMeter(docs)
    # 1 Dec 00:30 IST is still 30 Nov 11:00 in California: Google has not reset yet
    early_dec_ist = datetime(2026, 11, 30, 19, 0, tzinfo=UTC)
    assert m.month_of(early_dec_ist) == "2026-12"
    assert m.allowance_month_of(early_dec_ist) == "2026-11"
    await put_raw(docs, ALLOW, {"units": {KEY: FREE}})
    c = await _add(m, units=100, now=early_dec_ist)
    assert c.priced_units == 100  # November's allowance is still the one in force
    assert (await m.get(UID, "2026-12")).inr_total == pytest.approx(c.inr)
    # 1 Dec 00:30 in California: a fresh allowance
    pacific_dec = datetime(2026, 12, 1, 8, 30, tzinfo=UTC)
    assert m.allowance_month_of(pacific_dec) == "2026-12"
    c2 = await _add(m, units=100, now=pacific_dec)
    assert c2.priced_units == 0
    assert m.allowance_resets_at(NOW) == datetime(2026, 12, 1, 8, 0, tzinfo=UTC)  # 00:00 PST


async def test_chat_spend_never_touches_the_allowance_counter() -> None:
    docs = MemoryDocs()
    m = UsageMeter(docs)
    await _add(m, units=7)
    await _add(m, key="stt_seconds", units=7)
    await m.add(UID, brain_id="anthropic", cost_usd=0.01, cost_inr=0.95, now=NOW)
    a = await m.allowance("2026-11")
    assert (a.used(KEY), a.used("stt_seconds")) == (7, 7)
    assert (await m.get(UID, "2026-11")).calls == 1


# ---- corrupt counters fail closed (review item 4) ----------------------------------------------


@pytest.mark.parametrize("bad", [float("nan"), -1, "lots", None, True, float("inf")])
async def test_a_corrupt_counter_is_unreadable_for_its_key_and_kept(bad: object) -> None:
    docs = MemoryDocs()
    await put_raw(docs, ALLOW, {"units": {KEY: bad, "stt_seconds": 3}})
    m = UsageMeter(docs)
    a = await m.allowance("2026-11")
    with pytest.raises(UsageUnreadable):
        a.used(KEY)
    assert a.used("stt_seconds") == 3 and a.used("tts_studio") == 0
    with pytest.raises(UsageUnreadable):
        await _add(m, units=5)  # never "0 used": nothing is written
    await _add(m, key="stt_seconds", units=2)  # another counter still works …
    doc = await docs.get(ALLOW)
    assert doc is not None and doc["units"]["stt_seconds"] == 5
    assert KEY in doc["units"]  # … and the corrupt one is kept, never silently reset


@pytest.mark.parametrize("doc", [{"units": "corrupt"}, {"units": [1, 2]}, "not a map"])
async def test_an_unreadable_counter_map_is_unreadable(doc: object) -> None:
    with pytest.raises(UsageUnreadable):
        decode_allowance(doc, "2026-11")  # type: ignore[arg-type]


async def test_a_bad_unit_key_is_refused() -> None:
    with pytest.raises(ValueError):
        await _add(UsageMeter(MemoryDocs()), key="tts.chirp/../x")


# ---- the gate --------------------------------------------------------------------------------


async def _seed(docs: MemoryDocs, *, used: float, inr: float = 600.0, limit: object = 500) -> None:
    await put_raw(docs, ALLOW, {"units": {KEY: used}})
    await put_raw(docs, PATH, {"inr_total": inr})
    if limit is not None:
        await put_raw(docs, f"jarvis_budget/{UID}", {"monthly_limit_inr": limit})


async def test_no_limit_means_no_gate() -> None:
    b = billing(registry())
    await b.ensure_units_allowed(UID, key=KEY, units=10**9, free_units=FREE)


async def test_free_calls_still_work_at_the_limit() -> None:
    docs = MemoryDocs()
    await _seed(docs, used=FREE - 1000)
    await billing(registry(), docs=docs).ensure_units_allowed(
        UID, key=KEY, units=1000, free_units=FREE
    )


async def test_priced_calls_are_refused_at_the_limit_with_a_voice_message() -> None:
    docs = MemoryDocs()
    await _seed(docs, used=FREE - 10)
    b = billing(registry(), docs=docs)
    with pytest.raises(BudgetReached) as e:
        await b.ensure_units_allowed(UID, key=KEY, units=11, free_units=FREE)
    assert e.value.limit_inr == 500 and "₹500" in str(e.value)
    assert "browser" in str(e.value).lower() and "$" not in str(e.value)


async def test_another_owners_use_counts_against_the_shared_allowance() -> None:
    docs = MemoryDocs()
    await put_raw(docs, f"jarvis_budget/{UID}", {"monthly_limit_inr": 500})
    await put_raw(docs, PATH, {"inr_total": 600.0})
    b = billing(registry(), docs=docs)
    await b.record_units(
        OTHER, key=KEY, units=FREE, free_units=FREE, usd_per_unit=USD_PER_CHAR, label="voice"
    )
    with pytest.raises(BudgetReached):
        await b.ensure_units_allowed(UID, key=KEY, units=1, free_units=FREE)


async def test_priced_calls_below_the_limit_go_ahead() -> None:
    docs = MemoryDocs()
    await _seed(docs, used=FREE, inr=10.0)
    await billing(registry(), docs=docs).ensure_units_allowed(
        UID, key=KEY, units=100, free_units=FREE
    )


async def test_unreadable_limit_blocks_priced_but_not_free_calls() -> None:
    docs = MemoryDocs()
    await _seed(docs, used=FREE - 5, inr=1.0, limit="lots")
    b = billing(registry(), docs=docs)
    await b.ensure_units_allowed(UID, key=KEY, units=5, free_units=FREE)
    with pytest.raises(BudgetUnavailable):
        await b.ensure_units_allowed(UID, key=KEY, units=6, free_units=FREE)


async def test_an_unreadable_owner_month_blocks_only_priced_calls_under_a_limit() -> None:
    docs = MemoryDocs()
    await put_raw(docs, PATH, {"inr_total": "corrupt"})
    b = billing(registry(), docs=docs)
    await b.ensure_units_allowed(UID, key=KEY, units=5, free_units=FREE)  # free: month not needed
    await put_raw(docs, ALLOW, {"units": {KEY: FREE}})
    await b.ensure_units_allowed(UID, key=KEY, units=5, free_units=FREE)  # priced, no limit
    await b.budgets.update(UID, BudgetPatch(monthly_limit_inr=500))
    with pytest.raises(BudgetUnavailable):
        await b.ensure_units_allowed(UID, key=KEY, units=5, free_units=FREE)


async def test_a_corrupt_allowance_counter_fails_closed_only_under_a_limit() -> None:
    docs = MemoryDocs()
    await put_raw(docs, ALLOW, {"units": {KEY: "corrupt"}})
    await put_raw(docs, PATH, {"inr_total": 1.0})
    b = billing(registry(), docs=docs)
    await b.ensure_units_allowed(UID, key=KEY, units=5, free_units=FREE)  # no limit: no gate
    await b.ensure_units_allowed(UID, key="stt_seconds", units=5, free_units=3_240)
    await b.budgets.update(UID, BudgetPatch(monthly_limit_inr=500))
    with pytest.raises(BudgetUnavailable):
        await b.ensure_units_allowed(UID, key=KEY, units=5, free_units=FREE)
    with pytest.raises(BudgetUnavailable):
        await b.allowance((KEY,))  # the voice view says so instead of showing "0 used"


async def test_storage_down_fails_closed_when_it_cannot_tell() -> None:
    b = billing(registry(), docs=BrokenDocs(fail_reads=True))
    with pytest.raises(BudgetUnavailable):
        await b.ensure_units_allowed(UID, key=KEY, units=5, free_units=FREE)


# ---- recording and the views -----------------------------------------------------------------


async def test_record_units_prices_at_the_days_rate_and_shows_in_usage() -> None:
    docs = MemoryDocs()
    await put_raw(docs, ALLOW, {"units": {KEY: FREE}})
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


async def test_allowance_view_for_the_voice_panel() -> None:
    docs = MemoryDocs()
    await put_raw(docs, ALLOW, {"units": {KEY: 42}})
    b = billing(registry(), docs=docs, clock=Clock(NOW))
    a = await b.allowance((KEY, "stt_seconds"))
    assert a.month == "2026-11" and a.used(KEY) == 42 and a.used("stt_seconds") == 0
    assert b.allowance_resets_at() == datetime(2026, 12, 1, 8, 0, tzinfo=UTC)
