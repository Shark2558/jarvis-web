# src/jarvis/billing/service.py
"""Billing: the one spending gate, the meter hook and the owner's usage view (slice 7b).

    ensure_allowed(uid, brain) ─ before EVERY model call on a paid brain (chat, stream, tool
                                 rounds, approval narration, the brief's AI lines): this month's
                                 rupees ≥ the owner's limit → BudgetReached, no call.
    record(uid, brain, usd)    ─ after every completion with a cost: transactional increment at
                                 the rate of the moment. Never raises: a failed write is logged
                                 and the reply still goes out. Shielded from cancellation (a
                                 client that disconnects mid-stream cancels the response task;
                                 the provider still bills what it wrote).
    usage(uid) / set_limit()   ─ GET /v1/usage, PUT /v1/usage/budget.
    ensure_units_allowed /     ─ slice 9 voice: usage free up to a monthly allowance, priced
    record_units                 above it. The gate refuses only a call that would be priced
                                 (free calls still work at the limit); the recorder counts and
                                 prices in one transaction and never raises.

A brain is "paid" when any of its models is in the price table above zero; free (Gemini free
tier) and unpriced (custom) brains are never blocked. The check reads two documents (limit,
then this month) and only when a limit is set; it happens BEFORE the call, so one reply can go
over by its own cost. If those documents cannot be read — or hold a value that isn't a valid
limit / month total — no paid call is made (fail closed), and the usage view says so.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Literal

import anyio
import httpx
from pydantic import BaseModel

from jarvis.billing.budget import BudgetPatch, BudgetStore, LimitUnreadable
from jarvis.billing.fx import FETCH_TIMEOUT_S, FxRates
from jarvis.billing.meter import MonthUsage, UnitCharge, UsageMeter, UsageUnreadable
from jarvis.config import Settings
from jarvis.llm.brains import BrainRegistry, BrainSpec
from jarvis.llm.pricing import is_paid, is_priced
from jarvis.logging import get_logger
from jarvis.storage.docs import Docs, MemoryDocs

log = get_logger(__name__)

WARN_AT = 0.8  # the console turns amber at 80 % of the limit
METER_GRACE_S = 10.0  # how long a cancelled request still waits for its meter write
# Meter labels that are not brains (shown in GET /v1/usage by_brain).
LABELS = {"voice": "Voice"}


def utcnow() -> datetime:
    return datetime.now(UTC)


def _indian(n: int) -> str:
    """12345678 → "1,23,45,678" (Indian digit grouping)."""
    s = str(n)
    if len(s) <= 3:
        return s
    head, tail = s[:-3], s[-3:]
    groups: list[str] = []
    while len(head) > 2:
        groups.insert(0, head[-2:])
        head = head[:-2]
    return ",".join([head, *groups, tail])


def rupees(v: float) -> str:
    """ "₹500", "₹1,00,000", "₹25.50" — whole rupees without decimals, else two."""
    v = max(0.0, round(float(v), 2))  # float(): int.is_integer() exists only on Python 3.12+
    if v.is_integer():
        return "₹" + _indian(int(v))
    whole, frac = f"{v:.2f}".split(".")
    return f"₹{_indian(int(whole))}.{frac}"


class BudgetError(RuntimeError):
    """No paid model call was made because of the owner's monthly limit."""


class BudgetReached(BudgetError):
    """This month's limit is used up (→ 402 {"error": "budget_reached", "detail": …})."""

    def __init__(
        self, *, limit_inr: int, used_inr: float, free_brain: bool, detail: str | None = None
    ) -> None:
        self.limit_inr = limit_inr
        self.used_inr = used_inr
        tail = ", or switch to the free brain." if free_brain else "."
        super().__init__(
            detail
            or f"This month's limit of {rupees(limit_inr)} is used up ({rupees(used_inr)} spent). "
            f"Raise it in Vitals{tail}"
        )

    @property
    def brief_note(self) -> str:
        return (
            f"No AI summary: this month's limit of {rupees(self.limit_inr)} is used up "
            f"({rupees(self.used_inr)} spent). Raise it in Vitals; the facts above are complete."
        )


