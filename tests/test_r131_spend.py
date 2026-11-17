# tests/test_r131_spend.py -- R13.1 I0 seam 8 (docs/plans/r13-1-try-on.md D13.4, D15): the overall
# monthly limit before a priced try-on picture. `ensure_spend_allowed` refuses a spend that would
# pass his limit (BudgetReached's words, "Raise it in Vitals."), fails closed when the limit or the
# month can't be read (BudgetUnavailable), and lets it through with no limit set.
from __future__ import annotations

from datetime import UTC, datetime

import pytest
from billing_fakes import billing, registry

from jarvis.billing.budget import BudgetPatch
from jarvis.billing.service import BudgetReached, BudgetUnavailable
from jarvis.billing.spend import ensure_spend_allowed
from jarvis.storage.docs import MemoryDocs, Set

UID = "owner-r131"
NOW = datetime(2026, 11, 17, 6, 0, tzinfo=UTC)  # 11:30 IST


def _billing(docs: MemoryDocs) -> object:
    return billing(registry(), docs=docs, clock=lambda: NOW)


async def _limit(b: object, inr: int) -> None:
    await b.budgets.update(UID, BudgetPatch(monthly_limit_inr=inr, confirm_raise=True), now=NOW)  # type: ignore[attr-defined]


async def _spent(b: object, inr: float) -> None:
    await b.meter.add(UID, brain_id="tryon", cost_usd=0.0, cost_inr=inr, now=NOW)  # type: ignore[attr-defined]


async def test_no_limit_lets_a_picture_through() -> None:
    b = _billing(MemoryDocs())
    await ensure_spend_allowed(b, UID, 11.22)  # type: ignore[arg-type]


async def test_a_spend_inside_his_limit_goes_ahead_and_one_past_it_is_refused() -> None:
    b = _billing(MemoryDocs())
    await _limit(b, 100)
    await _spent(b, 88.0)
    await ensure_spend_allowed(b, UID, 11.22)  # type: ignore[arg-type]  # 99.22 <= 100
    with pytest.raises(BudgetReached) as got:
        await ensure_spend_allowed(b, UID, 12.5)  # type: ignore[arg-type]  # 100.5 > 100
    words = str(got.value)
    assert "₹100" in words and "Raise it in Vitals." in words and "free brain" not in words


async def test_an_unreadable_limit_refuses_fail_closed() -> None:
    docs = MemoryDocs()
    b = _billing(docs)
    await docs.write([Set("jarvis_budget/" + UID, {"user_id": UID, "monthly_limit_inr": "lots"})])
    with pytest.raises(BudgetUnavailable) as got:
        await ensure_spend_allowed(b, UID, 1.0)  # type: ignore[arg-type]
    assert "nothing was sent" in str(got.value) and "free brain" not in str(got.value)


@pytest.mark.parametrize("bad", [-0.01, float("nan"), float("inf")])
async def test_a_spend_that_is_not_money_is_refused(bad: float) -> None:
    b = _billing(MemoryDocs())
    with pytest.raises(ValueError):
        await ensure_spend_allowed(b, UID, bad)  # type: ignore[arg-type]
