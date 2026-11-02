# src/jarvis/quota/ledger.py
"""The allowance ledger for Google's free tiers (slice 12 D2; Layer 7 via the `Docs` port).

    {prefix}api_quota/{sku}@{period}   sku, period, tz, used, updated_at

Google's free allowances belong to the billing account / Cloud project — the whole deployment,
however many owners — so there is ONE counter per SKU and period. JARVIS stops at 90 % of the
free allowance and never runs into paid use (like web search, `jarvis.web.allowance`):

    maps_search     Places Text Search (New) Pro     31,500 / month   (35,000 free in India)
    maps_route      Routes computeRoutes Pro          31,500 / month   (TRAFFIC_AWARE)
    maps_geocode    Geocoding                         63,000 / month   (counted if ever used)
    youtube_search  YouTube search.list calls             90 / day     (its own 100/day bucket)
    youtube_units   other YouTube Data API units       9,000 / day     (of 10,000)

Months and days are Pacific time (America/Los_Angeles), as Google bills Maps and resets YouTube.

Each call RESERVES first, in a transaction (two calls can't both take the last one), and is given
back (`refund`) only when Google clearly did not use it (`KeyAPIError.clear`); `latch` marks the
period used up when Google itself says the quota is gone. Fail closed: an existing `used` that is
not a finite whole number ≥ 0 makes that SKU's period UNREADABLE — nothing is called and the counter
is never silently reset. The counter starts at 0 on the first deploy even if the key was used
elsewhere this period; the plan's optional per-day quotas in Cloud Console are extra brakes.
"""

from __future__ import annotations

import math
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal
from zoneinfo import ZoneInfo

from jarvis.logging import get_logger
from jarvis.storage.docs import Docs, DocTx

log = get_logger(__name__)

PACIFIC = "America/Los_Angeles"
HOUR_S = 3600.0
Period = Literal["month", "day"]


@dataclass(frozen=True)
class Sku:
    id: str
    label: str  # plain words for the owner ("Maps searches")
    cap: int  # JARVIS's stop: 90 % of the free allowance
    period: Period
    reached: str  # what the owner is told when the stop is reached

    def when(self) -> str:
        return "this month" if self.period == "month" else "today"


MAPS_SEARCH = Sku(
    "maps_search",
    "Maps searches",
    31_500,
    "month",
    "Maps place search is paused: this month's 31,500 free searches are used up. It starts "
    "again next month.",
)
MAPS_ROUTE = Sku(
    "maps_route",
    "Maps routes",
    31_500,
    "month",
    "Maps travel times are paused: this month's 31,500 free routes are used up. They start "
    "again next month.",
)
MAPS_GEOCODE = Sku(
    "maps_geocode",
    "Maps address look-ups",
    63_000,
    "month",
    "Maps address look-ups are paused: this month's 63,000 free look-ups are used up.",
)
YOUTUBE_SEARCH = Sku(
    "youtube_search",
    "YouTube searches",
    90,
    "day",
    "YouTube search is paused: today's 90 free searches are used up. It starts again after "
    "midnight Pacific time (about 1:30 pm India time).",
)
YOUTUBE_UNITS = Sku(
    "youtube_units",
    "YouTube look-ups",
    9_000,
    "day",
    "YouTube look-ups are paused: today's free allowance is used up. They start again after "
    "midnight Pacific time (about 1:30 pm India time).",
)
SKUS: dict[str, Sku] = {
    s.id: s for s in (MAPS_SEARCH, MAPS_ROUTE, MAPS_GEOCODE, YOUTUBE_SEARCH, YOUTUBE_UNITS)
}


class QuotaReached(RuntimeError):
    """The free allowance for this SKU and period is used up (plain words, never a price)."""


class QuotaUnreadable(RuntimeError):
    """The counter can't be read, so nothing is called (fail closed)."""


def _whole(v: object) -> bool:
    return (
        not isinstance(v, bool)
        and isinstance(v, int | float)
        and math.isfinite(v)
        and v >= 0
        and float(v).is_integer()
    )


@dataclass(frozen=True)
class SkuUse:
    sku: Sku
    period: str
    used: int = 0

    @property
    def left(self) -> int:
        return max(0, self.sku.cap - self.used)

    @property
    def reached(self) -> bool:
        return self.left <= 0


@dataclass(frozen=True)
class Reservation:
    sku: Sku
    period: str
    n: int
    left: int = 0  # what is left once this reservation is taken


