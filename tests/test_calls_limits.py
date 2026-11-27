# tests/test_calls_limits.py — R18 A1: the call limits and caps (calls.limits), checked at his
# tap and again at dial time, the dial counted in the same transaction as the limits.
from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import pytest

from jarvis.calls.limits import (
    BillingBudget,
    LimitRefused,
    Limits,
    cap_reached,
    in_quiet_hours,
    ist_day,
    ist_month,
)
from jarvis.calls.models import CallCard, CallSettings, CardLimits, EndReason
from jarvis.calls.store import MemoryCallStore

UID = "u_0123456789abcdef"
NUMBER = "+919000000001"
NOON_IST = datetime(2026, 11, 27, 6, 30, tzinfo=UTC)  # 12:00 IST


def _card(number: str = NUMBER, estimate: float | None = 2.0, **kw: object) -> CallCard:
    return CallCard(number_e164=number, purpose="Book a pickup", estimate_inr=estimate, **kw)  # type: ignore[arg-type]


class _Budget:
    def __init__(self, left: float | None = None, fail: bool = False) -> None:
        self.left, self.fail = left, fail

    async def left_inr(self, uid: str) -> float | None:
        if self.fail:
            raise RuntimeError("down")
        return self.left


def _limits(
    store: MemoryCallStore | None = None, now: datetime = NOON_IST, budget: _Budget | None = None
) -> tuple[Limits, MemoryCallStore]:
    store = store or MemoryCallStore()
    return Limits(store, budget=budget, clock=lambda: now), store


async def _refused(coro: object) -> LimitRefused:
    with pytest.raises(LimitRefused) as err:
        await coro  # type: ignore[misc]
    return err.value


def test_quiet_hours_are_21_to_8_ist() -> None:
    assert in_quiet_hours(datetime(2026, 11, 27, 15, 30, tzinfo=UTC))  # 21:00 IST
    assert in_quiet_hours(datetime(2026, 11, 27, 2, 29, tzinfo=UTC))  # 07:59 IST
    assert not in_quiet_hours(datetime(2026, 11, 27, 2, 30, tzinfo=UTC))  # 08:00 IST
    assert not in_quiet_hours(datetime(2026, 11, 27, 15, 29, tzinfo=UTC))  # 20:59 IST


def test_the_day_and_month_are_ist() -> None:
    late = datetime(2026, 11, 30, 19, 0, tzinfo=UTC)  # 1 Dec 00:30 IST
    assert ist_day(late).isoformat() == "2026-12-01"
    assert ist_month(late) == "2026-12"


async def test_a_card_within_every_limit_passes_at_approval() -> None:
    limits, _ = _limits()
    await limits.check_approval(UID, _card())


async def test_no_call_in_quiet_hours_or_one_that_could_run_into_them() -> None:
    night = datetime(2026, 11, 27, 16, 0, tzinfo=UTC)  # 21:30 IST
    limits, _ = _limits(now=night)
    assert (await _refused(limits.check_approval(UID, _card()))).code == "quiet_hours"
    almost = datetime(2026, 11, 27, 15, 27, tzinfo=UTC)  # 20:57 IST, a 6-minute card
    limits, _ = _limits(now=almost)
    err = await _refused(limits.check_approval(UID, _card()))
    assert err.code == "quiet_hours" and "21:00" in err.words
    short = _card(limits=CardLimits(max_minutes=2))
    await limits.check_approval(UID, short)


async def test_an_unknown_estimate_is_never_free() -> None:
    limits, _ = _limits()
    assert (await _refused(limits.check_approval(UID, _card(estimate=None)))).code == (
        "cost_unknown"
    )


async def test_the_card_call_month_and_owner_caps() -> None:
    limits, store = _limits()
    over_card = _card(estimate=6.0, limits=CardLimits(max_inr=5))
    assert (await _refused(limits.check_approval(UID, over_card))).code == "card_cap"
    await store.save_settings(UID, {"call_cap_inr": 3})
    assert (await _refused(limits.check_approval(UID, _card(estimate=4.0)))).code == "call_cap"
    await store.save_settings(UID, {"call_cap_inr": 20, "month_cap_inr": 10})
    await store.add_spend(UID, "2026-11", 9.0)
    assert (await _refused(limits.check_approval(UID, _card()))).code == "month_cap"
    limits, _ = _limits(budget=_Budget(left=1.0))
    assert (await _refused(limits.check_approval(UID, _card()))).code == "owner_limit"


