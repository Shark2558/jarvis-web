# src/jarvis/billing/meter.py
"""The monthly usage meter (Layer 7: Firestore counters via the `Docs` port).

    {prefix}usage/{uid}_{YYYY-MM}   user_id, month, usd_total, inr_total, calls,
                                    by_brain {brain id: usd}, by_brain_inr {brain id: inr},
                                    updated_at
    {prefix}allowance/{YYYY-MM}     month, tz, units {key: amount}, updated_at   (one per
                                    deployment, Pacific-time month)

The owner's month (JARVIS_USER_TIMEZONE) holds rupees: spend made at 00:10 IST on 1 December
counts in December. Every increment is a read-modify-write transaction (Firestore retries it on a
conflict), so concurrent replies never lose a call. Rupees are added at the rate of the moment
by the caller, so past spend does not change when the rate moves.

The allowance counter (slice 9 review) counts usage that a vendor gives free up to a monthly
allowance and prices above it — voice: "tts_chirp3-hd" / "tts_studio" characters,
"stt_seconds". Google's free tier is per BILLING ACCOUNT and resets on Pacific-time months, so
the counter is ONE document for the whole deployment (not per owner), keyed by the month in
America/Los_Angeles. `add_units` reads it, prices only the part of a call above the allowance,
adds that cost to the CALLER's IST month under `label` ("voice"), and counts the units — all in
one transaction, so two calls can't both use the last free units.

Fail closed: `inr_total` is what the owner's limit is compared with, so an existing month whose
`inr_total` is not a finite number ≥ 0 is UNREADABLE (UsageUnreadable) — never "₹0 spent", and
never silently reset by the next increment. The same holds for an allowance counter: a stored
value under a key that is not a finite number ≥ 0 makes THAT key unreadable (and is kept as it
is by writes to other keys); a `units` field that is not a map makes them all unreadable. The
other usage fields are only shown and read leniently.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from jarvis.storage.docs import Delete, Docs, DocTx, Query
from jarvis.storage.sessions import safe_id

_MONTH = re.compile(r"\d{4}-(0[1-9]|1[0-2])")
_BRAIN = re.compile(r"[A-Za-z0-9_-]{1,64}")
_UNIT_KEY = re.compile(r"[a-z0-9_-]{1,64}")
OTHER_BRAIN = "other"
# Google's free speech tiers reset at the start of each month, Pacific time.
ALLOWANCE_TZ = "America/Los_Angeles"


def _zone(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        return ZoneInfo("UTC")


def _valid(v: object) -> bool:
    """A finite number ≥ 0 (not a bool)."""
    return not isinstance(v, bool) and isinstance(v, int | float) and math.isfinite(v) and v >= 0


def _amount(v: object) -> float:
    """A stored money amount, or 0 when it is not a finite number ≥ 0."""
    return float(v) if _valid(v) else 0.0  # type: ignore[arg-type]


class UsageUnreadable(RuntimeError):
    """A rupee total or an allowance counter can't be read: the limit can't be checked, or the
    allowance can't be told (fail closed)."""


def _total(v: object) -> float:
    if not _valid(v):
        raise UsageUnreadable("month total is not a finite number of rupees")
    return float(v)  # type: ignore[arg-type]


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
        )


@dataclass(frozen=True)
class AllowanceUse:
    """The deployment's allowance-metered usage in one Pacific-time month. `bad` keeps, as
    stored, every counter that is not a finite number ≥ 0: reading one raises UsageUnreadable,
    and writes to other counters carry it over unchanged (never silently reset)."""

    month: str
    units: dict[str, float] = field(default_factory=dict)
    bad: dict[str, Any] = field(default_factory=dict)

    def used(self, key: str) -> float:
        if key in self.bad:
            raise UsageUnreadable(f"allowance counter {key} is not a number")
        return self.units.get(key, 0.0)

    def plus(self, key: str, amount: float) -> AllowanceUse:
        new = round(self.used(key) + amount, 3)
        return AllowanceUse(self.month, {**self.units, key: new}, self.bad)


def decode_allowance(doc: dict[str, Any] | None, month: str) -> AllowanceUse:
    """A stored allowance month (None = nothing used yet). Raises UsageUnreadable when the
    document or its `units` map isn't one; a bad value only makes its own key unreadable."""
    if doc is None:
        return AllowanceUse(month)
    if not isinstance(doc, dict):
        raise UsageUnreadable("allowance document is not a map")
    raw = doc.get("units")
    if raw is None:
        return AllowanceUse(month)
    if not isinstance(raw, dict):
        raise UsageUnreadable("allowance counters are not a map")
    good = {str(k): float(v) for k, v in raw.items() if _valid(v)}
    bad = {str(k): v for k, v in raw.items() if not _valid(v)}
    return AllowanceUse(month, good, bad)


