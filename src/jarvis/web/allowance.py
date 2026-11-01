# src/jarvis/web/allowance.py
"""The monthly web-search allowance (slice 10 B; Layer 7 via the `Docs` port).

    {prefix}web_usage/{YYYY-MM}   month, tz, credits, searches, reads, updated_at

Tavily's free plan gives 1,000 credits a month to the API KEY (the whole deployment, however
many owners), so there is ONE counter per month, keyed by the owner's month (JARVIS_USER_TIMEZONE,
IST). JARVIS stops at `MONTHLY_CREDITS` (90 %) and never uses pay-as-you-go: ₹0.

Each call RESERVES its credits first, in a transaction (two calls can't both take the last one),
and gives them back (`refund`) when Tavily clearly did not charge (no answer, an error status, a
failed extraction); `settle` adds whatever Tavily reports above the reservation. Fail closed: an
existing `credits` that is not a finite whole number ≥ 0 makes the month UNREADABLE — no search
is made and the counter is never silently reset. `searches` / `reads` are only shown, read
leniently.
"""

from __future__ import annotations

import math
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from jarvis.logging import get_logger
from jarvis.storage.docs import Docs, DocTx

log = get_logger(__name__)

MONTHLY_CREDITS = 900  # 90 % of Tavily's free 1,000 a month
_MONTH = re.compile(r"\d{4}-(0[1-9]|1[0-2])")
Kind = Literal["search", "read"]


class AllowanceReached(RuntimeError):
    """This month's web-search credits are used up (plain words, rupees never come into it)."""


class AllowanceUnreadable(RuntimeError):
    """The month's counter can't be read, so nothing is searched (fail closed)."""


def _whole(v: object) -> bool:
    return (
        not isinstance(v, bool)
        and isinstance(v, int | float)
        and math.isfinite(v)
        and v >= 0
        and float(v).is_integer()
    )


@dataclass(frozen=True)
class WebUse:
    month: str
    credits: int = 0
    searches: int = 0
    reads: int = 0
    cap: int = MONTHLY_CREDITS

    @property
    def left(self) -> int:
        return max(0, self.cap - self.credits)


@dataclass(frozen=True)
class Reservation:
    month: str
    credits: int
    kind: Kind
    left: int  # credits left this month once this reservation is taken


def _decode(doc: object, month: str, cap: int) -> WebUse:
    if doc is None:
        return WebUse(month, cap=cap)
    if not isinstance(doc, dict):
        raise AllowanceUnreadable("the web-search counter is not a document")
    raw = doc.get("credits", 0)
    if not _whole(raw):
        raise AllowanceUnreadable("the web-search counter is not a whole number")

    def side(key: str) -> int:
        v = doc.get(key, 0)
        return int(v) if _whole(v) else 0

    return WebUse(month, int(raw), side("searches"), side("reads"), cap)


class WebAllowance:
    def __init__(
        self,
        docs: Docs,
        *,
        prefix: str = "jarvis_",
        tz: str = "Asia/Kolkata",
        cap: int = MONTHLY_CREDITS,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.docs = docs
        self._col = f"{prefix}web_usage"
        try:
            self._tz = ZoneInfo(tz)
        except (ZoneInfoNotFoundError, ValueError):
            self._tz = ZoneInfo("UTC")
        self.tz_name = str(self._tz)
        self.cap = cap
        self._now = now

    def month(self) -> str:
        return self._now().astimezone(self._tz).strftime("%Y-%m")

    def _path(self, month: str) -> str:
        if not _MONTH.fullmatch(month):
            raise ValueError("month must be YYYY-MM")
        return f"{self._col}/{month}"

    def _encode(self, use: WebUse) -> dict[str, Any]:
        return {
            "month": use.month,
            "tz": self.tz_name,
            "credits": use.credits,
            "searches": use.searches,
            "reads": use.reads,
            "updated_at": self._now().isoformat(),
        }

    async def usage(self) -> WebUse:
        month = self.month()
        return _decode(await self.docs.get(self._path(month)), month, self.cap)

    async def reserve(self, credits: int, *, kind: Kind) -> Reservation:
        """Take `credits` from this month before a call. Raises AllowanceReached (nothing
        taken) when they are not there, AllowanceUnreadable when the counter can't be read."""
        month = self.month()
        path = self._path(month)

        async def fn(tx: DocTx) -> Reservation:
            use = _decode(await tx.get(path), month, self.cap)
            if use.credits + credits > self.cap:
                raise AllowanceReached(
                    f"Web search is paused: this month's {self.cap} free searches are used up. "
                    "It starts again on the 1st."
                )
            new = WebUse(
                month,
                use.credits + credits,
                use.searches + (kind == "search"),
                use.reads + (kind == "read"),
                self.cap,
            )
            tx.set(path, self._encode(new))
            return Reservation(month, credits, kind, new.left)

        return await self.docs.transaction(fn)

    async def _shift(self, r: Reservation, credits: int, count: int) -> None:
        path = self._path(r.month)

        async def fn(tx: DocTx) -> None:
            use = _decode(await tx.get(path), r.month, self.cap)
            searches = use.searches + (count if r.kind == "search" else 0)
            reads = use.reads + (count if r.kind == "read" else 0)
            tx.set(
                path,
                self._encode(
                    WebUse(
                        r.month,
                        max(0, use.credits + credits),
                        max(0, searches),
                        max(0, reads),
                        self.cap,
                    )
                ),
            )

        try:
            await self.docs.transaction(fn)
        except Exception as exc:  # noqa: BLE001 — bookkeeping after the call never fails it
            log.warning("web allowance update failed", extra={"reason": type(exc).__name__})

    async def refund(self, r: Reservation) -> None:
        """Tavily did not charge for the call: give its reservation back (never below 0)."""
        await self._shift(r, -r.credits, -1)

    async def settle(self, r: Reservation, *, charged: int | None) -> None:
        """Tavily reported charging more than was reserved: count the difference too."""
        if charged is not None and charged > r.credits:
            await self._shift(r, charged - r.credits, 0)


__all__ = [
    "MONTHLY_CREDITS",
    "AllowanceReached",
    "AllowanceUnreadable",
    "Kind",
    "Reservation",
    "WebAllowance",
    "WebUse",
]
