# src/jarvis/quota/ledger.py
"""The allowance ledger for Google's free tiers (slice 12 D2; Layer 7 via the `Docs` port).

    {prefix}api_quota/{sku}@{period}   sku, period, tz, used, closed_day?, latched?, updated_at

Google's free allowances belong to the billing account / Cloud project — the whole deployment,
however many owners — so there is ONE counter per SKU and period. JARVIS stops at 90 % of the
free allowance of the price list that applies to the billing account and never runs into paid
use (like web search, `jarvis.web.allowance`). The free allowances, per month
(developers.google.com/maps/billing-and-pricing/pricing-india and …/pricing, checked 2026-11-03):

    sku              Google SKU (what triggers it)                      India     global
    maps_search      Places API Text Search Pro (our Pro field mask)   35,000      5,000
    maps_route       Routes: Compute Routes Pro (TRAFFIC_AWARE, car)   35,000      5,000
    maps_route_2w    Routes: Compute Routes Enterprise (two-wheeler)    7,000      1,000
    maps_route_walk  Routes: Compute Routes Essentials (on foot)       70,000     10,000

and, per Pacific day whatever the billing country: youtube_search 100 search.list calls (its own
bucket since 1 Jun 2026), youtube_units 10,000 other YouTube Data API units. India's price list
applies only to a billing account in India (`JARVIS_MAPS_PRICING=india`, set by deploy/cloudrun.sh
when the account bills in INR); the default is `global`, the low caps, so a wrong guess can only
stop early. Months and days are Pacific time (America/Los_Angeles), as Google bills Maps and
resets quotas.

Each call RESERVES first, in a transaction (two calls can't both take the last one), and is given
back (`refund`) only when Google clearly did not use it (`KeyAPIError.clear`). `latch` acts on
Google's own "quota gone" for the reservation's period, never the current one (a call made just
before midnight is answered just after): a per-month limit marks that month used up; a per-day
limit closes only that day (`closed_day` on the month's counter; for a daily SKU, the day itself).
Latch state only moves forward (code review CR-2): `closed_day` keeps the later of the stored day
and the call's, and a whole period Google closed is `latched` — a later refund gives nothing back.
A per-minute limit never latches (`jarvis.integrations.google_key` calls that "busy"). Fail
closed: an existing `used` that is not a finite whole number ≥ 0, a `closed_day` that is not a
date, or a `latched` that is not true / false, makes that SKU's period UNREADABLE — nothing is
called and the counter is never silently reset. The counter starts at 0 on the first deploy even if
the key was used elsewhere this period.
"""

from __future__ import annotations

import re
import time
from collections import deque
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal, get_args
from zoneinfo import ZoneInfo

from jarvis.quota.counter import Doc, counted, quietly, take
from jarvis.storage.docs import Docs

PACIFIC = "America/Los_Angeles"
HOUR_S = 3600.0
STOP_PERCENT = 90
Period = Literal["month", "day"]
Pricing = Literal["india", "global"]
UsedUp = Literal["day", "month"]  # which of Google's limits was hit
PRICINGS: tuple[Pricing, ...] = get_args(Pricing)
_DAY = re.compile(r"\d{4}-\d{2}-\d{2}")
_AGAIN: dict[Period, str] = {
    "month": "next month",
    "day": "after midnight Pacific time (12:30 or 1:30 pm India time)",
}


@dataclass(frozen=True)
class Sku:
    id: str
    label: str  # plain words for the owner, plural ("Maps searches")
    unit: str  # what one is, plural ("searches")
    period: Period
    free: int  # Google's free allowance per period on this price list

    @property
    def cap(self) -> int:
        """JARVIS's stop: 90 % of the free allowance."""
        return self.free * STOP_PERCENT // 100

    def when(self) -> str:
        return "this month" if self.period == "month" else "today"

    @property
    def reached(self) -> str:
        """What the owner is told when the stop is reached (built from the cap: one source)."""
        return (
            f"{self.label} are paused: {self.when()}'s {self.cap:,} free {self.unit} are used "
            f"up. They start again {_AGAIN[self.period]}."
        )

    @property
    def closed_today(self) -> str:
        """What the owner is told after Google said its per-day limit was reached."""
        return (
            f"{self.label} are paused for today: Google's daily limit for this project is "
            f"reached. They start again {_AGAIN['day']}."
        )


