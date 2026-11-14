# tests/r14_fakes_b.py -- R14 Part B's fakes (self-health). Imported bare (`from r14_fakes_b
# import ...`); also used by evals/r14/selfwatch.py. Nothing here talks to Google, Telegram or
# spends anything; people are made up.
from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from jarvis.config import Settings
from jarvis.notify.models import NotifySettings
from jarvis.notify.policy import decide
from jarvis.notify.ports import Delivery, Signal
from jarvis.notify.storm import Storm
from jarvis.selfwatch.jobs import Watch
from jarvis.selfwatch.ports import SENDING
from jarvis.storage.docs import Docs, DocTx, MemoryDocs, Op, Query
from jarvis.ticks import run_jobs

UID = "owner-1"
OTHER = "owner-2"
# 12:00 and 02:00 in Asia/Kolkata on 16 Nov 2026 (a Monday)
NOON = datetime(2026, 11, 16, 6, 30, tzinfo=UTC)
TWO_AM = datetime(2026, 11, 15, 20, 30, tzinfo=UTC)


class Clock:
    """A settable clock: `clock()` is the time now; `advance(minutes=5)` moves it."""

    def __init__(self, now: datetime = NOON) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now

    def advance(self, **kw: float) -> None:
        self.now += timedelta(**kw)


@dataclass
class Sent:
    uid: str
    kind: str
    subject: str | None
    text: str
    sending: bool  # selfwatch.ports.SENDING was set while it was sent
    rang: bool


@dataclass
class RingCounter:
    """A notifier with the real policy (quiet hours, held kinds) and the real storm (R14's own
    soft table): it records every alert and whether it would have rung. `fail` makes it raise."""

    clock: Callable[[], datetime]
    settings: NotifySettings = field(default_factory=NotifySettings)
    storm: Storm = field(default_factory=Storm)
    sent: list[Sent] = field(default_factory=list)
    fail: bool = False

    async def notify(
        self,
        uid: str,
        signal: Signal,
        message: str,
        *,
        named_message: str | None = None,
        photo: bytes | None = None,
    ) -> Delivery:
        if self.fail:
            raise RuntimeError("telegram said: secret vendor words")
        now = self.clock()
        decision = decide(signal, self.settings, now)
        admitted = (
            decision.action in ("ring", "silent")
            and self.storm.admit(uid, signal, decision, now).admit
        )
        rang = admitted and decision.action == "ring"
        self.sent.append(Sent(uid, signal.kind, signal.subject, message, SENDING.get(), rang))
        return Delivery(action=decision.action, reason=decision.reason, telegram=admitted)

    def kinds(self) -> list[str]:
        return [s.kind for s in self.sent]

    def rings(self) -> list[Sent]:
        return [s for s in self.sent if s.rang]


class BrokenDocs(Docs):
    """A document store that is down: every call raises (a whole-Firestore outage)."""

    def __init__(self) -> None:
        self.calls = 0

    def _down(self) -> RuntimeError:
        self.calls += 1
        return RuntimeError("firestore: 503 secret backend words")

    async def get(self, path: str) -> dict[str, Any] | None:
        raise self._down()

    async def query(self, q: Query) -> list[tuple[str, dict[str, Any]]]:
        raise self._down()

    async def write(self, ops: Sequence[Op]) -> None:
        raise self._down()

    async def transaction(self, fn: Callable[[DocTx], Any]) -> Any:
        raise self._down()


@dataclass
class FakeTodayView:
    date: str
    tz: str
    status: str
    due_at: datetime | None


@dataclass
class FakeBrief:
    """`BriefService.today(uid)` and `owners` as Part B reads them."""

    status: str = "none"
    due_at: datetime | None = None
    date: str = "2026-11-16"
    tz: str = "Asia/Kolkata"
    owners: tuple[str, ...] = (UID,)
    calls: int = 0
    raises: bool = False

    async def today(self, uid: str) -> FakeTodayView:
        self.calls += 1
        if self.raises:
            raise RuntimeError("google said: secret words")
        return FakeTodayView(self.date, self.tz, self.status, self.due_at)


@dataclass
class FakeMonth:
    inr_total: float


@dataclass
class FakeBilling:
    """`Billing.month(uid)`: this month's total in rupees, as the meter keeps it."""

    inr: dict[str, float] = field(default_factory=dict)
    raises: bool = False

    async def month(self, uid: str) -> FakeMonth:
        if self.raises:
            raise RuntimeError("usage unreadable")
        return FakeMonth(self.inr.get(uid, 0.0))


def memory_docs() -> MemoryDocs:
    return MemoryDocs()


class FlakyJob:
    """A tick job that fails (raises) while `failing` is set, else answers ok."""

    def __init__(self, name: str, *, failing: bool = True, budget_s: float = 5.0) -> None:
        self.name, self.budget_s, self.failing = name, budget_s, failing

    async def run(self, owners: Sequence[str]) -> dict[str, int]:
        if self.failing:
            raise RuntimeError(f"{self.name}: secret backend words")
        return {"done": 1}


def settings(**kw: Any) -> Settings:
    return Settings(_env_file=None, **kw)


@dataclass
class BWorld:
    """Part B's watch on fakes: memory documents, the ring counter, a settable clock."""

    watch: Watch
    ring: RingCounter
    clock: Clock
    docs: Docs
    brief: FakeBrief
    billing: FakeBilling

    async def watchdog(self, *jobs: Any) -> dict[str, str]:
        """One 5-minute run: `selfwatch_clock` first, then `jobs`, the observer listening."""
        got = await run_jobs(
            (self.watch.clock_job, *jobs), self.brief.owners, observer=self.watch.observe,
            clock="watchdog", total_budget_s=50.0,
        )  # fmt: skip
        return dict(got)

    async def tick(self, *jobs: Any) -> dict[str, str]:
        """One morning tick: `jobs`, then `selfwatch_daily` (R14's daily jobs come last)."""
        got = await run_jobs(
            (*jobs, self.watch.daily_job), self.brief.owners, observer=self.watch.observe
        )
        return dict(got)


def build_world(
    *, now: datetime = NOON, docs: Docs | None = None, version: str = "14.0.0", **kw: Any
) -> BWorld:
    clock = Clock(now)
    ring = RingCounter(clock)
    brief, billing = FakeBrief(), FakeBilling()
    store = docs if docs is not None else MemoryDocs()
    watch = Watch(
        settings(**kw), store, notifier=lambda: ring, brief=lambda: brief,
        billing=lambda: billing, now=clock, version=version,
    )  # fmt: skip
    return BWorld(watch, ring, clock, store, brief, billing)


__all__ = [
    "NOON",
    "OTHER",
    "TWO_AM",
    "UID",
    "BWorld",
    "BrokenDocs",
    "Clock",
    "FakeBilling",
    "FakeBrief",
    "FakeMonth",
    "FakeTodayView",
    "FlakyJob",
    "RingCounter",
    "Sent",
    "build_world",
    "memory_docs",
    "settings",
]
