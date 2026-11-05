# src/jarvis/vitals/service.py
"""The Vitals board and its alerts (R4 D2-D4). No model call: meters, arithmetic and fixed words.

`board(uid)` merges the owner's manual records with the `auto` ones the meters give and computes
each status now. `check_and_alert` tells the owner ONCE when a provider crosses UP a status line
(ok -> amber: `vitals_warn`; -> red: `vitals_critical`); the last status is kept per provider in
`jarvis_vitals_status`. "unknown" never alerts and never overwrites the last status; a send that
fails is not recorded, so the next tick tries again.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from jarvis.billing.service import rupees
from jarvis.config import Settings
from jarvis.logging import get_logger
from jarvis.notify.ports import Notifier, Signal
from jarvis.quota.ledger import QuotaLedger
from jarvis.vitals import auto
from jarvis.vitals.auto import AllowanceSpec, BillingLike
from jarvis.vitals.models import RANK, Board, Provider, ProviderView, Spend
from jarvis.vitals.status import overall, status_of
from jarvis.vitals.store import VitalsStore

log = get_logger(__name__)

AUTO_IDS_PREFIXES = ("quota_", "allowance_")
RESERVED = "That name is used by a built-in item. Pick another id."
MESSAGE_MAX = 300


def utcnow() -> datetime:
    return datetime.now(UTC)


def reserved(pid: str) -> bool:
    return pid == auto.SPEND_ID or pid.startswith(AUTO_IDS_PREFIXES)


def alert_text(v: ProviderView) -> str:
    p = v.provider
    lead = "Critical" if v.status == "red" else "Heads-up"
    detail = ""
    if p.unit == auto.RUPEE and p.used is not None and p.limit is not None:
        detail = f" ({rupees(p.used)} of {rupees(p.limit)})"
    return f"{lead}: {p.label} {v.reason}{detail}."[:MESSAGE_MAX]


class VitalsService:
    def __init__(
        self,
        store: VitalsStore,
        settings: Settings,
        *,
        billing: BillingLike | None = None,
        ledger: QuotaLedger | None = None,
        allowances: Sequence[AllowanceSpec] = (),
        clock: Callable[[], datetime] = utcnow,
    ) -> None:
        self._store = store
        self._s = settings
        self._billing = billing
        self._ledger = ledger
        self._allowances = tuple(allowances)
        self._clock = clock

    async def _auto(self, uid: str, now: datetime) -> tuple[list[Provider], Spend | None]:
        out: list[Provider] = []
        spend: Spend | None = None
        if self._billing is not None:
            tz = ZoneInfo(self._s.user_timezone)
            p, spend = await auto.spend(self._billing, uid, now, tz)
            out.append(p)
            out.extend(await auto.allowances(self._billing, self._allowances))
        if self._ledger is not None:
            for sku in self._ledger.skus.values():
                out.append(await auto.quota(self._ledger, sku, now))
        return out, spend

    async def board(self, uid: str) -> Board:
        now = self._clock()
        autos, spend = await self._auto(uid, now)
        manual = await self._store.list_manual(uid)
        views = tuple(
            status_of(p, now, self._s.vitals_amber_fraction, self._s.vitals_expiry_amber_days)
            for p in [*autos, *manual]
        )
        return Board(items=views, spend=spend, overall=overall(views))

    async def set_key(self, uid: str, p: Provider) -> None:
        if reserved(p.id):
            raise ValueError(RESERVED)
        await self._store.put(uid, p.model_copy(update={"source": "manual"}))

    async def delete_key(self, uid: str, pid: str) -> bool:
        if reserved(pid):
            return False
        return await self._store.delete(uid, pid)

    async def check_and_alert(self, uid: str, notifier: Notifier) -> int:
        """Alert on every upward line-cross; returns how many alerts were sent."""
        now = self._clock()
        sent = 0
        for v in (await self.board(uid)).items:
            if v.status == "unknown":
                continue
            pid = v.provider.id
            last = await self._store.last_status(uid, pid) or "ok"
            if v.status == last:
                continue
            if RANK[v.status] > RANK[last]:
                if not await self._send(uid, notifier, v):
                    continue
                sent += 1
            await self._store.set_status(uid, pid, v.status, now)
        return sent

    @staticmethod
    async def _send(uid: str, notifier: Notifier, v: ProviderView) -> bool:
        signal = (
            Signal(source="system", kind="vitals_critical")
            if v.status == "red"
            else Signal(source="system", kind="vitals_warn")
        )
        try:
            await notifier.notify(uid, signal, alert_text(v))
        except Exception as exc:  # noqa: BLE001 - not recorded, so the next tick retries
            log.warning("vitals alert failed", extra={"reason": type(exc).__name__})
            return False
        return True


__all__ = ["VitalsService", "alert_text", "reserved"]
