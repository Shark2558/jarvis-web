# tests/r14_fakes_b.py -- R14 Part B's fakes (self-health). Imported bare (`from r14_fakes_b
# import ...`); also used by evals/r14/selfwatch.py. Nothing here talks to Google, Telegram or
# spends anything; people are made up.
from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from jarvis.notify.models import NotifySettings
from jarvis.notify.policy import decide
from jarvis.notify.ports import Delivery, Signal
from jarvis.notify.storm import Storm
from jarvis.selfwatch.ports import SENDING
from jarvis.storage.docs import Docs, DocTx, MemoryDocs, Op, Query

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


__all__ = [
    "NOON",
    "OTHER",
    "TWO_AM",
    "UID",
    "BrokenDocs",
    "Clock",
    "FakeBilling",
    "FakeBrief",
    "FakeMonth",
    "FakeTodayView",
    "RingCounter",
    "Sent",
    "memory_docs",
]
