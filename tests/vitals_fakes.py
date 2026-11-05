# tests/vitals_fakes.py -- a Vitals service over MemoryDocs with a fake billing and notifier (R4 A).
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from jarvis.billing import UsageView
from jarvis.billing.service import BudgetUnavailable, RateView
from jarvis.config import Settings
from jarvis.notify.ports import Delivery, Signal
from jarvis.quota.ledger import QuotaLedger
from jarvis.storage.docs import MemoryDocs
from jarvis.vitals.models import Provider
from jarvis.vitals.service import VitalsService
from jarvis.vitals.store import VitalsStore

UID = "u_owner"
OTHER = "u_other"
T0 = datetime(2026, 11, 5, 12, 0, tzinfo=UTC)


class Clock:
    def __init__(self, now: datetime = T0) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now

    def advance(self, **kw: float) -> None:
        self.now = self.now + timedelta(**kw)


def usage_view(used: float = 100.0, limit: int | None = 500) -> UsageView:
    pct = None if limit is None else round(used / limit * 100, 2)
    return UsageView(
        month="2026-11",
        used_inr=used,
        limit_inr=limit,
        remaining_inr=None if limit is None else max(0.0, limit - used),
        percent=pct,
        warn=limit is not None and used >= 0.8 * limit,
        reached=limit is not None and used >= limit,
        calls=3,
        by_brain=[],
        rate=RateView(inr_per_usd=85.0, as_of=None, source="default"),
    )


class FakeBilling:
    def __init__(self, view: UsageView | None = None, *, down: bool = False) -> None:
        self.view = view or usage_view()
        self.down = down

    async def usage(self, uid: str) -> UsageView:
        if self.down:
            raise BudgetUnavailable()
        return self.view


class FakeNotifier:
    def __init__(self, *, fail: bool = False) -> None:
        self.sent: list[tuple[str, Signal, str]] = []
        self.fail = fail

    async def notify(self, uid: str, signal: Signal, message: str, **_kw: Any) -> Delivery:
        if self.fail:
            raise RuntimeError("telegram down")
        self.sent.append((uid, signal, message))
        return Delivery(action="silent", reason="ok")

    @property
    def kinds(self) -> list[str]:
        return [s.kind for _, s, _ in self.sent]


class Rig:
    def __init__(self, *, billing: FakeBilling | None = None, with_ledger: bool = False) -> None:
        self.docs = MemoryDocs()
        self.clock = Clock()
        self.settings = Settings()
        self.store = VitalsStore(self.docs)
        self.billing = billing if billing is not None else FakeBilling()
        self.ledger = QuotaLedger(self.docs, now=self.clock) if with_ledger else None
        self.svc = VitalsService(
            self.store,
            self.settings,
            billing=self.billing,  # type: ignore[arg-type]
            ledger=self.ledger,
            clock=self.clock,
        )
        self.notifier = FakeNotifier()


def key(
    pid: str = "brave",
    *,
    limit: float | None = None,
    used: float | None = None,
    expires_in_days: float | None = None,
    now: datetime = T0,
    **kw: Any,
) -> Provider:
    return Provider(
        id=pid,
        label=kw.pop("label", pid.title()),
        kind=kw.pop("kind", "key"),
        source=kw.pop("source", "manual"),
        limit=limit,
        used=used,
        expires_at=None if expires_in_days is None else now + timedelta(days=expires_in_days),
        **kw,
    )