def encode_allowance(a: AllowanceUse, now: datetime) -> dict[str, Any]:
    return {
        "month": a.month,
        "tz": ALLOWANCE_TZ,
        "units": {**a.bad, **a.units},
        "updated_at": now.isoformat(),
    }


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
        "updated_at": now.isoformat(),
    }


class UsageMeter:
    def __init__(self, docs: Docs, *, prefix: str = "jarvis_", tz: str = "Asia/Kolkata") -> None:
        self._d = docs
        self._col = f"{prefix}usage"
        self._allowance_col = f"{prefix}allowance"
        self._tz = _zone(tz)
        self._allowance_tz = _zone(ALLOWANCE_TZ)

    def month_of(self, now: datetime) -> str:
        """The owner's month (rupees, the limit)."""
        return now.astimezone(self._tz).strftime("%Y-%m")

    def allowance_month_of(self, now: datetime) -> str:
        """The vendor's free-allowance month (Pacific time)."""
        return now.astimezone(self._allowance_tz).strftime("%Y-%m")

    def allowance_resets_at(self, now: datetime) -> datetime:
        """When the allowance month that holds `now` ends: the next 1st, 00:00 Pacific."""
        local = now.astimezone(self._allowance_tz)
        year, month = (local.year + 1, 1) if local.month == 12 else (local.year, local.month + 1)
        return datetime(year, month, 1, tzinfo=self._allowance_tz)

    def _path(self, uid: str, month: str) -> str:
        if not safe_id(uid):
            raise ValueError("invalid user id")
        if not _MONTH.fullmatch(month):
            raise ValueError("month must be YYYY-MM")
        return f"{self._col}/{uid}_{month}"

    def _allowance_path(self, month: str) -> str:
        if not _MONTH.fullmatch(month):
            raise ValueError("month must be YYYY-MM")
        return f"{self._allowance_col}/{month}"

    async def get(self, uid: str, month: str) -> MonthUsage:
        return decode(await self._d.get(self._path(uid, month)), month)

    async def months(self, uid: str) -> list[MonthUsage]:
        """Every stored month of this owner, oldest first (R2 privacy dashboard). UsageUnreadable
        when one can't be read."""
        if not safe_id(uid):
            raise ValueError("invalid user id")
        rows = await self._d.query(Query(self._col, where=("user_id", uid)))
        out: list[MonthUsage] = []
        for _doc_id, doc in rows:
            month = doc.get("month")
            if not isinstance(month, str) or not _MONTH.fullmatch(month):
                raise UsageUnreadable("month document has no month")
            out.append(decode(doc, month))
        return sorted(out, key=lambda m: m.month)

    async def forget_before(self, uid: str, month: str) -> int:
        """Delete this owner's months before `month` (YYYY-MM); the current month stays because the
        owner's limit is compared with it. Returns how many went."""
        if not _MONTH.fullmatch(month):
            raise ValueError("month must be YYYY-MM")
        old = [m.month for m in await self.months(uid) if m.month < month]
        if old:
            await self._d.write([Delete(self._path(uid, m)) for m in old])
        return len(old)

    async def allowance(self, month: str) -> AllowanceUse:
        """The deployment's allowance use in a Pacific-time month (UsageUnreadable as above)."""
        return decode_allowance(await self._d.get(self._allowance_path(month)), month)

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
        """Count `units` under `key` in the deployment's allowance month and price the part above
        `free_units` (that month's use, read in the same transaction) at `usd_per_unit` ×
        `inr_per_usd`; a priced call adds its cost to `uid`'s month as `label`. Raises
        UsageUnreadable (writing nothing) when the counter, or the month a priced call would
        be added to, can't be read."""
        if not _UNIT_KEY.fullmatch(key):
            raise ValueError("invalid unit key")
        month, allowance_month = self.month_of(now), self.allowance_month_of(now)
        path, allowance_path = self._path(uid, month), self._allowance_path(allowance_month)

        async def fn(tx: DocTx) -> UnitCharge:
            allow = decode_allowance(await tx.get(allowance_path), allowance_month)
            priced = priced_units(allow.used(key), units, free_units)
            usd = round(priced * usd_per_unit, 8)
            inr = round(usd * inr_per_usd, 6)
            spent = decode(await tx.get(path), month).plus(label, usd, inr) if usd > 0 else None
            if spent is not None:  # every read happens before the first write
                tx.set(path, encode(uid, spent, now))
            tx.set(allowance_path, encode_allowance(allow.plus(key, units), now))
            return UnitCharge(units=units, priced_units=priced, usd=usd, inr=inr)

        return await self._d.transaction(fn)


__all__ = [
    "ALLOWANCE_TZ",
    "AllowanceUse",
    "MonthUsage",
    "UnitCharge",
    "UsageMeter",
    "UsageUnreadable",
    "decode_allowance",
    "priced_units",
]
