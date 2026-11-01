# src/jarvis/billing/meter.py
"""The monthly usage meter (Layer 7: Firestore counters via the `Docs` port).

    {prefix}usage/{uid}_{YYYY-MM}   user_id, month, usd_total, inr_total, calls,
                                    by_brain {brain id: usd}, by_brain_inr {brain id: inr},
                                    units {key: amount}, updated_at

`units` (slice 9) counts usage that is free up to a monthly allowance and priced above it —
voice: "tts_chirp3-hd" / "tts_studio" characters, "stt_seconds". `add_units` prices only the part
of a call above the allowance, in the same transaction that counts it (concurrent calls can't
both use the last free units), and adds that cost to the totals under `label` ("voice").

The month is the owner's (JARVIS_USER_TIMEZONE): spend made at 00:10 IST on 1 December counts in
December. Every increment is a read-modify-write transaction (Firestore retries it on a
conflict), so concurrent replies never lose a call. Rupees are added at the rate of the moment
by the caller, so past spend does not change when the rate moves.

Fail closed: `inr_total` is what the owner's limit is compared with, so an existing month whose
`inr_total` is not a finite number ≥ 0 is UNREADABLE (UsageUnreadable) — never "₹0 spent", and
never silently reset by the next increment. The other fields are only shown and read leniently.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field, replace
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from jarvis.storage.docs import Docs, DocTx
from jarvis.storage.sessions import safe_id

_MONTH = re.compile(r"\d{4}-(0[1-9]|1[0-2])")
_BRAIN = re.compile(r"[A-Za-z0-9_-]{1,64}")
_UNIT_KEY = re.compile(r"[a-z0-9_-]{1,64}")
OTHER_BRAIN = "other"


def _zone(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        return ZoneInfo("UTC")


def _amount(v: object) -> float:
    """A stored money amount, or 0 when it is not a finite number ≥ 0."""
    if isinstance(v, bool) or not isinstance(v, int | float) or not math.isfinite(v) or v < 0:
        return 0.0
    return float(v)


class UsageUnreadable(RuntimeError):
    """This month's rupee total can't be read: the limit can't be checked (fail closed)."""


def _total(v: object) -> float:
    if isinstance(v, bool) or not isinstance(v, int | float) or not math.isfinite(v) or v < 0:
        raise UsageUnreadable("month total is not a finite number of rupees")
    return float(v)


def _amounts(v: object) -> dict[str, float]:
    if not isinstance(v, dict):
        return {}
    out = {str(k): _amount(x) for k, x in v.items() if _amount(x) > 0}
    return out


@dataclass(frozen=True)
class MonthUsage:
    month: str
    usd_total: float = 0.0
    inr_total: float = 0.0
    calls: int = 0
    by_brain: dict[str, float] = field(default_factory=dict)  # USD per brain id
    by_brain_inr: dict[str, float] = field(default_factory=dict)  # rupees per brain id
    units: dict[str, float] = field(default_factory=dict)  # allowance-metered usage (voice)

    def plus(self, brain_id: str, cost_usd: float, cost_inr: float) -> MonthUsage:
        key = brain_id if _BRAIN.fullmatch(brain_id) else OTHER_BRAIN
        return MonthUsage(
            month=self.month,
            usd_total=round(self.usd_total + cost_usd, 8),
            inr_total=round(self.inr_total + cost_inr, 6),
            calls=self.calls + 1,
            by_brain={**self.by_brain, key: round(self.by_brain.get(key, 0.0) + cost_usd, 8)},
            by_brain_inr={
                **self.by_brain_inr,
                key: round(self.by_brain_inr.get(key, 0.0) + cost_inr, 6),
            },
            units=self.units,
        )

    def with_units(self, key: str, amount: float) -> MonthUsage:
        return replace(self, units={**self.units, key: round(self.units.get(key, 0.0) + amount, 3)})


def priced_units(used: float, units: float, free: float) -> float:
    """The part of `units` above the free allowance, given `used` so far this month."""
    return max(0.0, units - max(0.0, free - used))


