# src/jarvis/web/vendor_usage.py
"""Tavily's own count, folded into the monthly allowance (slice 11 D7 b; Layer 6 → 7).

    {prefix}web_vendor_usage/tavily   checked_at, month, used, limit, exhausted

The scheduler tick (hourly) calls `VendorCheck.run`. At most once a day — the claim is a
transaction on the document above, so every Cloud Run instance shares it, and a failed call uses
up the day's check (no retry storm) — it asks the vendor for its usage (Tavily GET /usage: no
credit) and corrects the month's count with it (`WebAllowance.correct`: only ever RAISED, capped
at the stop; a vendor whose credits are gone closes the month).

Billing cycles: Tavily counts per "current billing cycle", the allowance per IST calendar month.
For the first 5½ hours of an IST month it is still last month in UTC, and the vendor's count may
still be last month's, so no check runs then (and the tick does not claim the day). If the
vendor's cycle starts on another day, the raise-only rule can only make JARVIS stop early, never
spend more.

Not on a 432 / 433: that answer already latches the month at the stop (`WebAllowance.latch`),
and a raise-only correction can't change a latched month, so the extra call would add nothing.
Never raises; logs counts, never the key.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from jarvis.logging import get_logger
from jarvis.storage.docs import Docs, DocTx, Set
from jarvis.web.allowance import WebAllowance
from jarvis.web.ports import UsageReporter, VendorUsage

log = get_logger(__name__)

CHECK_EVERY = timedelta(hours=24)
DOC_ID = "tavily"


class VendorCheck:
    def __init__(
        self,
        docs: Docs,
        reporter: UsageReporter,
        allowance: WebAllowance,
        *,
        prefix: str = "jarvis_",
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
        every: timedelta = CHECK_EVERY,
    ) -> None:
        self._docs, self._reporter, self._allowance = docs, reporter, allowance
        self._path = f"{prefix}web_vendor_usage/{DOC_ID}"
        self._now, self._every = now, every

    async def _claim(self, now: datetime) -> bool:
        """Take today's check (shared by every instance): False when one ran in the last day."""

        async def fn(tx: DocTx) -> bool:
            doc = await tx.get(self._path)
            old = doc if isinstance(doc, dict) else {}
            last = old.get("checked_at")
            if isinstance(last, datetime) and timedelta(0) <= now - last < self._every:
                return False
            tx.set(self._path, {**old, "checked_at": now})
            return True

        return await self._docs.transaction(fn)

    async def _record(self, now: datetime, got: VendorUsage) -> None:
        snapshot = {
            "checked_at": now,
            "month": self._allowance.month(),
            "used": got.used,
            "limit": got.limit,
            "exhausted": got.exhausted,
        }
        await self._docs.write([Set(self._path, snapshot)])

    async def run(self) -> VendorUsage | None:
        """The vendor's count when a check ran (and the month was corrected), else None."""
        now = self._now()
        try:
            if self._allowance.month() != now.astimezone(UTC).strftime("%Y-%m"):
                return None  # the owner's month began before the vendor's: check later
            if not await self._claim(now):
                return None
            got = await self._reporter.usage()
            use = await self._allowance.correct(got)
            await self._record(now, got)
        except Exception as exc:  # noqa: BLE001 — a housekeeping check never fails the tick
            log.warning("tavily usage check failed", extra={"reason": type(exc).__name__})
            return None
        log.info(
            "tavily usage checked",
            extra={
                "vendor_used": got.used,
                "vendor_limit": got.limit,
                "exhausted": got.exhausted,
                "month_credits": use.credits if use is not None else None,
            },
        )
        return got


__all__ = ["CHECK_EVERY", "VendorCheck"]
