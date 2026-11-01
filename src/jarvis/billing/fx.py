# src/jarvis/billing/fx.py
"""USD → INR for display and the owner's limit (cross-cutting: token & cost metering).

Anthropic bills in US dollars and the owner's card is charged in rupees at the bank's rate, so
every rupee figure JARVIS shows is an estimate ("≈"). The rate comes from Frankfurter (free, no
key): ONE fixed URL, fetched at most once a day, 5 s overall deadline, no retries. An answer is
used only if it carries a finite number between 50 and 200 at `rate` (or, defensively,
`rates.INR` or `rates[0].rate`). The value is cached in memory and in Firestore
(`{prefix}fx/usd_inr`), so a cold start reads one document instead of calling out. On any
failure: the last cached value, else `JARVIS_USD_INR_RATE`.

Never blocks a reply: `rate()` answers with what is known at once and, when the day's check is
due, starts it in the background. `refresh()` (the usage view) waits for that check.
"""

from __future__ import annotations

import asyncio
import math
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, timedelta
from typing import Any, Literal, TypeGuard

import httpx

from jarvis.logging import get_logger
from jarvis.storage.docs import Docs, DocTx

log = get_logger(__name__)

FRANKFURTER_URL = "https://api.frankfurter.dev/v2/rate/usd/inr"
DEFAULT_RATE = 95.24  # mid-market, 1 Nov 2026 (docs/plans/phase7-slice7b-inr-costs-budget.md)
DEFAULT_AS_OF = "2026-11-01"
RATE_MIN, RATE_MAX = 50.0, 200.0
FETCH_TIMEOUT_S = 5.0
REFRESH_EVERY = timedelta(days=1)

Source = Literal["frankfurter", "cached", "default"]


@dataclass(frozen=True)
class Rate:
    inr_per_usd: float
    as_of: str | None  # YYYY-MM-DD the rate is for; None when nobody knows (owner-set default)
    source: Source


def utcnow() -> datetime:
    return datetime.now(UTC)


def _rate_ok(v: object) -> TypeGuard[int | float]:
    return (
        isinstance(v, int | float)
        and not isinstance(v, bool)
        and math.isfinite(v)
        and RATE_MIN <= v <= RATE_MAX
    )


def _first(rates: object) -> dict[str, Any]:
    if isinstance(rates, list) and rates and isinstance(rates[0], dict):
        return rates[0]
    return {}


def parse_rate(body: object) -> float | None:
    """The rate in a Frankfurter answer, or None. Only the documented places are read."""
    if not isinstance(body, dict):
        return None
    rates = body.get("rates")
    for v in (
        body.get("rate"),
        rates.get("INR") if isinstance(rates, dict) else None,
        _first(rates).get("rate"),
    ):
        if _rate_ok(v):
            return float(v)
    return None


def _iso_day(v: object) -> str | None:
    if not isinstance(v, str):
        return None
    try:
        d = date.fromisoformat(v)
    except ValueError:
        return None
    return v if d.isoformat() == v else None


def parse_as_of(body: object, fallback: str) -> str:
    """The day the rate is for (`date`, or `rates[0].date`), else `fallback` (the fetch day)."""
    if isinstance(body, dict):
        for v in (body.get("date"), _first(body.get("rates")).get("date")):
            if (d := _iso_day(v)) is not None:
                return d
    return fallback


def _when(v: object) -> datetime | None:
    if not isinstance(v, str):
        return None
    try:
        t = datetime.fromisoformat(v)
    except ValueError:
        return None
    return t if t.tzinfo else t.replace(tzinfo=UTC)


