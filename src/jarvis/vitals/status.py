# src/jarvis/vitals/status.py
"""Status is computed, never stored stale (R4 D3). ok -> amber at `amber_fraction` of the limit or
within `expiry_days` of expiry -> red at the limit or when expired. An `auto` record whose usage
could not be read is `unknown`, never a failure. A manual record whose `reset_at` has passed has
unknown usage (the period rolled over: it re-arms). A naive date is read as end of day in the
owner's zone, never an error. Fixed-template reasons (no model, no dollar)."""

from __future__ import annotations

import math
from datetime import datetime, timedelta, tzinfo
from zoneinfo import ZoneInfo

from jarvis.vitals.models import DEFAULT_TZ, RANK, Provider, ProviderView, Status, aware

PERCENT = 100.0
DEFAULT_ZONE = ZoneInfo(DEFAULT_TZ)  # callers that pass no zone (tests); the service passes its own


def _worse(a: Status, b: Status) -> Status:
    return a if RANK[a] >= RANK[b] else b


def _used(p: Provider, now: datetime, tz: tzinfo) -> float | None:
    """The usage to judge: a manual figure is stale once its reset has passed."""
    if p.source == "manual" and p.reset_at is not None and now > aware(p.reset_at, tz):
        return None
    return p.used


def _percent(limit: float | None, used: float | None) -> float | None:
    if limit is None or limit <= 0 or used is None:
        return None
    return used / limit * PERCENT


def _reaches(used: float, limit: float, fraction: float) -> bool:
    return used >= fraction * limit or math.isclose(used, fraction * limit, rel_tol=1e-9)


def _usage(limit: float | None, used: float | None, amber_fraction: float) -> tuple[Status, str]:
    if limit is None or used is None:
        return "ok", ""
    if limit <= 0:
        return ("red", "has reached its limit") if used > 0 else ("ok", "")
    if used >= limit:
        return "red", "has reached its limit"
    if _reaches(used, limit, amber_fraction):
        return "amber", f"is at {round(used / limit * PERCENT)}% of its limit"
    return "ok", ""


def _expiry(p: Provider, now: datetime, days: int, tz: tzinfo) -> tuple[Status, str]:
    if p.expires_at is None:
        return "ok", ""
    expires = aware(p.expires_at, tz)
    if expires <= now:
        return "red", "has expired"
    if expires - now <= timedelta(days=days):
        left = max(1, (expires - now).days)
        return "amber", f"expires in {left} day{'s' if left != 1 else ''}"
    return "ok", ""


def status_of(
    p: Provider,
    now: datetime,
    amber_fraction: float,
    expiry_days: int,
    tz: tzinfo = DEFAULT_ZONE,
    *,
    base: tuple[Status, str] | None = None,
) -> ProviderView:
    """`tz` is the owner's zone (the service passes `Settings.user_timezone`).

    `base` (R5.1, JARVIS's own keys and connections): the thing's own state and its fixed reason
    ("was refused"), judged together with any usage and expiry; the worst wins. Such an item has
    no usage to read, so it is never "unknown" for that alone. An "unknown" base gives way to a
    known amber or red from usage or expiry."""
    used = _used(p, now, tz)
    pct = _percent(p.limit, used)
    pct = None if pct is None else round(pct, 1)
    if base is None and p.source == "auto" and p.used is None:
        return ProviderView(provider=p, status="unknown", percent=None, reason="can't be read now")
    parts = [_usage(p.limit, used, amber_fraction), _expiry(p, now, expiry_days, tz)]
    if base is not None and base[0] == "unknown":
        if all(s == "ok" for s, _ in parts):
            return ProviderView(provider=p, status="unknown", percent=pct, reason=base[1])
    elif base is not None:
        parts.insert(0, base)
    status: Status = "ok"
    for s, _ in parts:
        status = _worse(status, s)
    reasons = [r for s, r in parts if r and s == status]
    return ProviderView(provider=p, status=status, percent=pct, reason="; ".join(reasons))


def overall(views: list[ProviderView] | tuple[ProviderView, ...]) -> Status:
    if views and all(v.status == "unknown" for v in views):
        return "unknown"
    worst: Status = "ok"
    for v in views:
        if v.status in RANK:
            worst = _worse(worst, v.status)
    return worst


__all__ = ["overall", "status_of"]
