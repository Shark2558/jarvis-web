# src/jarvis/billing/spend.py
"""R13.1 I0 seam 8 (docs/plans/r13-1-try-on.md D13.4, D15): money helpers for a priced action that
is not a brain call (a "See it on me" picture).

- `with_tax(inr, pct)`: a ₹ figure with GST added, to the paise (every ₹ shown for a try-on
  picture and its monthly cap include `tryon_tax_pct`, M1). Not money (negative, NaN, infinite)
  or a rate outside 0-28 % is a ValueError.
- `ensure_spend_allowed(billing, uid, inr)`: his OVERALL monthly limit (Vitals) before the spend:
  refused when this month's use plus `inr` would pass it (`BudgetReached`, "Raise it in Vitals."),
  fail closed when the limit or the month can't be read (`BudgetUnavailable`), and no limit set
  lets it through. The try-on cap is a second, separate gate (Part C's `TryonCap`).
"""

from __future__ import annotations

import math

from jarvis.billing.service import Billing, BudgetReached, BudgetUnavailable
from jarvis.logging import get_logger

log = get_logger(__name__)
MAX_TAX_PCT = 28
MSG_SPEND_UNAVAILABLE = (
    "JARVIS couldn't check this month's spending limit just now, so nothing was sent. Try again "
    "in a minute."
)


def _money(inr: float) -> float:
    value = float(inr)
    if not math.isfinite(value) or value < 0:
        raise ValueError("a ₹ amount is a finite number of at least 0")
    return value


def with_tax(inr: float, pct: int) -> float:
    """`inr` with `pct` % GST, rounded to the paise (7.22 at 18 % is 8.52)."""
    if isinstance(pct, bool) or not isinstance(pct, int) or not 0 <= pct <= MAX_TAX_PCT:
        raise ValueError(f"GST is a whole per cent from 0 to {MAX_TAX_PCT}")
    return round(_money(inr) * (100 + pct) / 100 + 1e-9, 2)


async def ensure_spend_allowed(billing: Billing, uid: str, inr: float) -> None:
    """Raises BudgetReached / BudgetUnavailable; returns when `inr` more fits his monthly limit."""
    spend = _money(inr)
    try:
        limit = await billing.budgets.get(uid)
        if limit is None:
            return
        month = billing.meter.month_of(billing.clock())
        used = (await billing.meter.get(uid, month)).inr_total
    except Exception as exc:  # noqa: BLE001 - fail closed: no spend we can't account for
        log.error("LIMIT CHECK FAILED; no priced action made", extra={"reason": type(exc).__name__})
        raise BudgetUnavailable(MSG_SPEND_UNAVAILABLE) from None
    if used + spend > limit:
        log.info(
            "monthly limit reached; priced action refused",
            extra={"limit_inr": limit, "used_inr": round(used, 2)},
        )
        raise BudgetReached(limit_inr=limit, used_inr=used, free_brain=False)


__all__ = ["MAX_TAX_PCT", "MSG_SPEND_UNAVAILABLE", "ensure_spend_allowed", "with_tax"]
