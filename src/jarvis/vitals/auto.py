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
from jarvis.vitals.models import Kind, Provider, Spend

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


def _auto(
    pid: str,
    label: str,
    kind: Kind,
    unit: str,
    *,
    limit: float | None,
    used: float | None,
    reset_at: datetime | None,
    note: str = "",
) -> Provider:
    return Provider(
        id=pid,
        label=label,
        kind=kind,
        source="auto",
        limit=limit,
        used=used,
        unit=unit,
        reset_at=reset_at,
        note=note,
    )


async def spend(
    billing: BillingLike, uid: str, now: datetime, tz: ZoneInfo
) -> tuple[Provider, Spend | None]:
    reset = next_month_start(now, tz)

    def make(*, limit: float | None, used: float | None, note: str) -> Provider:
        return _auto(
            SPEND_ID, "AI spend this month", "billing", RUPEE,
            limit=limit, used=used, reset_at=reset, note=note,
        )  # fmt: skip

    try:
        view = await billing.usage(uid)
    except Exception as exc:  # noqa: BLE001 - unreadable meter: "unknown", never a failure
        log.warning("vitals: spend unreadable", extra={"reason": type(exc).__name__})
        return make(limit=None, used=None, note=UNREADABLE), None
    limit = view.limit_inr
    if view.limit_unreadable:  # the limit is unknown, so the status is too (paid replies pause)
        note = "The stored limit can't be read; paid replies are paused."
        return make(limit=None, used=None, note=note), Spend(
            used_inr=view.used_inr, limit_inr=limit, text=spend_text(view.used_inr, limit)
        )
    p = make(limit=None if limit is None else float(limit), used=view.used_inr, note="")
    return p, Spend(used_inr=view.used_inr, limit_inr=limit, text=spend_text(view.used_inr, limit))


async def quota(ledger: QuotaLedger, sku: Sku, now: datetime) -> Provider:
    pacific = ZoneInfo(PACIFIC)
    reset = next_month_start(now, pacific) if sku.period == "month" else next_midnight(now, pacific)
    pid = f"quota_{sku.id}"
    cap = float(sku.cap)
    try:
        use = await ledger.use(sku)
    except Exception as exc:  # noqa: BLE001
        log.warning("vitals: quota unreadable", extra={"sku": sku.id, "reason": type(exc).__name__})
        return _auto(
            pid, sku.label, "quota", sku.unit, limit=cap, used=None, reset_at=reset, note=UNREADABLE
        )
    used = cap if use.latched else float(use.used)
    return _auto(pid, sku.label, "quota", sku.unit, limit=cap, used=used, reset_at=reset)


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
        except Exception as exc:  # noqa: BLE001 - a bad counter reads as unknown
            log.warning(
                "vitals: allowance counter unreadable",
                extra={"key": s.key, "reason": type(exc).__name__},
            )
            used = None
    return _auto(
        f"allowance_{s.key}", s.label, "allowance", s.unit,
        limit=s.free_units, used=used, reset_at=reset,
        note="" if used is not None else UNREADABLE,
    )  # fmt: skip


__all__ = [
    "SPEND_ID",
    "AllowanceSpec",
    "BillingLike",
    "allowances",
    "quota",
    "spend",
    "spend_text",
]