# (id, label, unit, period, {pricing: free allowance}) — see the module docstring for sources
_TABLE: tuple[tuple[str, str, str, Period, Mapping[Pricing, int]], ...] = (
    ("maps_search", "Maps searches", "searches", "month", {"india": 35_000, "global": 5_000}),
    ("maps_route", "Maps routes by car", "routes", "month", {"india": 35_000, "global": 5_000}),
    (
        "maps_route_2w",
        "Maps two-wheeler routes",
        "two-wheeler routes",
        "month",
        {"india": 7_000, "global": 1_000},
    ),
    (
        "maps_route_walk",
        "Maps walking routes",
        "walking routes",
        "month",
        {"india": 70_000, "global": 10_000},
    ),
    ("youtube_search", "YouTube searches", "searches", "day", {"india": 100, "global": 100}),
    ("youtube_units", "YouTube look-ups", "look-ups", "day", {"india": 10_000, "global": 10_000}),
)


def skus_for(pricing: Pricing) -> dict[str, Sku]:
    """Every SKU with the free allowance of Google's `pricing` price list."""
    if pricing not in PRICINGS:
        raise ValueError("pricing must be india or global")
    return {
        sid: Sku(sid, label, unit, per, free[pricing]) for sid, label, unit, per, free in _TABLE
    }


SKUS: dict[str, Sku] = skus_for("global")  # the safe default; a ledger uses its own (`sku`)
MAPS_SEARCH = SKUS["maps_search"]
MAPS_ROUTE = SKUS["maps_route"]
MAPS_ROUTE_2W = SKUS["maps_route_2w"]
MAPS_ROUTE_WALK = SKUS["maps_route_walk"]
YOUTUBE_SEARCH = SKUS["youtube_search"]
YOUTUBE_UNITS = SKUS["youtube_units"]


class QuotaReached(RuntimeError):
    """The free allowance for this SKU and period is used up (plain words, never a price)."""


class QuotaUnreadable(RuntimeError):
    """The counter can't be read, so nothing is called (fail closed)."""


@dataclass(frozen=True)
class SkuUse:
    sku: Sku
    period: str
    used: int = 0
    closed_day: str | None = None  # the latest day Google's per-day limit closed (monthly SKUs)
    latched: bool = False  # Google said the whole period's quota is gone: no refund reopens it

    @property
    def left(self) -> int:
        return 0 if self.latched else max(0, self.sku.cap - self.used)

    @property
    def reached(self) -> bool:
        return self.left <= 0


@dataclass(frozen=True)
class Reservation:
    sku: Sku
    period: str  # the counter it was taken from: refund and latch touch only that one
    n: int
    left: int = 0  # what is left once this reservation is taken
    day: str = ""  # the Pacific day it was taken on (a per-day latch closes that day)


def _decode(doc: object, sku: Sku, period: str) -> SkuUse:
    found, used = counted(doc, "used", unreadable=QuotaUnreadable, what=f"the {sku.label} counter")
    closed = found.get("closed_day")
    if closed is not None and not (isinstance(closed, str) and _DAY.fullmatch(closed)):
        raise QuotaUnreadable(f"the {sku.label} counter's closed day is not a date")
    latched = found.get("latched", False)
    if not isinstance(latched, bool):
        raise QuotaUnreadable(f"the {sku.label} counter's latch is not yes or no")
    return SkuUse(sku, period, used, closed, latched)


