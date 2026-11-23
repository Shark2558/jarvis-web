# tests/test_r63_b_caps.py -- R6.3 D8 (plan review M1, H7): the writer's rupee ledger, R13.1's
# pattern. One transaction reserves each call's hold; refused with nothing written past the run's
# cap, the month cap or the 80 % gate; `busy` while a fresh hold is out for the page; settle,
# release and keep-at-hold; `close_later` and `settle_old` first; his IST month, and the month
# before for an hour after its end. Every clock is fixed.
from __future__ import annotations

import asyncio
from typing import Any

import pytest
from r63_fakes import UID, FixedClock, ist

from jarvis.buildbook.writer.caps import CapRefused, Gate, WriterCaps
from jarvis.storage.docs import MemoryDocs

OPEN = Gate(used_inr=0.0, limit_inr=None, pct=80)
HOLD = 11.84


def _caps(clock: FixedClock | None = None, docs: MemoryDocs | None = None) -> WriterCaps:
    return WriterCaps(
        docs or MemoryDocs(), "jarvis_", tz="Asia/Kolkata", clock=clock or FixedClock()
    )


async def _reserve(c: WriterCaps, n: int, **kw: Any) -> Any:
    args: dict[str, Any] = dict(
        call_id=f"wc_{n:016x}", page=f"pg_card_c{n % 100:02d}", run="trial", key="trial_x",
        hold_inr=HOLD, cap_inr=100, month_cap=None, gate=OPEN,
    )  # fmt: skip
    args.update(kw)
    return await c.reserve(UID, **args)


async def test_eight_holds_fit_the_trials_rs_100_and_the_ninth_is_refused_writing_nothing() -> None:
    docs = MemoryDocs()
    c = _caps(docs=docs)
    for n in range(8):
        await _reserve(c, n)
    before = dict(docs._data)
    with pytest.raises(CapRefused) as no:
        await _reserve(c, 8)
    assert no.value.code == "cap" and dict(docs._data) == before
    m = await c.month(UID)
    assert m.held_inr == pytest.approx(8 * HOLD) and len(m.holds) == 8


async def test_two_parallel_reserves_never_both_pass_the_cap() -> None:
    c = _caps()
    for n in range(7):
        await _reserve(c, n)
    got = await asyncio.gather(_reserve(c, 7), _reserve(c, 8), return_exceptions=True)
    assert sum(isinstance(g, CapRefused) for g in got) == 1


async def test_settle_moves_the_hold_into_the_runs_spend_and_release_gives_it_back() -> None:
    c = _caps()
    a, b = await _reserve(c, 1), await _reserve(c, 2)
    await c.settle(a, 7.5)
    await c.release(b)
    await c.release(b)  # a second close is a no-op
    m = await c.month(UID)
    assert (m.spent_inr, m.held_inr, m.holds, m.calls) == (7.5, 0.0, {}, 1)
    assert m.runs == {"trial_x": 7.5}
    assert await c.run_spent(UID, "trial_x", "trial") == 7.5


async def test_a_fresh_hold_for_the_same_page_is_busy_and_an_old_one_is_not() -> None:
    clock = FixedClock()
    c = _caps(clock)
    await _reserve(c, 1, page="pg_card_c16")
    with pytest.raises(CapRefused) as no:
        await _reserve(c, 2, page="pg_card_c16")
    assert no.value.code == "busy"
    clock.advance(minutes=11)
    await _reserve(c, 3, page="pg_card_c16")


async def test_the_month_cap_counts_release_updates_only() -> None:
    c = _caps()
    first = await _reserve(c, 1, run="first", key="first", cap_inr=1_500, hold_inr=900.0)
    await c.settle(first, 900.0)
    up = dict(run="update", key="update_6363636", cap_inr=500, month_cap=1_000)
    held = await _reserve(c, 2, hold_inr=400.0, **up)
    await c.settle(held, 400.0)
    await _reserve(c, 3, hold_inr=90.0, **up)
    with pytest.raises(CapRefused) as no:
        await _reserve(c, 4, hold_inr=20.0, **{**up, "key": "update_7070707", "cap_inr": 500,
                                             "month_cap": 500})  # fmt: skip
    assert no.value.code == "month"


