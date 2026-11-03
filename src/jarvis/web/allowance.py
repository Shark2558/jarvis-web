# src/jarvis/web/allowance.py
"""The monthly web-search allowance (slice 10 B; Layer 7 via the `Docs` port).

    {prefix}web_usage/{YYYY-MM}   month, tz, credits, searches, reads, updated_at

Tavily's free plan gives 1,000 credits a month to the API KEY (the whole deployment, however
many owners), so there is ONE counter per month, keyed by the owner's month (JARVIS_USER_TIMEZONE,
IST). JARVIS stops at `MONTHLY_CREDITS` (90 %) and never uses pay-as-you-go: ₹0.

Each call RESERVES its credits first, in a transaction (two calls can't both take the last one),
and gives them back (`refund`) when Tavily clearly did not charge (no answer, an error status, a
failed extraction); `settle` adds whatever Tavily reports above the reservation; `latch` marks the
month used up when Tavily itself says the credits are gone (432/433). The counter starts at 0 on
the first deploy even if the key was used elsewhere this month; once a day Tavily's own count
(GET /usage, `jarvis.web.vendor_usage`) can only RAISE it (`correct`). Fail closed: an
existing `credits` that is not a finite whole number ≥ 0 makes the month UNREADABLE — no search
is made and the counter is never silently reset. `searches` / `reads` are only shown, read
leniently. The counter rules are shared with Google's ledger (`jarvis.quota.counter`).
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from jarvis.quota.counter import Doc, counted, lenient, quietly, take
from jarvis.storage.docs import Docs
from jarvis.web.ports import VendorUsage

MONTHLY_CREDITS = 900  # 90 % of Tavily's free 1,000 a month
_MONTH = re.compile(r"\d{4}-(0[1-9]|1[0-2])")
Kind = Literal["search", "read"]


class AllowanceReached(RuntimeError):
    """This month's web-search credits are used up (plain words, rupees never come into it)."""


class AllowanceUnreadable(RuntimeError):
    """The month's counter can't be read, so nothing is searched (fail closed)."""


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
    found, credits = counted(
        doc, "credits", unreadable=AllowanceUnreadable, what="the web-search counter"
    )
    return WebUse(month, credits, lenient(found, "searches"), lenient(found, "reads"), cap)


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

        def step(doc: object) -> tuple[Doc, Reservation]:
            use = _decode(doc, month, self.cap)
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
            return self._encode(new), Reservation(month, credits, kind, new.left)

        return await take(self.docs, self._path(month), step)

    async def _shift(self, r: Reservation, credits: int, count: int) -> None:
        """Bookkeeping after the call: never fails it (`quietly`)."""

        def step(doc: object) -> Doc:
            use = _decode(doc, r.month, self.cap)
            searches = use.searches + (count if r.kind == "search" else 0)
            reads = use.reads + (count if r.kind == "read" else 0)
            new = WebUse(
                r.month,
                max(0, use.credits + credits),
                max(0, searches),
                max(0, reads),
                self.cap,
            )
            return self._encode(new)

        await quietly(self.docs, self._path(r.month), step, event="web allowance update failed")

    async def refund(self, r: Reservation) -> None:
        """Tavily did not charge for the call: give its reservation back (never below 0)."""
        await self._shift(r, -r.credits, -1)

    async def latch(self) -> None:
        """Tavily said the plan's credits are gone (432/433): mark this month used up, so Vitals
        says so and nothing more is sent until it resets. Repairs an unreadable counter too (to
        "used up", which keeps it closed); the side counts are kept when they can be read."""
        month = self.month()

        def step(doc: object) -> Doc:
            old = doc if isinstance(doc, dict) else {}
            searches, reads = lenient(old, "searches"), lenient(old, "reads")
            return self._encode(WebUse(month, self.cap, searches, reads, self.cap))

        await quietly(self.docs, self._path(month), step, event="web allowance latch failed")

    async def settle(self, r: Reservation, *, charged: int | None) -> None:
        """Tavily reported charging more than was reserved: count the difference too."""
        if charged is not None and charged > r.credits:
            await self._shift(r, charged - r.credits, 0)

    async def correct(self, vendor: VendorUsage) -> WebUse | None:
        """Tavily's own count (slice 11 D7 b): RAISE this month's count to it — never lower it (a
        low or glitchy reading must not reopen web search), never past the stop; a vendor whose
        credits are gone closes the month. None when the counter is unreadable (it stays
        closed). May raise on a store error (the caller logs it)."""
        month = self.month()
        target = self.cap if vendor.exhausted else min(max(0, vendor.used), self.cap)

        def step(doc: object) -> tuple[Doc | None, WebUse | None]:
            try:
                use = _decode(doc, month, self.cap)
            except AllowanceUnreadable:
                return None, None
            if target <= use.credits:
                return None, use
            new = WebUse(month, target, use.searches, use.reads, self.cap)
            return self._encode(new), new

        return await take(self.docs, self._path(month), step)


__all__ = [
    "MONTHLY_CREDITS",
    "AllowanceReached",
    "AllowanceUnreadable",
    "Kind",
    "Reservation",
    "WebAllowance",
    "WebUse",
]