def unreadable_message(sku: Sku) -> str:
    return (
        f"{sku.label} are paused: JARVIS can't read {sku.when()}'s count, so nothing was sent "
        "to Google."
    )


Answer = dict[str, Any]
Run = Callable[[Answer], Awaitable[Answer]]


def stops_answered(run: Run) -> Run:
    """A tool run whose allowance stop is an ANSWER, not a failure (code review CR-3):
    QuotaReached → {status: "paused", message}, QuotaUnreadable → {status: "unreadable",
    message}, the way a missing Grant is {status: "permission_needed"}. The message is our own
    plain words (the SKU's `reached` / `closed_today` / `unreadable_message`), reaching the model
    whole — a failure's text is cut at 160 characters and starts "The tool failed"."""

    async def answered(args: Answer) -> Answer:
        try:
            return await run(args)
        except QuotaReached as exc:
            return {"status": "paused", "message": str(exc)}
        except QuotaUnreadable as exc:
            return {"status": "unreadable", "message": str(exc)}

    return answered


class QuotaLedger:
    def __init__(
        self,
        docs: Docs,
        *,
        pricing: Pricing = "global",
        prefix: str = "jarvis_",
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.docs = docs
        self.pricing: Pricing = pricing
        self.skus = skus_for(pricing)
        self._col = f"{prefix}api_quota"
        self._tz = ZoneInfo(PACIFIC)
        self.tz_name = PACIFIC
        self._now = now

    def sku(self, ref: Sku | str) -> Sku:
        """This ledger's SKU (its price list's cap) for a SKU or its id."""
        sid = ref.id if isinstance(ref, Sku) else ref
        if sid not in self.skus:
            raise ValueError("unknown quota sku")
        return self.skus[sid]

    def _local(self) -> datetime:
        return self._now().astimezone(self._tz)

    def period_key(self, sku: Sku) -> str:
        return self._local().strftime("%Y-%m" if sku.period == "month" else "%Y-%m-%d")

    def day_key(self) -> str:
        return self._local().strftime("%Y-%m-%d")

    def _path(self, sku: Sku, period: str) -> str:
        return f"{self._col}/{self.sku(sku).id}@{period}"

    def _encode(self, use: SkuUse) -> Doc:
        out: Doc = {
            "sku": use.sku.id,
            "period": use.period,
            "tz": self.tz_name,
            "used": use.used,
            "updated_at": self._now().isoformat(),
        }
        if use.closed_day is not None:
            out["closed_day"] = use.closed_day
        if use.latched:
            out["latched"] = True
        return out

    async def use(self, sku: Sku | str) -> SkuUse:
        s = self.sku(sku)
        period = self.period_key(s)
        return _decode(await self.docs.get(self._path(s, period)), s, period)

    async def reserve(self, sku: Sku | str, n: int = 1) -> Reservation:
        """Take `n` from this period before a call. QuotaReached (nothing taken) when they are
        not there or Google closed today; QuotaUnreadable when the counter can't be read."""
        if n < 1:
            raise ValueError("reserve at least one")
        s = self.sku(sku)
        local = self._local()
        period = local.strftime("%Y-%m" if s.period == "month" else "%Y-%m-%d")
        day = local.strftime("%Y-%m-%d")

        def step(doc: object) -> tuple[Doc, Reservation]:
            use = _decode(doc, s, period)
            if use.closed_day == day:
                raise QuotaReached(s.closed_today)
            if use.latched or use.used + n > s.cap:
                raise QuotaReached(s.reached)
            new = SkuUse(s, period, use.used + n, use.closed_day)
            return self._encode(new), Reservation(s, period, n, new.left, day)

        return await take(self.docs, self._path(s, period), step)

    async def refund(self, r: Reservation) -> None:
        """Google clearly did not use the call: give its reservation back to the period it was
        taken from (never below 0; a closed day stays closed; a period Google said is used up
        stays used up — code review CR-2). Never raises."""

        def step(doc: object) -> Doc | None:
            use = _decode(doc, r.sku, r.period)
            if use.latched:
                return None  # nothing to give back: the period is closed whatever the count
            back = SkuUse(r.sku, r.period, max(0, use.used - r.n), use.closed_day)
            return self._encode(back)

        await quietly(
            self.docs,
            self._path(r.sku, r.period),
            step,
            event="quota refund failed",
            extra={"sku": r.sku.id},
        )

    async def latch(self, r: Reservation, limit: UsedUp) -> None:
        """Google says the quota `r` was taken against is gone. A per-month limit (or any limit
        on a daily SKU) marks r's period used up for good (`latched`: no refund reopens it); a
        per-day limit on a monthly SKU closes only r's day — and never moves `closed_day` back
        (code review CR-2: yesterday's late answer must not reopen today, which a later call
        closed). Repairs an unreadable counter to "used up", which keeps it closed. Never
        raises."""
        sku = self.sku(r.sku)
        whole_period = limit == "month" or sku.period == "day"
        day = r.day or (r.period if sku.period == "day" else self.day_key())

        def step(doc: object) -> Doc:
            try:
                use = _decode(doc, sku, r.period)
            except QuotaUnreadable:
                return self._encode(SkuUse(sku, r.period, sku.cap, latched=True))
            if whole_period:
                used = max(use.used, sku.cap)
                return self._encode(SkuUse(sku, r.period, used, use.closed_day, latched=True))
            closed = max(use.closed_day, day) if use.closed_day else day  # ISO days sort as text
            return self._encode(SkuUse(sku, r.period, use.used, closed, use.latched))

        await quietly(
            self.docs,
            self._path(sku, r.period),
            step,
            event="quota latch failed",
            extra={"sku": sku.id},
        )

    async def view(self) -> dict[str, dict[str, Any]]:
        """Every SKU's count for its current period. An unreadable counter is said so (used and
        left null), never shown as 0. `paused_today`: Google's per-day limit closed today."""
        out: dict[str, dict[str, Any]] = {}
        today = self.day_key()
        for sku in self.skus.values():
            period = self.period_key(sku)
            try:
                use = await self.use(sku)
            except QuotaUnreadable:
                out[sku.id] = {
                    "period": period,
                    "used": None,
                    "limit": sku.cap,
                    "left": None,
                    "reached": False,
                    "paused_today": False,
                    "unreadable": True,
                }
                continue
            paused = use.closed_day == today
            out[sku.id] = {
                "period": period,
                "used": use.used,
                "limit": sku.cap,
                "left": use.left,
                "reached": use.reached or paused,
                "paused_today": paused,
                "unreadable": False,
            }
        return out


@dataclass
class HourlyCounter:
    """Calls per owner in the last hour. In-process: production runs ONE instance."""

    clock: Callable[[], float] = time.monotonic
    _recent: dict[str, deque[float]] = field(default_factory=dict)

    def last_hour(self, uid: str) -> int:
        q = self._recent.setdefault(uid, deque())
        now = self.clock()
        while q and now - q[0] >= HOUR_S:
            q.popleft()
        return len(q)

    def count(self, uid: str) -> None:
        self._recent.setdefault(uid, deque()).append(self.clock())


__all__ = [
    "MAPS_ROUTE",
    "MAPS_ROUTE_2W",
    "MAPS_ROUTE_WALK",
    "MAPS_SEARCH",
    "PACIFIC",
    "PRICINGS",
    "SKUS",
    "STOP_PERCENT",
    "YOUTUBE_SEARCH",
    "YOUTUBE_UNITS",
    "HourlyCounter",
    "Pricing",
    "QuotaLedger",
    "QuotaReached",
    "QuotaUnreadable",
    "Reservation",
    "Sku",
    "SkuUse",
    "UsedUp",
    "skus_for",
    "stops_answered",
    "unreadable_message",
]