MSG_UNAVAILABLE = (
    "JARVIS couldn't check this month's spending limit just now, so it didn't call the paid AI. "
    "Try again in a minute, or switch to the free brain."
)
NOTE_UNAVAILABLE = (
    "No AI summary: JARVIS couldn't check this month's spending limit. The facts above are "
    "complete."
)
MSG_USAGE_UNREADABLE = (
    "This month's spending record can't be read, so JARVIS won't call the paid AI until it is "
    "fixed or the month turns. Free brains still answer."
)
MSG_USAGE_DOWN = "Couldn't read this month's spending just now. Try again in a minute."


class BudgetUnavailable(BudgetError):
    """The limit or this month's spend could not be read (→ 503): fail closed, no paid call."""

    def __init__(self, detail: str = MSG_UNAVAILABLE) -> None:
        super().__init__(detail)

    @property
    def brief_note(self) -> str:
        return NOTE_UNAVAILABLE


# ---- views ------------------------------------------------------------------------------------


class RateView(BaseModel):
    inr_per_usd: float
    as_of: str | None
    source: Literal["frankfurter", "cached", "default"]


class BrainUsage(BaseModel):
    brain: str
    label: str
    used_inr: float


class UsageView(BaseModel):
    month: str  # "2026-11", the owner's month
    used_inr: float
    limit_inr: int | None
    remaining_inr: float | None
    percent: float | None  # of the limit; can pass 100 (one reply may overshoot)
    warn: bool  # ≥ 80 % of the limit
    reached: bool  # ≥ the limit: paid brains are paused until the month turns or it is raised
    calls: int
    by_brain: list[BrainUsage]
    rate: RateView
    # The stored limit can't be read: paid brains are paused (fail closed) and any new limit
    # needs confirm_raise. limit_inr is None, but this is NOT "no limit".
    limit_unreadable: bool = False


def paid_brain(spec: BrainSpec) -> bool:
    return any(is_paid(m) for m in spec.tiers.values())


def free_brain(spec: BrainSpec) -> bool:
    """Known to cost nothing: every model priced, at zero. (Unpriced is "cost unknown".)"""
    return all(is_priced(m) and not is_paid(m) for m in spec.tiers.values())