@dataclass(frozen=True)
class UnitCharge:
    """One allowance-metered call: how much of it was priced and what that cost."""

    units: float
    priced_units: float = 0.0
    usd: float = 0.0
    inr: float = 0.0


def decode(doc: dict[str, Any] | None, month: str) -> MonthUsage:
    """A stored month (None = nothing spent yet). Raises UsageUnreadable for a bad rupee total."""
    if doc is None:
        return MonthUsage(month)
    if not isinstance(doc, dict):
        raise UsageUnreadable("month document is not a map")
    calls = doc.get("calls")
    return MonthUsage(
        month=month,
        usd_total=_amount(doc.get("usd_total")),
        inr_total=_total(doc.get("inr_total")),
        calls=calls if isinstance(calls, int) and not isinstance(calls, bool) and calls > 0 else 0,
        by_brain=_amounts(doc.get("by_brain")),
        by_brain_inr=_amounts(doc.get("by_brain_inr")),
        units=_amounts(doc.get("units")),
    )


def encode(uid: str, m: MonthUsage, now: datetime) -> dict[str, Any]:
    """The stored month: every write goes through here, so no write drops another's field."""
    return {
        "user_id": uid,
        "month": m.month,
        "usd_total": m.usd_total,
        "inr_total": m.inr_total,
        "calls": m.calls,
        "by_brain": m.by_brain,
        "by_brain_inr": m.by_brain_inr,
        "units": m.units,
        "updated_at": now.isoformat(),
    }


class UsageMeter:
    def __init__(self, docs: Docs, *, prefix: str = "jarvis_", tz: str = "Asia/Kolkata") -> None:
        self._d = docs
        self._col = f"{prefix}usage"
        self._tz = _zone(tz)

    def month_of(self, now: datetime) -> str:
        return now.astimezone(self._tz).strftime("%Y-%m")

    def _path(self, uid: str, month: str) -> str:
        if not safe_id(uid):
            raise ValueError("invalid user id")
        if not _MONTH.fullmatch(month):
            raise ValueError("month must be YYYY-MM")
        return f"{self._col}/{uid}_{month}"

    async def get(self, uid: str, month: str) -> MonthUsage:
        return decode(await self._d.get(self._path(uid, month)), month)

    async def add(
        self, uid: str, *, brain_id: str, cost_usd: float, cost_inr: float, now: datetime
    ) -> MonthUsage:
        """One completion's cost, added in a transaction to the owner's month at `now`. Raises
        UsageUnreadable (writing nothing) when the stored month can't be read."""
        month = self.month_of(now)
        path = self._path(uid, month)

        async def fn(tx: DocTx) -> MonthUsage:
            new = decode(await tx.get(path), month).plus(brain_id, cost_usd, cost_inr)
            tx.set(path, encode(uid, new, now))
            return new

        return await self._d.transaction(fn)

    async def add_units(
        self,
        uid: str,
        *,
        key: str,
        units: float,
        free_units: float,
        usd_per_unit: float,
        inr_per_usd: float,
        label: str,
        now: datetime,
    ) -> UnitCharge:
        """Count `units` under `key` and price the part above `free_units` (this month's use
        read in the same transaction) at `usd_per_unit` × `inr_per_usd`; a priced call adds its
        cost to the totals as `label`. Raises UsageUnreadable (writing nothing) like `add`."""
        if not _UNIT_KEY.fullmatch(key):
            raise ValueError("invalid unit key")
        month = self.month_of(now)
        path = self._path(uid, month)

        async def fn(tx: DocTx) -> UnitCharge:
            cur = decode(await tx.get(path), month)
            priced = priced_units(cur.units.get(key, 0.0), units, free_units)
            usd = round(priced * usd_per_unit, 8)
            inr = round(usd * inr_per_usd, 6)
            new = (cur.plus(label, usd, inr) if usd > 0 else cur).with_units(key, units)
            tx.set(path, encode(uid, new, now))
            return UnitCharge(units=units, priced_units=priced, usd=usd, inr=inr)

        return await self._d.transaction(fn)


__all__ = ["MonthUsage", "UnitCharge", "UsageMeter", "UsageUnreadable", "priced_units"]
