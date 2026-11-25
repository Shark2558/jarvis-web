# src/jarvis/billing/service.py
"""Billing: the one spending gate, the meter hook and the owner's usage view (slice 7b).

    ensure_allowed(uid, brain) ─ before EVERY model call on a paid or unpriced brain (chat,
                                 stream, tool rounds, approval narration, the brief's AI lines):
                                 this month's counted rupees ≥ the owner's limit → BudgetReached,
                                 no call.
    record(uid, brain, usd)    ─ after every completion with a cost: transactional increment at
                                 the rate of the moment. Never raises: a failed write is logged
                                 and the reply still goes out. Shielded from cancellation (a
                                 client that disconnects mid-stream cancels the response task;
                                 the provider still bills what it wrote). Given the reply's model
                                 and usage, a reply whose price is unknown is counted as such;
                                 given a cost only (R6.4 I1: the background callers), a brain
                                 with a model of no known price counts one call at
                                 `pricing.UNREPORTED_CALL`.
    usage(uid) / set_limit()   ─ GET /v1/usage, PUT /v1/usage/budget.
    ensure_units_allowed /     ─ slice 9 voice: usage free up to a monthly allowance, priced
    record_units                 above it. The allowance is the deployment's (one counter,
                                 Pacific-time months, like Google's per-billing-account free
                                 tier); rupees are the owner's. The gate refuses only a call that
                                 would be priced (free calls still work at the limit); the
                                 recorder counts and prices in one transaction, never raises.

A brain is "paid" when any of its models is in the price table above zero; free brains (Gemini
free tier) are never blocked. R6.4 D9: a model with no known price (a custom vendor) is never
₹0. Its reply is counted as "price unknown" (replies and tokens) and, for the limit only, at the
dearest price JARVIS knows (`pricing.dearest`); the limit compares the priced rupees plus that
upper estimate (`MonthUsage.counted_inr`), so a brain without a price list stops at the owner's
limit, never past it, unless it costs more than the dearest known model. The check reads two
documents (limit, then this month) and only when a limit is set; it happens BEFORE the call, so
one reply can go over by its own cost. If those documents cannot be read — or hold a value that
isn't a valid limit / month total — no paid call is made (fail closed), and the usage view says so.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from typing import Literal, Protocol

import anyio
import httpx
from pydantic import BaseModel

from jarvis.billing.budget import BudgetPatch, BudgetStore, LimitUnreadable
from jarvis.billing.fx import FETCH_TIMEOUT_S, FxRates
from jarvis.billing.meter import (
    AllowanceUse,
    Hold,
    MonthUsage,
    UnitCharge,
    UsageMeter,
    UsageUnreadable,
)
from jarvis.config import Settings
from jarvis.llm.base import Usage
from jarvis.llm.brains import BrainRegistry, BrainSpec
from jarvis.llm.pricing import (
    UNREPORTED_CALL,
    dearest,
    is_paid,
    is_priced,
    price_unknown,
    priced_at,
)
from jarvis.logging import get_logger
from jarvis.storage.docs import Docs, MemoryDocs

log = get_logger(__name__)

WARN_AT = 0.8  # the console turns amber at 80 % of the limit
METER_GRACE_S = 10.0  # how long a cancelled request still waits for its meter write
# Meter labels that are not brains (shown in GET /v1/usage by_brain).
LABELS = {"voice": "Voice", "tryon": "Try-on", "book": "Book writer"}  # R13.1 "Try-on", R6.3


class Used(Protocol):
    """What a reply used: a `Completion`, or a stream's meter (`core.finish.StreamMeter`)."""

    @property
    def model(self) -> str: ...

    @property
    def usage(self) -> Usage | None: ...


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


def _spent(used_inr: float, unpriced_inr: float) -> str:
    """ "₹120 spent", plus the "price unknown" replies' upper estimate when there are any."""
    if unpriced_inr <= 0:
        return f"{rupees(used_inr)} spent"
    return (
        f"{rupees(used_inr)} spent, plus up to {rupees(unpriced_inr)} counted for replies whose "
        "price JARVIS doesn't know"
    )


