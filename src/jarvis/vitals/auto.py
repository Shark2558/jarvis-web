# src/jarvis/vitals/auto.py
"""`auto` providers: computed from the meters that already exist (R4 D2). Billing (this month's
rupees), the Google SKU ledger and the voice allowance. A meter that can't be read gives a record
with `used=None` (status "unknown"), never an exception."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Protocol
from zoneinfo import ZoneInfo

from jarvis.billing import UsageView
from jarvis.billing.meter import AllowanceUse
from jarvis.billing.service import rupees
from jarvis.logging import get_logger
from jarvis.quota.ledger import PACIFIC, QuotaLedger, Sku
from jarvis.vitals.models import Provider, Spend

log = get_logger(__name__)

SPEND_ID = "ai_spend"
RUPEE = "₹"
UNREADABLE = "Can't be read just now."


class BillingLike(Protocol):
    async def usage(self, uid: str) -> UsageView: ...

    async def allowance(self, keys: Sequence[str]) -> AllowanceUse: ...

    def allowance_resets_at(self) -> datetime: ...


@dataclass(frozen=True)
class AllowanceSpec:
    key: str  # the meter key (e.g. a voice price's key)
    label: str
    free_units: float
    unit: str


def next_month_start(now: datetime, tz: ZoneInfo) -> datetime:
    local = now.astimezone(tz)
    year, month = (local.year + 1, 1) if local.month == 12 else (local.year, local.month + 1)
    return datetime(year, month, 1, tzinfo=tz)


def next_midnight(now: datetime, tz: ZoneInfo) -> datetime:
    local = now.astimezone(tz)
    return datetime(local.year, local.month, local.day, tzinfo=tz) + timedelta(days=1)


def spend_text(used: float, limit: int | None) -> str:
    if limit is None:
        return f"{rupees(used)} this month, no limit set"
    return f"{rupees(used)} of {rupees(limit)} this month"


async def spend(
    billing: BillingLike, uid: str, now: datetime, tz: ZoneInfo
) -> tuple[Provider, Spend | None]:
    base = {
        "id": SPEND_ID,
        "label": "AI spend this month",
        "kind": "billing",
        "source": "auto",
        "unit": RUPEE,
        "reset_at": next_month_start(now, tz),
    }
    try:
        view = await billing.usage(uid)
    except Exception as exc:  # noqa: BLE001 - unreadable meter: "unknown", never a failure
        log.warning("vitals: spend unreadable", extra={"reason": type(exc).__name__})
        return Provider(**base, note=UNREADABLE), None  # type: ignore[arg-type]
    limit = view.limit_inr
    note = (
        "The stored limit can't be read; paid replies are paused." if view.limit_unreadable else ""
    )
    p = Provider(
        **base,  # type: ignore[arg-type]
        used=view.used_inr,
        limit=None if limit is None else float(limit),
        note=note,
    )
    return p, Spend(used_inr=view.used_inr, limit_inr=limit, text=spend_text(view.used_inr, limit))


async def quota(ledger: QuotaLedger, sku: Sku, now: datetime) -> Provider:
    pacific = ZoneInfo(PACIFIC)
    reset = next_month_start(now, pacific) if sku.period == "month" else next_midnight(now, pacific)
    base = {
        "id": f"quota_{sku.id}",
        "label": sku.label,
        "kind": "quota",
        "source": "auto",
        "unit": sku.unit,
        "limit": float(sku.cap),
        "reset_at": reset,
    }
    try:
        use = await ledger.use(sku)
    except Exception as exc:  # noqa: BLE001
        log.warning("vitals: quota unreadable", extra={"sku": sku.id, "reason": type(exc).__name__})
        return Provider(**base, note=UNREADABLE)  # type: ignore[arg-type]
    used = float(sku.cap) if use.latched else float(use.used)
    return Provider(**base, used=used)  # type: ignore[arg-type]


async def allowances(billing: BillingLike, specs: Sequence[AllowanceSpec]) -> list[Provider]:
    if not specs:
        return []
    try:
        reset: datetime | None = billing.allowance_resets_at()
        got: AllowanceUse | None = await billing.allowance([s.key for s in specs])
    except Exception as exc:  # noqa: BLE001
        log.warning("vitals: allowance unreadable", extra={"reason": type(exc).__name__})
        reset, got = None, None
    return [_allowance(s, got, reset) for s in specs]


def _allowance(s: AllowanceSpec, got: AllowanceUse | None, reset: datetime | None) -> Provider:
    used: float | None = None
    if got is not None:
        try:
            used = got.used(s.key)
        except Exception:  # noqa: BLE001 - a bad counter reads as unknown
            used = None
    return Provider(
        id=f"allowance_{s.key}",
        label=s.label,
        kind="allowance",
        source="auto",
        limit=s.free_units,
        used=used,
        unit=s.unit,
        reset_at=reset,
        note="" if used is not None else UNREADABLE,
    )


__all__ = [
    "SPEND_ID",
    "AllowanceSpec",
    "BillingLike",
    "allowances",
    "quota",
    "spend",
    "spend_text",
]
