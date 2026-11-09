# src/jarvis/vitals/service.py
"""The Vitals board and its alerts (R4 D2-D4). No model call: meters, arithmetic and fixed words.

`board(uid)` merges the owner's manual records with the `auto` ones the meters give and, since
R5.1 D2, JARVIS's own keys and connections (`jarvis.vitals.own`), and computes each status now.
Manual records that can't be read never hide the rest (`manual_unavailable`).

`check_and_alert` tells the owner ONCE when a provider crosses UP a status line (ok -> amber:
`vitals_warn`; -> red: `vitals_critical`); the last status is kept per provider in
`jarvis_vitals_status`. "unknown" never alerts and never overwrites the last status; a send that
fails is not recorded, so the next tick tries again. Items another system already rings for
(`own.QUIET_IDS`) never alert from here.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Sequence
from datetime import UTC, datetime

from jarvis.billing.service import rupees
from jarvis.config import Settings
from jarvis.logging import get_logger
from jarvis.notify.ports import Notifier, Signal
from jarvis.quota.ledger import QuotaLedger
from jarvis.vitals import auto
from jarvis.vitals.auto import AllowanceSpec, BillingLike
from jarvis.vitals.models import (
    RANK,
    Board,
    Group,
    Provider,
    ProviderView,
    Spend,
    Status,
    group_of,
    zone_of,
)
from jarvis.vitals.own import OWN_IDS, QUIET_IDS, Own, OwnSources
from jarvis.vitals.status import overall, status_of
from jarvis.vitals.store import BAD_ID, VitalsStore, VitalsUnavailable, valid_id
from jarvis.vitals.words import words_for

log = get_logger(__name__)

AUTO_IDS_PREFIXES = ("quota_", "allowance_")
RESERVED = "That name is used by a built-in item. Pick another id."
MESSAGE_MAX = 300
ALERT_PREFIX = "Vitals — "  # fixed lead: a label can never pose as the sender
MANUAL_UNAVAILABLE = (
    "The items you track yourself can't be read just now; everything JARVIS watches on its own "
    "is shown. Try again in a minute."
)


def utcnow() -> datetime:
    return datetime.now(UTC)


def reserved(pid: str) -> bool:
    return pid == auto.SPEND_ID or pid in OWN_IDS or pid.startswith(AUTO_IDS_PREFIXES)


def alert_text(v: ProviderView) -> str:
    p = v.provider
    lead = "Critical" if v.status == "red" else "Heads-up"
    detail = ""
    if p.unit == auto.RUPEE and p.used is not None and p.limit is not None:
        detail = f" ({rupees(p.used)} of {rupees(p.limit)})"
    return f"{ALERT_PREFIX}{lead}: {p.label} {v.reason}{detail}."[:MESSAGE_MAX]


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
        own: OwnSources | None = None,
    ) -> None:
        self._store = store
        self._s = settings
        self._billing = billing
        self._ledger = ledger
        self._allowances = tuple(allowances)
        self._clock = clock
        self._own = Own(own, settings) if own is not None else None
        self._locks: dict[str, asyncio.Lock] = {}

    async def _auto(self, uid: str, now: datetime) -> tuple[list[Provider], Spend | None]:
        out: list[Provider] = []
        spend: Spend | None = None
        if self._billing is not None:
            tz = zone_of(self._s.user_timezone)
            p, spend = await auto.spend(self._billing, uid, now, tz)
            out.append(p)
            out.extend(await auto.allowances(self._billing, self._allowances))
        if self._ledger is not None:
            for sku in self._ledger.skus.values():
                out.append(await auto.quota(self._ledger, sku, now))
        return out, spend

    async def _manual(self, uid: str) -> list[Provider] | None:
        """The owner's own records, or None when they can't be read (the board still opens)."""
        try:
            rows = await self._store.list_manual(uid)
        except VitalsUnavailable:
            return None
        clash = [p.id for p in rows if reserved(p.id)]
        if clash:  # an old record under a name a built-in item now uses: the built-in wins
            log.warning(
                "vitals: manual records shadowed by built-in items", extra={"n": len(clash)}
            )
        return [p for p in rows if not reserved(p.id)]

    def _view(
        self, p: Provider, now: datetime, base: tuple[Status, str] | None = None
    ) -> ProviderView:
        v = status_of(
            p,
            now,
            self._s.vitals_amber_fraction,
            self._s.vitals_expiry_amber_days,
            zone_of(self._s.user_timezone),
            base=base,
        )
        if p.source == "manual":
            return v.model_copy(update={"group": group_of(p.kind)})
        impact, fix = words_for(p.id, p.label)
        group: Group = "bills" if p.id == auto.SPEND_ID else group_of(p.kind)
        return v.model_copy(update={"impact": impact, "fix": fix, "group": group})

    async def board(self, uid: str, now: datetime | None = None) -> Board:
        now = now or self._clock()
        autos, spend = await self._auto(uid, now)
        tz = zone_of(self._s.user_timezone)
        own = await self._own.items(uid, now, tz) if self._own is not None else []
        manual = await self._manual(uid)
        views = (
            *(self._view(p, now) for p in autos),
            *(
                self._view(i.provider, now, i.base).model_copy(update={"group": i.group})
                for i in own
            ),
            *(self._view(p, now) for p in manual or []),
        )
        return Board(
            items=views,
            spend=spend,
            overall=overall(views),
            manual_unavailable=manual is None,
            manual_note=MANUAL_UNAVAILABLE if manual is None else "",
        )

    async def set_key(self, uid: str, p: Provider) -> None:
        if reserved(p.id):
            raise ValueError(RESERVED)
        await self._store.put(uid, p.model_copy(update={"source": "manual"}))

    async def delete_key(self, uid: str, pid: str) -> bool:
        if not valid_id(pid):
            raise ValueError(BAD_ID)
        if reserved(pid):
            return False
        return await self._store.delete(uid, pid)

    async def check_and_alert(self, uid: str, notifier: Notifier) -> int:
        """Alert on every upward line-cross; returns how many alerts were sent.

        At-least-once: the alert goes out BEFORE the new status is recorded, so if recording
        fails the next poll sends it again (a repeat is better than a lost warning). One
        provider's storage trouble is counted and skipped; it never aborts the owner's other
        providers. Calls for one owner are serialised."""
        async with self._locks.setdefault(uid, asyncio.Lock()):
            now = self._clock()
            items = [
                v
                for v in (await self.board(uid, now)).items
                if v.status != "unknown" and v.provider.id not in QUIET_IDS  # rung elsewhere
            ]
            lasts = await asyncio.gather(
                *(self._store.last_status(uid, v.provider.id) for v in items),
                return_exceptions=True,
            )
            sent = 0
            for v, last in zip(items, lasts, strict=True):
                sent += await self._one(uid, notifier, v, last, now)
            return sent

    async def _one(
        self,
        uid: str,
        notifier: Notifier,
        v: ProviderView,
        last: Status | None | BaseException,
        now: datetime,
    ) -> int:
        if isinstance(last, BaseException):
            log.warning("vitals: status read failed", extra={"error": type(last).__name__})
            return 0
        before: Status = last or "ok"
        if v.status == before:
            return 0
        sent = 0
        if RANK[v.status] > RANK[before]:
            if not await self._send(uid, notifier, v):
                return 0
            sent = 1
        try:
            await self._store.set_status(uid, v.provider.id, v.status, now)
        except VitalsUnavailable as exc:
            log.warning("vitals: status not recorded", extra={"error": type(exc).__name__})
        return sent

    @staticmethod
    async def _send(uid: str, notifier: Notifier, v: ProviderView) -> bool:
        signal = (
            Signal(source="system", kind="vitals_critical", subject=v.provider.id)
            if v.status == "red"
            else Signal(source="system", kind="vitals_warn", subject=v.provider.id)
        )
        try:
            await notifier.notify(uid, signal, alert_text(v))
        except Exception as exc:  # noqa: BLE001 - not recorded, so the next tick retries
            log.warning("vitals alert failed", extra={"reason": type(exc).__name__})
            return False
        return True


__all__ = ["VitalsService", "alert_text", "reserved"]
