# src/jarvis/billing/__init__.py
"""Costs in rupees, the monthly usage meter and the owner's limit (slice 7b).

Cross-cutting (observability: token & cost metering) with a Layer 4 guardrail (the spending
gate) and Layer 7 storage (Firestore counters). Vendor-neutral: it sees brain ids, model ids and
USD costs, never an SDK.
"""

from jarvis.billing.budget import BudgetPatch, BudgetRejected, BudgetStore
from jarvis.billing.fx import FxRates, Rate
from jarvis.billing.meter import MonthUsage, UsageMeter
from jarvis.billing.service import (
    Billing,
    BudgetError,
    BudgetReached,
    BudgetUnavailable,
    UsageView,
    build_billing,
    fx_client,
    rupees,
)

__all__ = [
    "Billing",
    "BudgetError",
    "BudgetPatch",
    "BudgetReached",
    "BudgetRejected",
    "BudgetStore",
    "BudgetUnavailable",
    "FxRates",
    "MonthUsage",
    "Rate",
    "UsageMeter",
    "UsageView",
    "build_billing",
    "fx_client",
    "rupees",
]