class Billing:
    def __init__(
        self,
        *,
        fx: FxRates,
        meter: UsageMeter,
        budgets: BudgetStore,
        brains: BrainRegistry,
        clock: Callable[[], datetime] = utcnow,
    ) -> None:
        self.fx = fx
        self.meter = meter
        self.budgets = budgets
        self.brains = brains
        self.clock = clock

    @classmethod
    def in_memory(cls, brains: BrainRegistry, settings: Settings) -> Billing:
        """No persistence, no network: for a Brain built without the app (CLI tests, evals)."""
        docs = MemoryDocs()
        return cls(
            fx=FxRates(docs=None, http=None, default_rate=settings.usd_inr_rate),
            meter=UsageMeter(docs, tz=settings.user_timezone),
            budgets=BudgetStore(docs),
            brains=brains,
        )

    # ---- the gate ------------------------------------------------------------------------------

    async def ensure_allowed(self, uid: str, spec: BrainSpec) -> None:
        """The spending gate. Raises BudgetReached / BudgetUnavailable; returns when a call on
        `spec` may go ahead."""
        if not paid_brain(spec):
            return
        try:
            limit = await self.budgets.get(uid)
            if limit is None:
                return
            used = (await self.meter.get(uid, self.meter.month_of(self.clock()))).inr_total
        except Exception as exc:  # noqa: BLE001 — fail closed: no paid call we can't account for
            log.error(
                "LIMIT CHECK FAILED; no paid call made",
                extra={"brain": spec.id, "reason": type(exc).__name__},
            )
            raise BudgetUnavailable() from None
        if used >= limit:
            log.info(
                "monthly limit reached; paid call refused",
                extra={"brain": spec.id, "limit_inr": limit, "used_inr": round(used, 2)},
            )
            raise BudgetReached(limit_inr=limit, used_inr=used, free_brain=self._has_free())

    def _has_free(self) -> bool:
        return any(free_brain(b) for b in self.brains.list())

    async def ensure_units_allowed(
        self, uid: str, *, key: str, units: float, free_units: float
    ) -> None:
        """The spending gate for allowance-metered usage (voice). A call the free allowance
        still covers always goes ahead; one that would be priced is gated like a paid brain
        (BudgetReached / BudgetUnavailable). Fails closed only when it can't tell."""
        month = self.meter.month_of(self.clock())
        try:
            m: MonthUsage | None = await self.meter.get(uid, month)
        except Exception:  # noqa: BLE001 — unreadable month: decided below, with the limit
            m = None
        if m is not None and m.units.get(key, 0.0) + units <= free_units:
            return
        try:
            limit = await self.budgets.get(uid)
        except Exception as exc:  # noqa: BLE001 — fail closed: no priced call we can't account
            log.error(
                "LIMIT CHECK FAILED; no priced voice call", extra={"reason": type(exc).__name__}
            )
            raise BudgetUnavailable() from None
        if limit is None:
            return
        if m is None:
            log.error("MONTH UNREADABLE; no priced voice call", extra={"month": month})
            raise BudgetUnavailable() from None
        if m.inr_total >= limit:
            log.info(
                "monthly limit reached; priced voice call refused",
                extra={"limit_inr": limit, "used_inr": round(m.inr_total, 2)},
            )
            raise BudgetReached(
                limit_inr=limit,
                used_inr=m.inr_total,
                free_brain=False,
                detail=(
                    f"This month's limit of {rupees(limit)} is used up ({rupees(m.inr_total)} "
                    "spent) and the free cloud-voice allowance is too. The browser's own voice "
                    "and speech recognition still work; raise the limit in Vitals for the cloud "
                    "voice."
                ),
            )

    # ---- metering ------------------------------------------------------------------------------

    async def record(self, uid: str, brain_id: str, cost_usd: float) -> float:
        """Add one completion to this month. Returns its rupee estimate. Never raises, and is
        not cut short by the caller's cancellation (bounded by METER_GRACE_S)."""
        if not isinstance(cost_usd, int | float) or not math.isfinite(cost_usd) or cost_usd <= 0:
            return 0.0
        inr = 0.0
        with anyio.move_on_after(METER_GRACE_S, shield=True) as scope:
            inr = await self.inr(cost_usd)
            try:
                await self.meter.add(
                    uid, brain_id=brain_id, cost_usd=cost_usd, cost_inr=inr, now=self.clock()
                )
            except Exception as exc:  # noqa: BLE001 — the reply matters more than the counter
                log.error(
                    "USAGE METER WRITE FAILED; reply still sent",
                    extra={"brain": brain_id, "cost_usd": cost_usd, "reason": type(exc).__name__},
                )
        if scope.cancelled_caught:
            log.error(
                "USAGE METER WRITE TIMED OUT; reply still sent",
                extra={"brain": brain_id, "cost_usd": cost_usd},
            )
        return inr

    async def record_units(
        self,
        uid: str,
        *,
        key: str,
        units: float,
        free_units: float,
        usd_per_unit: float,
        label: str,
    ) -> UnitCharge:
        """Count one allowance-metered call (voice) and price what is above the allowance at
        today's rate. Never raises; not cut short by cancellation (like `record`)."""
        charge = UnitCharge(units=units)
        with anyio.move_on_after(METER_GRACE_S, shield=True) as scope:
            try:
                rate = (await self.fx.rate()).inr_per_usd
            except Exception:  # noqa: BLE001 — FxRates never raises; belt and braces
                rate = self.fx.peek().inr_per_usd
            try:
                charge = await self.meter.add_units(
                    uid,
                    key=key,
                    units=units,
                    free_units=free_units,
                    usd_per_unit=usd_per_unit,
                    inr_per_usd=rate,
                    label=label,
                    now=self.clock(),
                )
            except Exception as exc:  # noqa: BLE001 — the audio matters more than the counter
                log.error(
                    "USAGE METER WRITE FAILED (voice); result still sent",
                    extra={"key": key, "units": units, "reason": type(exc).__name__},
                )
        if scope.cancelled_caught:
            log.error("USAGE METER WRITE TIMED OUT (voice)", extra={"key": key, "units": units})
        return charge

    async def month(self, uid: str) -> MonthUsage:
        """This month's record (voice view). BudgetUnavailable when it can't be read."""
        _, _, m = await self._read(uid, self.meter.month_of(self.clock()))
        return m

    async def inr(self, usd: float) -> float:
        """Display conversion at the current rate (never waits on the network)."""
        if not isinstance(usd, int | float) or not math.isfinite(usd) or usd <= 0:
            return 0.0
        try:
            rate = (await self.fx.rate()).inr_per_usd
        except Exception:  # noqa: BLE001 — FxRates never raises; belt and braces
            rate = self.fx.peek().inr_per_usd
        return round(usd * rate, 6)

    # ---- the owner's view ----------------------------------------------------------------------

    async def _read(self, uid: str, month: str) -> tuple[int | None, bool, MonthUsage]:
        """(limit, limit unreadable?, month) for the view; BudgetUnavailable (plain words) when
        the month can't be read or storage is down."""
        try:
            try:
                limit, unreadable = await self.budgets.get(uid), False
            except LimitUnreadable:
                limit, unreadable = None, True
            return limit, unreadable, await self.meter.get(uid, month)
        except UsageUnreadable:
            log.error("MONTH TOTAL UNREADABLE; paid calls stay off", extra={"month": month})
            raise BudgetUnavailable(MSG_USAGE_UNREADABLE) from None
        except Exception as exc:  # noqa: BLE001 — storage down: say so, never a 500 with its text
            log.error("usage view unreadable", extra={"reason": type(exc).__name__})
            raise BudgetUnavailable(MSG_USAGE_DOWN) from None

    async def usage(self, uid: str) -> UsageView:
        rate = await self.fx.refresh()
        month = self.meter.month_of(self.clock())
        limit, unreadable, m = await self._read(uid, month)
        used = round(m.inr_total, 2)
        labels = {**LABELS, **{b.id: b.label for b in self.brains.list()}}
        by_brain = sorted(
            (
                BrainUsage(brain=b, label=labels.get(b, b), used_inr=round(v, 2))
                for b, v in m.by_brain_inr.items()
            ),
            key=lambda x: (-x.used_inr, x.brain),
        )
        return UsageView(
            month=month,
            used_inr=used,
            limit_inr=limit,
            remaining_inr=None if limit is None else round(max(0.0, limit - m.inr_total), 2),
            percent=None if limit is None else round(m.inr_total / limit * 100, 2),
            warn=limit is not None and m.inr_total >= WARN_AT * limit,
            reached=limit is not None and m.inr_total >= limit,
            calls=m.calls,
            by_brain=by_brain,
            rate=RateView(inr_per_usd=rate.inr_per_usd, as_of=rate.as_of, source=rate.source),
            limit_unreadable=unreadable,
        )

    async def set_limit(self, uid: str, patch: BudgetPatch) -> UsageView:
        await self.budgets.update(uid, patch, now=self.clock())
        return await self.usage(uid)


def build_billing(
    s: Settings, docs: Docs, brains: BrainRegistry, *, http: httpx.AsyncClient | None
) -> Billing:
    return Billing(
        fx=FxRates(docs=docs, http=http, prefix=s.firestore_prefix, default_rate=s.usd_inr_rate),
        meter=UsageMeter(docs, prefix=s.firestore_prefix, tz=s.user_timezone),
        budgets=BudgetStore(docs, prefix=s.firestore_prefix),
        brains=brains,
    )


def fx_client(s: Settings) -> httpx.AsyncClient | None:
    """The one HTTP client for the daily rate (None when JARVIS_USD_INR_LIVE is off)."""
    if not s.usd_inr_live:
        return None
    return httpx.AsyncClient(timeout=FETCH_TIMEOUT_S, follow_redirects=False)


__all__ = [
    "Billing",
    "BrainUsage",
    "BudgetError",
    "BudgetReached",
    "BudgetUnavailable",
    "RateView",
    "UsageView",
    "build_billing",
    "free_brain",
    "fx_client",
    "paid_brain",
    "rupees",
]
