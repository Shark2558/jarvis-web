# src/jarvis/web/service.py
"""Wiring for web search (slice 10 B): the provider (Tavily today) and the deployment's monthly
allowance, built from settings. No key, or switched off → None: the tools are not registered and
JARVIS says web search is not set up. Also the Vitals line's data (`usage_view`) and, from the
scheduler tick, the once-a-day cross-check with the vendor's own count (slice 11 D7 b).
"""

from __future__ import annotations

import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import httpx

from jarvis.config import Settings
from jarvis.storage.docs import Docs
from jarvis.web.allowance import AllowanceUnreadable, WebAllowance
from jarvis.web.ports import SearchProvider
from jarvis.web.vendor_usage import VendorCheck

HOUR_S = 3600.0


@dataclass
class WebService:
    provider: SearchProvider
    allowance: WebAllowance
    clock: Callable[[], float] = time.monotonic
    # searches per owner in the last hour (review M3). In-process: production runs ONE instance.
    _recent: dict[str, deque[float]] = field(default_factory=dict)
    # slice 11 D7 b: the vendor's own count, once a day from the scheduler tick (None: none)
    vendor_check: VendorCheck | None = None

    async def check_vendor_usage(self) -> None:
        """The scheduler tick: cross-check the month with the vendor's count. Never raises."""
        if self.vendor_check is not None:
            await self.vendor_check.run()

    def searches_last_hour(self, uid: str) -> int:
        q = self._recent.setdefault(uid, deque())
        now = self.clock()
        while q and now - q[0] >= HOUR_S:
            q.popleft()
        return len(q)

    def count_search(self, uid: str) -> None:
        self._recent.setdefault(uid, deque()).append(self.clock())

    async def aclose(self) -> None:
        await self.provider.aclose()


def web_configured(s: Settings) -> bool:
    key = s.tavily_api_key.get_secret_value().strip() if s.tavily_api_key else ""
    return bool(s.web_search_enabled and key)


def build_web_service(
    s: Settings, docs: Docs, *, http: httpx.AsyncClient | None = None
) -> WebService | None:
    if not web_configured(s):
        return None
    from jarvis.web.tavily import TavilyProvider

    assert s.tavily_api_key is not None
    provider = TavilyProvider(s.tavily_api_key, http=http)
    allowance = WebAllowance(docs, prefix=s.firestore_prefix, tz=s.user_timezone)
    check = VendorCheck(docs, provider, allowance, prefix=s.firestore_prefix)
    return WebService(provider, allowance, vendor_check=check)


async def usage_view(web: WebService | None) -> dict[str, Any]:
    """{configured: false} | {configured, month, used, limit, left, reached, unreadable}.
    An unreadable counter is said so (used/left null), never shown as 0."""
    if web is None:
        return {"configured": False}
    a = web.allowance
    try:
        use = await a.usage()
    except AllowanceUnreadable:
        return {
            "configured": True,
            "month": a.month(),
            "used": None,
            "limit": a.cap,
            "left": None,
            "reached": False,
            "unreadable": True,
        }
    return {
        "configured": True,
        "month": use.month,
        "used": use.credits,
        "limit": use.cap,
        "left": use.left,
        "reached": use.left <= 0,
        "unreadable": False,
    }


__all__ = ["WebService", "build_web_service", "usage_view", "web_configured"]