async def test_an_unreadable_budget_refuses() -> None:
    limits, _ = _limits(budget=_Budget(fail=True))
    assert (await _refused(limits.check_approval(UID, _card()))).code == "unreadable"


async def test_dials_are_counted_and_stop_at_two_a_number() -> None:
    limits, store = _limits()
    first = await limits.admit_dial(UID, _card())
    assert first.new_number and first.counts.calls == 1
    second = await limits.admit_dial(UID, _card())
    assert not second.new_number and second.counts.calls == 2
    err = await _refused(limits.admit_dial(UID, _card()))
    assert err.code == "number_limit"
    assert (await store.day_counts(UID, ist_day(NOON_IST))).calls == 2  # the refusal: not counted
    assert (await _refused(limits.check_approval(UID, _card()))).code == "number_limit"


async def test_ten_calls_a_day_and_three_new_numbers() -> None:
    limits, store = _limits()
    for n in range(3):
        await limits.admit_dial(UID, _card(f"+91900000001{n}"))
    err = await _refused(limits.admit_dial(UID, _card("+919000000019")))
    assert err.code == "new_numbers_limit"
    for n in range(3):  # the three are known now: a second call each still passes
        await limits.admit_dial(UID, _card(f"+91900000001{n}"))
    counts = await store.day_counts(UID, ist_day(NOON_IST))
    assert counts.calls == 6


async def test_the_tenth_call_is_the_last() -> None:
    limits, store = _limits()
    day = ist_day(NOON_IST)
    for n in range(10):  # ten known numbers called before (yesterday)
        await store.count_call(UID, day - timedelta(days=1), f"+91900000002{n}")
    for n in range(10):
        await limits.admit_dial(UID, _card(f"+91900000002{n}"))
    err = await _refused(limits.admit_dial(UID, _card("+919000000020")))
    assert err.code == "day_limit"


async def test_one_redial_a_day_to_a_number_that_did_not_answer() -> None:
    limits, store = _limits()
    await limits.admit_dial(UID, _card())
    await limits.no_answer(UID, NUMBER)
    await limits.admit_dial(UID, _card())  # the one redial
    await store.save_settings(UID, {})  # nothing else changes
    err = await _refused(limits.check_approval(UID, _card()))
    assert err.code in {"number_limit", "redial_limit"}


async def test_two_dials_racing_at_the_limit_cannot_both_pass() -> None:
    limits, store = _limits()
    await limits.admit_dial(UID, _card())
    results = await asyncio.gather(
        limits.admit_dial(UID, _card()), limits.admit_dial(UID, _card()), return_exceptions=True
    )
    assert sum(1 for r in results if isinstance(r, LimitRefused)) == 1
    assert (await store.day_counts(UID, ist_day(NOON_IST))).calls == 2


async def test_spend_is_added_to_the_ist_month() -> None:
    limits, store = _limits()
    assert await limits.add_spend(UID, 1.5) == 1.5
    assert await store.month_spend(UID, "2026-11") == 1.5


def test_caps_during_a_call() -> None:
    card, settings = _card(), CallSettings()
    assert cap_reached(card, settings, seconds=10, call_inr=0.5, month_inr=10) is None
    assert cap_reached(card, settings, seconds=360, call_inr=0, month_inr=0) is (
        EndReason.CAP_MINUTES
    )
    assert cap_reached(card, settings, seconds=10, call_inr=20, month_inr=0) is EndReason.CAP_INR
    assert cap_reached(card, settings, seconds=10, call_inr=1, month_inr=200) is (EndReason.CAP_INR)


class _Month:
    counted_inr = 2950.5


class _Budgets:
    def __init__(self, limit: int | None) -> None:
        self.limit = limit

    async def get(self, uid: str) -> int | None:
        return self.limit


class _Billing:
    def __init__(self, limit: int | None) -> None:
        self.budgets = _Budgets(limit)

    async def month(self, uid: str) -> _Month:
        return _Month()


async def test_the_owner_budget_reads_billing() -> None:
    assert await BillingBudget(_Billing(3000)).left_inr(UID) == pytest.approx(49.5)
    assert await BillingBudget(_Billing(None)).left_inr(UID) is None
