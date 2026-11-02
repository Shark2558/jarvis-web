# src/jarvis/integrations/google_errors.py
"""What a Google error answer says about quotas (slice 12 D2; Layer 6) — from its machine-readable
fields only, never its message text. Shared by the server-key client (`google_key`) and the owner's
OAuth link (`google.GoogleConnector`).

Google's JSON errors are a `google.rpc.Status` ({error: {code, status, details[]}}) and, on older
APIs such as YouTube, also {error: {errors: [{reason, domain}]}} (cloud.google.com/apis/design/
errors, developers.google.com/youtube/v3/docs/errors; checked 2026-11-03). EVERY Places / Routes
429 carries status RESOURCE_EXHAUSTED — most of them a per-minute limit — so the status alone
never means "used up". Which limit was hit is named by an ErrorInfo's `metadata.quota_limit` (and
`quota_unit`, e.g. "1/d/{project}") or a QuotaFailure's `violations[].quotaId`
(e.g. "SearchTextRequestsPerDayPerProject"): only a per-day or per-month name is "used up".
YouTube's own reasons: `quotaExceeded` / `dailyLimitExceeded` are its daily quota (used up for the
day); `rateLimitExceeded` / `userRateLimitExceeded` are short-term (try again: "busy").
"""

from __future__ import annotations

import json
import re
from typing import Any

from jarvis.quota.ledger import UsedUp

DAILY_REASONS = frozenset({"quotaExceeded", "dailyLimitExceeded"})
RATE_LIMITED = frozenset(
    {"rateLimitExceeded", "userRateLimitExceeded", "RATE_LIMIT_EXCEEDED", "RESOURCE_EXHAUSTED"}
)
_LIMIT_KEYS = ("quota_limit", "quota_limit_id", "quotaId", "quota_id")
USED_UP_MSG: dict[UsedUp, str] = {  # plain words for the owner, never Google's
    "day": "Google says today's allowance for that service is used up; it starts again after "
    "midnight Pacific time.",
    "month": "Google says this month's allowance for that service is used up.",
}
_DAY_UNIT = re.compile(r"/d(?:/|$)")
_MONTH_UNIT = re.compile(r"/(?:mo|month)(?:/|$)")
_MAX_ITEMS = 20  # details / violations looked at; an answer is capped at 1 MB anyway


def envelope(raw: bytes) -> dict[str, Any]:
    """The `error` object of a Google error answer ({} when there is none or it can't be read)."""
    try:
        err = json.loads(raw).get("error")
    except (ValueError, AttributeError, TypeError):
        return {}
    return err if isinstance(err, dict) else {}


def reasons(err: dict[str, Any]) -> set[str]:
    """errors[].reason, details[].reason and the status (each cut to 64 characters)."""
    found: set[str] = set()
    for key in ("errors", "details"):
        items = err.get(key)
        for item in items[:_MAX_ITEMS] if isinstance(items, list) else []:
            if isinstance(item, dict) and isinstance(item.get("reason"), str):
                found.add(item["reason"][:64])
    status = err.get("status")
    if isinstance(status, str):
        found.add(status[:64])
    return found


def _limit_names(err: dict[str, Any]) -> tuple[list[str], list[str]]:
    """(the quota limit names, the quota units) the error's details name."""
    names: list[str] = []
    units: list[str] = []
    details = err.get("details")
    for item in details[:_MAX_ITEMS] if isinstance(details, list) else []:
        if not isinstance(item, dict):
            continue
        meta = item.get("metadata")
        if isinstance(meta, dict):
            names += [meta[k] for k in _LIMIT_KEYS if isinstance(meta.get(k), str)]
            if isinstance(meta.get("quota_unit"), str):
                units.append(meta["quota_unit"])
        violations = item.get("violations")
        for v in violations[:_MAX_ITEMS] if isinstance(violations, list) else []:
            if isinstance(v, dict):
                names += [v[k] for k in _LIMIT_KEYS if isinstance(v.get(k), str)]
    return [n[:128] for n in names], [u[:64] for u in units]


def _period_of(name: str) -> UsedUp | None:
    flat = re.sub(r"[^a-z]", "", name.lower())
    if "perday" in flat or "daily" in flat:
        return "day"
    if "permonth" in flat or "monthly" in flat:
        return "month"
    return None


def used_up(err: dict[str, Any]) -> UsedUp | None:
    """'day' / 'month' when Google says a per-day / per-month quota is gone; None for anything
    else — a per-minute limit, or a quota error that names no limit (then: busy, try again)."""
    names, units = _limit_names(err)
    found = {_period_of(n) for n in names}
    found |= {"day" for u in units if _DAY_UNIT.search(u)}
    found |= {"month" for u in units if _MONTH_UNIT.search(u)}
    if "month" in found:
        return "month"
    if "day" in found or reasons(err) & DAILY_REASONS:
        return "day"
    return None


def rate_limited(err: dict[str, Any]) -> bool:
    """A short-term limit (try again in a minute), when it is not a used-up quota."""
    return used_up(err) is None and bool(reasons(err) & RATE_LIMITED)


__all__ = [
    "DAILY_REASONS",
    "RATE_LIMITED",
    "USED_UP_MSG",
    "UsedUp",
    "envelope",
    "rate_limited",
    "reasons",
    "used_up",
]
