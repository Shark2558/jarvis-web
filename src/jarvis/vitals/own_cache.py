# src/jarvis/vitals/own_cache.py
"""The web vendor's free usage report for Vitals' own items (R5.1 D2), cached per process so the
board never asks the vendor more than once per `WEB_CACHE_S` (a failure is asked again after
`WEB_RETRY_S`). Kept out of `own.py` (R6 review L2 added the build book item there).
"""

from __future__ import annotations

import asyncio
import math
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from jarvis.vitals.own import UsageReporterLike, VendorUsageLike

WEB_CACHE_S = 600.0  # the vendor's usage report, at most once per 10 minutes per process
WEB_RETRY_S = 60.0  # after a failed report, wait this long before asking again


class CachedUsage:
    """The vendor's usage report, kept for `WEB_CACHE_S` (a failure for `WEB_RETRY_S`)."""

    def __init__(self, reporter: UsageReporterLike) -> None:
        self._reporter = reporter
        self._lock = asyncio.Lock()
        self._at = -math.inf
        self._value: VendorUsageLike | None = None

    async def get(self, now: float) -> VendorUsageLike:
        async with self._lock:
            fresh = now - self._at < (WEB_CACHE_S if self._value is not None else WEB_RETRY_S)
            if not fresh:
                self._at = now
                self._value = None
                self._value = await self._reporter.usage()
            if self._value is None:
                raise LookupError("usage report unavailable")
            return self._value


__all__ = ["WEB_CACHE_S", "WEB_RETRY_S", "CachedUsage"]