class BudgetReached(BudgetError):
    """This month's limit is used up (→ 402 {"error": "budget_reached", "detail": …})."""

    def __init__(
        self,
        *,
        limit_inr: int,
        used_inr: float,
        free_brain: bool,
        detail: str | None = None,
        unpriced_inr: float = 0.0,
    ) -> None:
        self.limit_inr = limit_inr
        self.used_inr = used_inr
        self.unpriced_inr = unpriced_inr
        tail = ", or switch to the free brain." if free_brain else "."
        super().__init__(
            detail
            or f"This month's limit of {rupees(limit_inr)} is used up "
            f"({_spent(used_inr, unpriced_inr)}). Raise it in Vitals{tail}"
        )

    @property
    def brief_note(self) -> str:
        return (
            f"No AI summary: this month's limit of {rupees(self.limit_inr)} is used up "
            f"({_spent(self.used_inr, self.unpriced_inr)}). Raise it in Vitals; the facts above "
            "are complete."
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
MSG_ALLOWANCE_UNREADABLE = (
    "The free cloud-voice allowance record can't be read, so JARVIS won't make a priced voice "
    "call under your limit until it is fixed or the month turns. The browser's own voice works."
)


class BudgetUnavailable(BudgetError):
    """The limit or this month's spend could not be read (→ 503): fail closed, no paid call."""

    def __init__(self, detail: str = MSG_UNAVAILABLE) -> None:
        super().__init__(detail)

    @property
    def brief_note(self) -> str:
        return NOTE_UNAVAILABLE


class FreeAllowanceUsed(BudgetError):
    """A free-only voice call (R6.2 decision 4: a build book guest's cloud listening) the free
    allowance no longer covers: refused, never priced (→ 503 in the Book's own words)."""

    def __init__(self) -> None:
        super().__init__("This month's free allowance doesn't cover it, so nothing was sent.")


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
    # R6.4 D9: replies whose price is unknown, not in used_inr; unpriced_inr is them at the
    # dearest known price, which remaining_inr, percent, warn and reached count (as the gate does).
    unpriced_calls: int = 0
    unpriced_tokens: int = 0
    unpriced_inr: float = 0.0


def paid_brain(spec: BrainSpec) -> bool:
    return any(is_paid(m) for m in spec.tiers.values())


def unpriced_brain(spec: BrainSpec) -> bool:
    """A model of the brain has no known price (R6.4 D9): a cost of 0 from it says nothing."""
    name = getattr(spec.provider, "name", "")
    return any(price_unknown(m, name) for m in spec.tiers.values())


def metered_brain(spec: BrainSpec) -> bool:
    """The monthly limit applies: a model is priced above zero, or its price is unknown."""
    return paid_brain(spec) or unpriced_brain(spec)


def _tokens(usage: Usage) -> int:
    parts = (usage.input_tokens, usage.output_tokens, usage.cache_read_tokens)
    return sum(max(0, n) for n in (*parts, usage.cache_write_tokens))


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
        if not metered_brain(spec):
            return
        try:
            limit = await self.budgets.get(uid)
            if limit is None:
                return
            m = await self.meter.get(uid, self.meter.month_of(self.clock()))
        except Exception as exc:  # noqa: BLE001 — fail closed: no paid call we can't account for
            log.error(
                "LIMIT CHECK FAILED; no paid call made",
                extra={"brain": spec.id, "reason": type(exc).__name__},
            )
            raise BudgetUnavailable() from None
        if m.counted_inr >= limit:
            log.info(
                "monthly limit reached; paid call refused",
                extra={"brain": spec.id, "limit_inr": limit, "used_inr": round(m.counted_inr, 2)},
            )
            raise BudgetReached(
                limit_inr=limit,
                used_inr=m.inr_total,
                free_brain=self._has_free(),
                unpriced_inr=m.unpriced_inr,
            )

    def _has_free(self) -> bool:
        return any(free_brain(b) for b in self.brains.list())

    async def ensure_units_allowed(
        self, uid: str, *, key: str, units: float, free_units: float
    ) -> None:
        """The spending gate for allowance-metered usage (voice). A call the deployment's free
        allowance (this Pacific month) still covers always goes ahead; one that would be priced
        is gated like a paid brain against `uid`'s limit and IST month (BudgetReached /
        BudgetUnavailable). An allowance counter that can't be read counts as "priced": it
        fails closed only under a limit."""
        now = self.clock()
        try:
            used: float | None = (
                await self.meter.allowance(self.meter.allowance_month_of(now))
            ).used(key)
        except Exception:  # noqa: BLE001 — can't tell: decided below, with the limit
            used = None
        if used is not None and used + units <= free_units:
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
        if used is None:
            log.error("ALLOWANCE UNREADABLE; no priced voice call", extra={"key": key})
            raise BudgetUnavailable()
        month = self.meter.month_of(now)
        try:
            m = await self.meter.get(uid, month)
        except Exception:  # noqa: BLE001 — fail closed
            log.error("MONTH UNREADABLE; no priced voice call", extra={"month": month})
            raise BudgetUnavailable() from None
        if m.counted_inr >= limit:
            log.info(
                "monthly limit reached; priced voice call refused",
                extra={"limit_inr": limit, "used_inr": round(m.counted_inr, 2)},
            )
            raise BudgetReached(
                limit_inr=limit,
                used_inr=m.inr_total,
                free_brain=False,
                unpriced_inr=m.unpriced_inr,
                detail=(
                    f"This month's limit of {rupees(limit)} is used up "
                    f"({_spent(m.inr_total, m.unpriced_inr)}) and the free cloud-voice allowance "
                    "is too. The browser's own voice and speech recognition still work; raise "
                    "the limit in Vitals for the cloud voice."
                ),
            )

    async def reserve_free(self, *, key: str, units: float, free_units: float) -> Hold:
        """Free-only (R6.2 decision 4): hold `units` of the deployment's free allowance, checked
        and counted in one transaction, so two calls at the end of it cannot both pass; the call
        is never priced. Returns the Hold (it remembers its month). FreeAllowanceUsed when it
        doesn't fit; BudgetUnavailable (fail closed) when the counter can't be read."""
        try:
            hold = await self.meter.reserve_units(
                key=key, units=units, free_units=free_units, now=self.clock()
            )
        except UsageUnreadable:
            log.error("ALLOWANCE COUNTER UNREADABLE; free-only voice stays off", extra={"key": key})
            raise BudgetUnavailable(MSG_ALLOWANCE_UNREADABLE) from None
        except Exception as exc:  # noqa: BLE001 — storage down: say so
            log.error("allowance unreadable", extra={"reason": type(exc).__name__})
            raise BudgetUnavailable(MSG_USAGE_DOWN) from None
        if hold is None:
            log.info("free allowance used up; a free-only voice call refused", extra={"key": key})
            raise FreeAllowanceUsed()
        return hold

    async def release_free(self, hold: Hold) -> None:
        """Give back a hold whose call was never billed, to the month it was made in. Never
        raises (an unreleased hold only keeps the free allowance a little lower, the safe
        side)."""
        try:
            await self.meter.release_units(hold, now=self.clock())
        except Exception as exc:  # noqa: BLE001 — the answer matters more than the counter
            log.error(
                "free hold not released", extra={"key": hold.key, "reason": type(exc).__name__}
            )

    # ---- metering ------------------------------------------------------------------------------

    async def record(
        self, uid: str, brain_id: str, cost_usd: float, *, used: Used | None = None
    ) -> float:
        """Add one completion to this month. Returns its rupee estimate. Never raises, and is
        not cut short by the caller's cancellation (bounded by METER_GRACE_S). `used`: the reply
        (its model and usage); with no cost and no known price it is counted as "price unknown".
        R6.4 I1: a caller that passes a cost only (the background callers) on a brain with a
        model of no known price is counted the same way, as one call at `UNREPORTED_CALL`."""
        if not isinstance(cost_usd, int | float) or not math.isfinite(cost_usd) or cost_usd <= 0:
            await self._no_cost(uid, brain_id, used)
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

    def _unknown(self, brain_id: str, used: Used) -> bool:
        """No price for the reply's model, and not the laptop's offline answer nor a provider that
        calls no vendor. A stream's meter names no provider: the brain's own is used."""
        if getattr(used, "offline", False):
            return False
        provider = getattr(used, "provider", "")
        if not provider:
            try:
                provider = getattr(self.brains.get(brain_id).provider, "name", "")
            except LookupError:
                provider = ""
        return price_unknown(used.model, provider)

    async def _no_cost(self, uid: str, brain_id: str, used: Used | None) -> None:
        """A call that came with no cost: "price unknown" when its price can't be told (never
        ₹0), with its tokens when they were reported, else as one call at `UNREPORTED_CALL`. A
        brain priced at ₹0, a paid one with nothing spent and a label naming no brain are not."""
        if used is not None:
            if not self._unknown(brain_id, used):
                return
            await self._record_unpriced(uid, brain_id, used.model, used.usage)
            return
        try:
            spec = self.brains.get(brain_id)
        except LookupError:
            return  # a meter label ("memory", "voice"), not a brain: nothing to judge it by
        if unpriced_brain(spec):
            await self._record_unpriced(uid, brain_id, "", None)

    async def _record_unpriced(
        self, uid: str, brain_id: str, model: str, usage: Usage | None
    ) -> None:
        """One "price unknown" reply: its tokens, and them at the dearest known price for the
        limit; with no tokens reported, no tokens and one call at `UNREPORTED_CALL`. Never
        raises; not cut short by cancellation (like `record`)."""
        tokens = _tokens(usage) if usage is not None else 0
        priced = usage if usage is not None and tokens > 0 else UNREPORTED_CALL
        with anyio.move_on_after(METER_GRACE_S, shield=True) as scope:
            inr = await self.inr(priced_at(dearest(), priced))
            try:
                await self.meter.add_unpriced(uid, tokens=tokens, inr=inr, now=self.clock())
            except Exception as exc:  # noqa: BLE001 — the reply matters more than the counter
                log.error(
                    "USAGE METER WRITE FAILED (price unknown); reply still sent",
                    extra={"brain": brain_id, "model": model, "reason": type(exc).__name__},
                )
                return
        if scope.cancelled_caught:
            log.error("USAGE METER WRITE TIMED OUT (price unknown)", extra={"brain": brain_id})
            return
        log.warning(
            "reply with no known price; counted at the dearest known price",
            extra={"brain": brain_id, "model": model, "tokens": tokens},
        )

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

    async def allowance(self, keys: Sequence[str]) -> AllowanceUse:
        """The deployment's allowance use this Pacific month (voice view); every key in `keys`
        is readable. BudgetUnavailable (plain words) when it can't be read — never "0 used"."""
        month = self.meter.allowance_month_of(self.clock())
        try:
            a = await self.meter.allowance(month)
            for key in keys:
                a.used(key)
        except UsageUnreadable:
            log.error("ALLOWANCE COUNTER UNREADABLE; priced voice stays off", extra={"m": month})
            raise BudgetUnavailable(MSG_ALLOWANCE_UNREADABLE) from None
        except Exception as exc:  # noqa: BLE001 — storage down: say so
            log.error("allowance unreadable", extra={"reason": type(exc).__name__})
            raise BudgetUnavailable(MSG_USAGE_DOWN) from None
        return a

    def allowance_resets_at(self) -> datetime:
        return self.meter.allowance_resets_at(self.clock())

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
        used, counted = round(m.inr_total, 2), m.counted_inr
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
            remaining_inr=None if limit is None else round(max(0.0, limit - counted), 2),
            percent=None if limit is None else round(counted / limit * 100, 2),
            warn=limit is not None and counted >= WARN_AT * limit,
            reached=limit is not None and counted >= limit,
            calls=m.calls,
            by_brain=by_brain,
            rate=RateView(inr_per_usd=rate.inr_per_usd, as_of=rate.as_of, source=rate.source),
            limit_unreadable=unreadable,
            unpriced_calls=m.unpriced_calls,
            unpriced_tokens=m.unpriced_tokens,
            unpriced_inr=round(m.unpriced_inr, 2),
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
    "FreeAllowanceUsed",
    "RateView",
    "Used",
    "UsageView",
    "build_billing",
    "free_brain",
    "fx_client",
    "metered_brain",
    "paid_brain",
    "rupees",
]