async def test_the_80_percent_gate_sees_the_open_holds_of_calls_in_flight() -> None:
    c = _caps()
    gate = Gate(used_inr=2_380.0, limit_inr=3_000, pct=80)  # the line is Rs 2,400
    await _reserve(c, 1, gate=gate, cap_inr=1_500, run="first", key="first")
    with pytest.raises(CapRefused) as no:
        await _reserve(c, 2, gate=gate, cap_inr=1_500, run="first", key="first")
    assert no.value.code == "limit"
    unlimited = Gate(used_inr=9_999.0, limit_inr=None, pct=80)  # no limit set: the caps only
    await _reserve(c, 3, gate=unlimited, cap_inr=1_500, run="first", key="first")


async def test_an_unreadable_ledger_refuses_fail_closed() -> None:
    docs = MemoryDocs()
    c = _caps(docs=docs)
    await docs.transaction(_corrupt(c.path(UID, c.month_of(ist(2026, 11, 24, 10)))))
    with pytest.raises(CapRefused) as no:
        await _reserve(c, 1)
    assert no.value.code == "unreadable"


def _corrupt(path: str) -> Any:
    async def fn(tx: Any) -> None:
        tx.set(path, {"owner": UID, "spent_inr": float("inf"), "held_inr": 0.0})

    return fn


async def test_settle_old_turns_an_hour_old_hold_into_spend_at_its_hold() -> None:
    clock = FixedClock()
    c = _caps(clock)
    await _reserve(c, 1, run="first", key="first", cap_inr=1_500)
    clock.advance(minutes=61)
    assert await c.settle_old(UID) == 1
    m = await c.month(UID)
    assert m.spent_inr == pytest.approx(HOLD) and m.holds == {} and m.runs["first"] == HOLD


async def test_a_failed_close_is_kept_and_closed_later_as_it_was_meant() -> None:
    docs = MemoryDocs()
    c = _caps(docs=docs)
    h = await _reserve(c, 1)
    real = docs.transaction

    async def broken(fn: Any) -> Any:
        raise RuntimeError("store blip")

    docs.transaction = broken  # type: ignore[method-assign]
    with pytest.raises(RuntimeError):
        await c.release(h, waits=(0.0, 0.0))
    docs.transaction = real  # type: ignore[method-assign]
    assert await c.close_later(UID) == 1
    m = await c.month(UID)
    assert m.held_inr == 0.0 and m.spent_inr == 0.0


@pytest.mark.parametrize(
    ("at", "month"),
    [
        (ist(2026, 11, 30, 23, 30), "2026-11"),
        (ist(2026, 12, 1, 0, 30), "2026-12"),
        (ist(2027, 1, 1, 0, 5), "2027-01"),
        (ist(2028, 2, 29, 12, 0), "2028-02"),
    ],
)
def test_his_ist_month(at: Any, month: str) -> None:
    assert _caps().month_of(at) == month


async def test_the_month_before_is_read_for_an_hour_after_his_months_end() -> None:
    clock = FixedClock(ist(2026, 11, 30, 23, 50))
    c = _caps(clock)
    for n in range(8):
        await _reserve(c, n)
    clock.advance(minutes=20)  # 00:10 IST on 1 Dec: November's holds still count
    with pytest.raises(CapRefused):
        await _reserve(c, 9)
    clock.advance(minutes=60)  # 01:10: only December's
    await c.settle_old(UID)  # November's holds became spend at their holds (over an hour old)
    assert await c.run_spent(UID, "trial_x", "trial") == pytest.approx(0.0)
