# tests/r131_fakes_c.py -- R13.1 Part C's fakes (imported bare: `from r131_fakes_c import ...`).
# Every clock is FIXED (`r131_fakes.NOW`, 17 Nov 2026 09:00 IST); nothing here reaches Google.
#
#   YieldingDocs                  MemoryDocs whose reads yield to the loop, as a network read does,
#                                 so a read-then-write race is real (the cap's eval control)
#   FakeBilling(limit, used)      `billing.spend.ensure_spend_allowed`'s view: budgets, meter, fx;
#                                 `recorded` keeps each `record(uid, label, usd)`
#   OffMode / OnMode              `offline.mode.BrainMode.load` answering "none" / "ai"
from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from r131_fakes import NOW

from jarvis.billing.fx import Rate
from jarvis.billing.meter import MonthUsage, UsageMeter
from jarvis.storage.docs import MemoryDocs

RATE = 95.24


class YieldingDocs(MemoryDocs):
    """A read gives the loop away first (a real store's read is a network round trip)."""

    async def get(self, path: str) -> dict[str, Any] | None:
        await asyncio.sleep(0)
        return await super().get(path)


@dataclass
class FakeFx:
    inr_per_usd: float = RATE

    async def rate(self) -> Rate:
        return Rate(self.inr_per_usd, "2026-11-17", "default")

    def peek(self) -> Rate:
        return Rate(self.inr_per_usd, "2026-11-17", "default")


@dataclass
class FakeBudgets:
    limit: int | None = None
    broken: bool = False

    async def get(self, uid: str) -> int | None:
        if self.broken:
            raise RuntimeError("budgets down")
        return self.limit


@dataclass
class FakeBilling:
    """The parts of `billing.service.Billing` See it on me reads (fx, budgets, meter, record)."""

    limit: int | None = None
    used_inr: float = 0.0
    rate: float = RATE
    broken: bool = False
    clock: Callable[[], datetime] = lambda: NOW
    recorded: list[tuple[str, str, float]] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.fx = FakeFx(self.rate)
        self.budgets = FakeBudgets(self.limit, self.broken)
        self.meter = _Meter(self.used_inr)

    async def record(self, uid: str, brain_id: str, cost_usd: float) -> float:
        self.recorded.append((uid, brain_id, cost_usd))
        return round(cost_usd * self.fx.inr_per_usd, 6)


class _Meter(UsageMeter):
    def __init__(self, used_inr: float) -> None:
        super().__init__(MemoryDocs())
        self._used = used_inr

    async def get(self, uid: str, month: str) -> MonthUsage:
        return MonthUsage(month=month, inr_total=self._used)


class OffMode:
    async def load(self, uid: str) -> str:
        return "none"


class OnMode:
    async def load(self, uid: str) -> str:
        return "ai"


__all__ = ["RATE", "FakeBilling", "FakeFx", "OffMode", "OnMode", "YieldingDocs"]
