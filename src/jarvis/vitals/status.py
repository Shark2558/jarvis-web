# src/jarvis/vitals/status.py
"""Status is computed, never stored stale (R4 D3). ok -> amber at `amber_fraction` of the limit or
within `expiry_days` of expiry -> red at the limit or when expired. An `auto` record whose usage
could not be read is `unknown`, never a failure. Fixed-template reasons (no model, no dollar)."""

from __future__ import annotations

from datetime import datetime, timedelta

from jarvis.vitals.models import RANK, Provider, ProviderView, Status

PERCENT = 100.0


def _worse(a: Status, b: Status) -> Status:
    return a if RANK[a] >= RANK[b] else b


def _usage(p: Provider, amber_fraction: float) -> tuple[Status, str]:
    if p.limit is None or p.limit <= 0 or p.used is None:
        return "ok", ""
    pct = round(p.used / p.limit * PERCENT)
    if p.used >= p.limit:
        return "red", "has reached its limit"
    if p.used >= amber_fraction * p.limit:
        return "amber", f"is at {pct}% of its limit"
    return "ok", ""


def _expiry(p: Provider, now: datetime, days: int) -> tuple[Status, str]:
    if p.expires_at is None:
        return "ok", ""
    if p.expires_at <= now:
        return "red", "has expired"
    if p.expires_at - now <= timedelta(days=days):
        left = max(1, (p.expires_at - now).days)
        return "amber", f"expires in {left} day{'s' if left != 1 else ''}"
    return "ok", ""


def status_of(p: Provider, now: datetime, amber_fraction: float, expiry_days: int) -> ProviderView:
    pct = None
    if p.limit is not None and p.limit > 0 and p.used is not None:
        pct = round(p.used / p.limit * PERCENT, 1)
    if p.source == "auto" and p.used is None:
        return ProviderView(provider=p, status="unknown", percent=None, reason="can't be read now")
    s1, r1 = _usage(p, amber_fraction)
    s2, r2 = _expiry(p, now, expiry_days)
    status = _worse(s1, s2)
    reasons = [r for s, r in ((s1, r1), (s2, r2)) if r and s == status]
    return ProviderView(provider=p, status=status, percent=pct, reason="; ".join(reasons))


def overall(views: list[ProviderView] | tuple[ProviderView, ...]) -> Status:
    worst: Status = "ok"
    for v in views:
        if v.status in RANK:
            worst = _worse(worst, v.status)
    return worst


__all__ = ["overall", "status_of"]