class FxRates:
    def __init__(
        self,
        *,
        docs: Docs | None,
        http: httpx.AsyncClient | None,
        prefix: str = "jarvis_",
        default_rate: float = DEFAULT_RATE,
        url: str = FRANKFURTER_URL,
        clock: Callable[[], datetime] = utcnow,
        timeout_s: float = FETCH_TIMEOUT_S,
    ) -> None:
        self._docs = docs
        self._http = http
        self._path = f"{prefix}fx/usd_inr"
        as_of = DEFAULT_AS_OF if default_rate == DEFAULT_RATE else None
        self._default = Rate(float(default_rate), as_of, "default")
        self._url = url
        self._clock = clock
        self._timeout = timeout_s
        self._best: Rate | None = None  # the last good value (fetched here, or from Firestore)
        self._checked_at: datetime | None = None  # last fetch ATTEMPT, here or by any instance
        self._loaded = False
        self._load_lock = asyncio.Lock()
        self._task: asyncio.Task[None] | None = None

    def peek(self) -> Rate:
        """What is known right now, without any I/O."""
        return self._best or self._default

    async def rate(self) -> Rate:
        """Never raises and never waits on the network (one Firestore read on a cold start)."""
        await self._load()
        if self._due() and (self._task is None or self._task.done()):
            self._task = asyncio.create_task(self._fetch())
        return self.peek()

    async def refresh(self) -> Rate:
        """`rate()`, then wait for the day's fetch if one is running (≤ the 5 s timeout)."""
        await self.rate()
        task = self._task
        if task is not None and not task.done():
            try:
                await asyncio.shield(task)
            except Exception as exc:  # noqa: BLE001 — _fetch handles its own errors
                log.warning("fx: refresh failed", extra={"reason": type(exc).__name__})
        return self.peek()

    # ---- internals ------------------------------------------------------------------------------

    def _due(self) -> bool:
        if self._http is None:
            return False
        return self._checked_at is None or self._clock() - self._checked_at >= REFRESH_EVERY

    async def _load(self) -> None:
        if self._loaded:
            return
        async with self._load_lock:
            if self._loaded:
                return
            self._loaded = True
            if self._docs is None:
                return
            try:
                doc = await self._docs.get(self._path)
            except Exception as exc:  # noqa: BLE001 — the default rate is always there
                log.warning("fx: cached rate unreadable", extra={"reason": type(exc).__name__})
                return
            if not isinstance(doc, dict):
                return
            checked = _when(doc.get("checked_at"))
            if checked is not None and checked > self._clock():
                checked = None  # in the future (clock skew, a bad write): don't skip the fetch
            self._checked_at = self._checked_at or checked
            if self._best is None and _rate_ok(doc.get("rate")):
                self._best = Rate(float(doc["rate"]), _iso_day(doc.get("as_of")), "cached")

    async def _fetch(self) -> None:
        now = self._clock()
        self._checked_at = now  # one attempt a day, successful or not
        fresh: Rate | None = None
        try:
            assert self._http is not None
            # httpx timeouts are per step (connect, each read): one overall deadline as well, so
            # a slow-dripping answer can't hold the usage view (which waits for this) open.
            async with asyncio.timeout(self._timeout):
                resp = await self._http.get(self._url, timeout=self._timeout)
            body = resp.json() if resp.status_code == 200 else None
            value = parse_rate(body)
            if value is not None:
                fresh = Rate(value, parse_as_of(body, now.date().isoformat()), "frankfurter")
            else:
                log.warning(
                    "fx: unusable answer; keeping the last rate", extra={"status": resp.status_code}
                )
        except Exception as exc:  # noqa: BLE001 — never let the rate fail anything
            log.warning(
                "fx: fetch failed; keeping the last rate", extra={"reason": type(exc).__name__}
            )
        if fresh is not None:
            self._best = fresh
        elif self._best is not None and self._best.source == "frankfurter":
            self._best = replace(self._best, source="cached")
        await self._store(fresh, now)

    async def _store(self, fresh: Rate | None, now: datetime) -> None:
        """Record the attempt (and a fresh value) for every instance. A good value stored by
        someone else is kept: this only ever adds the newer one."""
        if self._docs is None:
            return

        async def fn(tx: DocTx) -> None:
            cur = await tx.get(self._path)
            data = dict(cur) if isinstance(cur, dict) else {}
            data["checked_at"] = now.isoformat()
            if fresh is not None:
                data.update(
                    rate=fresh.inr_per_usd,
                    as_of=fresh.as_of,
                    source="frankfurter",
                    fetched_at=now.isoformat(),
                )
            tx.set(self._path, data)

        try:
            await self._docs.transaction(fn)
        except Exception as exc:  # noqa: BLE001 — memory still has it
            log.warning("fx: rate not cached", extra={"reason": type(exc).__name__})


__all__ = [
    "DEFAULT_AS_OF",
    "DEFAULT_RATE",
    "FETCH_TIMEOUT_S",
    "FRANKFURTER_URL",
    "FxRates",
    "Rate",
    "parse_as_of",
    "parse_rate",
]