def _decode(doc: object, sku: Sku, period: str) -> SkuUse:
    if doc is None:
        return SkuUse(sku, period)
    if not isinstance(doc, dict):
        raise QuotaUnreadable(f"the {sku.label} counter is not a document")
    raw = doc.get("used", 0)
    if not _whole(raw):
        raise QuotaUnreadable(f"the {sku.label} counter is not a whole number")
    return SkuUse(sku, period, int(raw))


def unreadable_message(sku: Sku) -> str:
    return (
        f"{sku.label} are paused: JARVIS can't read {sku.when()}'s count, so nothing was sent "
        "to Google."
    )


class QuotaLedger:
    def __init__(
        self,
        docs: Docs,
        *,
        prefix: str = "jarvis_",
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.docs = docs
        self._col = f"{prefix}api_quota"
        self._tz = ZoneInfo(PACIFIC)
        self.tz_name = PACIFIC
        self._now = now

    def period_key(self, sku: Sku) -> str:
        local = self._now().astimezone(self._tz)
        return local.strftime("%Y-%m" if sku.period == "month" else "%Y-%m-%d")

    def _path(self, sku: Sku, period: str) -> str:
        if sku.id not in SKUS:
            raise ValueError("unknown quota sku")
        return f"{self._col}/{sku.id}@{period}"

    def _encode(self, use: SkuUse) -> dict[str, Any]:
        return {
            "sku": use.sku.id,
            "period": use.period,
            "tz": self.tz_name,
            "used": use.used,
            "updated_at": self._now().isoformat(),
        }

    async def use(self, sku: Sku) -> SkuUse:
        period = self.period_key(sku)
        return _decode(await self.docs.get(self._path(sku, period)), sku, period)

    async def reserve(self, sku: Sku, n: int = 1) -> Reservation:
        """Take `n` from this period before a call. QuotaReached (nothing taken) when they are
        not there; QuotaUnreadable when the counter can't be read."""
        if n < 1:
            raise ValueError("reserve at least one")
        period = self.period_key(sku)
        path = self._path(sku, period)

        async def fn(tx: DocTx) -> Reservation:
            use = _decode(await tx.get(path), sku, period)
            if use.used + n > sku.cap:
                raise QuotaReached(sku.reached)
            new = SkuUse(sku, period, use.used + n)
            tx.set(path, self._encode(new))
            return Reservation(sku, period, n, new.left)

        return await self.docs.transaction(fn)

    async def refund(self, r: Reservation) -> None:
        """Google clearly did not use the call: give its reservation back (never below 0).
        Never raises (bookkeeping after a call never fails it)."""
        path = self._path(r.sku, r.period)

        async def fn(tx: DocTx) -> None:
            use = _decode(await tx.get(path), r.sku, r.period)
            tx.set(path, self._encode(SkuUse(r.sku, r.period, max(0, use.used - r.n))))

        try:
            await self.docs.transaction(fn)
        except Exception as exc:  # noqa: BLE001
            log.warning(
                "quota refund failed", extra={"sku": r.sku.id, "reason": type(exc).__name__}
            )

    async def latch(self, sku: Sku) -> None:
        """Google says the quota is gone: mark this period used up (repairs an unreadable
        counter to "used up", which keeps it closed). Never raises."""
        period = self.period_key(sku)
        path = self._path(sku, period)

        async def fn(tx: DocTx) -> None:
            await tx.get(path)  # reads before writes, as Firestore requires
            tx.set(path, self._encode(SkuUse(sku, period, sku.cap)))

        try:
            await self.docs.transaction(fn)
        except Exception as exc:  # noqa: BLE001
            log.warning("quota latch failed", extra={"sku": sku.id, "reason": type(exc).__name__})

    async def view(self) -> dict[str, dict[str, Any]]:
        """Every SKU's count for its current period. An unreadable counter is said so (used and
        left null), never shown as 0."""
        out: dict[str, dict[str, Any]] = {}
        for sku in SKUS.values():
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
                    "unreadable": True,
                }
                continue
            out[sku.id] = {
                "period": period,
                "used": use.used,
                "limit": sku.cap,
                "left": use.left,
                "reached": use.reached,
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
    "MAPS_GEOCODE",
    "MAPS_ROUTE",
    "MAPS_SEARCH",
    "PACIFIC",
    "SKUS",
    "YOUTUBE_SEARCH",
    "YOUTUBE_UNITS",
    "HourlyCounter",
    "QuotaLedger",
    "QuotaReached",
    "QuotaUnreadable",
    "Reservation",
    "Sku",
    "SkuUse",
    "unreadable_message",
]
