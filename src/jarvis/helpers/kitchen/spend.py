# src/jarvis/helpers/kitchen/spend.py
"""Grocery spend a month from his e-mailed receipts (docs/plans/r11-free-helpers.md D15, item 15).

`GrocerySpendJob` (`grocery_spend`, the morning tick's daily composite) runs for the configured
owners (`ctx.owners`; the caller's list is ignored), each only when:
  - the keyring is there (receipts are sealed, purpose `spend`): otherwise "off";
  - he switched receipts on in the Kitchen tab (`spend_scan.on`, default off): otherwise "off";
  - his permission rows ALLOW both "Search and read email" (`gmail_*`, R1) and the Kitchen row
    (`spend_*`, R1); "Ask first" counts as no (a background reader can't ask), and rows that can't
    be read, or aren't wired yet, mean no (fail closed): "skipped".
Then it lists his Gmail (the fixed merchants' domains only, since the last scan, at most 35 days,
at most 60 messages), skips mails already read (keyed hashes in `spend_scan`), reads the rest as
the parcels reader does (`GoogleConnector.request`, format=full, a few at a time; one unreadable
mail never hides the others) and keeps, per month, only merchant, day, amount and a keyed hash
(`receipts.read_receipt`, `store.SpendStore`). One audit line per owner (agent `helpers`, the
kind and counts only); logs carry class names and counts, never an amount or a merchant.
"""

from __future__ import annotations

import asyncio
import re
from collections.abc import Callable, Sequence
from datetime import datetime
from typing import Any

from jarvis.billing.service import rupees
from jarvis.core.guardrails import ActionRisk
from jarvis.helpers.kitchen.models import ScanState, SpendMonth
from jarvis.helpers.kitchen.receipts import gmail_query, read_receipt
from jarvis.helpers.kitchen.store import KitchenOff, SpendStore
from jarvis.integrations.google import GoogleAPIError, GoogleConnector, GoogleNotConnected
from jarvis.logging import get_logger
from jarvis.notify.quiet import local
from jarvis.tools.audit import AuditTrail
from jarvis.tools.gmail import MESSAGES_URL
from jarvis.tools.policy import Effect, OwnerRules, Policy

log = get_logger(__name__)

JOB = "grocery_spend"
AGENT = "helpers"
JOB_BUDGET_S = 15.0
FIRST_DAYS = MAX_DAYS = 35
OVERLAP_DAYS = 2
MAX_SCAN = 60
READ_PARALLEL = 4
ROW_TOOLS = ("gmail_search", "spend_month")  # "Search and read email" and the Kitchen row
OFF_LINE = "Grocery spend is off, Sir: switch on 'Read my grocery receipts' in Helpers, Kitchen."
_ID_OK = frozenset("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-")
_MONTH = re.compile(r"^(\d{4})-(0[1-9]|1[0-2])$")
_NAMES = ("January February March April May June July August September October November "
          "December").split()  # fmt: skip


def month_label(month: str) -> str:
    year, mm = month.split("-")
    return f"{_NAMES[int(mm) - 1]} {year}"


def _view(m: SpendMonth) -> dict[str, Any]:
    return {
        "month": m.month,
        "label": month_label(m.month),
        "total": rupees(m.total_paise / 100),
        "total_paise": m.total_paise,
        "orders": len(m.orders),
        "by_merchant": {k: rupees(v / 100) for k, v in m.by_merchant().items()},
    }


class SpendService:
    def __init__(
        self,
        store: SpendStore,
        *,
        google: GoogleConnector | None,
        now: Callable[[], datetime],
        tz: str = "Asia/Kolkata",
    ) -> None:
        self.store = store
        self._google = google
        self._now = now
        self._tz = tz

    @property
    def can_scan(self) -> bool:
        return self.store.sealed and self._google is not None

    async def set_on(self, uid: str, on: bool) -> ScanState:
        if not self.store.sealed:
            raise KitchenOff()
        return await self.store.set_scan(uid, lambda s: s.model_copy(update={"on": bool(on)}))

    async def totals(self, uid: str) -> list[dict[str, Any]]:
        return [_view(m) for m in await self.store.months(uid)]

    def _this_month(self) -> str:
        return local(self._now(), self._tz).strftime("%Y-%m")

    async def month(self, uid: str, month: str | None) -> dict[str, Any]:
        """One month's total as a fixed-template line (this month when `month` is None)."""
        want = month or self._this_month()
        if not _MONTH.match(want):
            raise ValueError("month must read YYYY-MM, such as 2026-11")
        if not self.store.sealed:
            return {"message": str(KitchenOff()), "unavailable": True}
        if not (await self.store.scan(uid)).on:
            return {"message": OFF_LINE, "off": True}
        found = next((m for m in await self.store.months(uid) if m.month == want), None)
        if found is None or not found.orders:
            return {"message": f"No grocery receipts found for {month_label(want)}, Sir."}
        v = _view(found)
        n = v["orders"]
        shops = ", ".join(v["by_merchant"])
        v["message"] = (
            f"Groceries in {v['label']}: about {v['total']} from {n} order{'s' if n != 1 else ''} "
            f"(from your e-mailed receipts: {shops})."
        )
        return v

    def _days(self, state: ScanState) -> int:
        if not state.last_at:
            return FIRST_DAYS
        try:
            since = (self._now() - datetime.fromisoformat(state.last_at)).days
        except (TypeError, ValueError):
            return FIRST_DAYS
        return max(1, min(MAX_DAYS, since + OVERLAP_DAYS))

    async def _ids(self, uid: str, days: int) -> list[str]:
        assert self._google is not None
        listing = await self._google.request(
            uid, "GET", MESSAGES_URL, params={"q": gmail_query(days), "maxResults": MAX_SCAN}
        )
        rows = listing.get("messages") if isinstance(listing, dict) else None
        ids = [str(x.get("id")) for x in rows or [] if isinstance(x, dict) and x.get("id")]
        return [i for i in ids if set(i) <= _ID_OK][:MAX_SCAN]

    async def _read(self, uid: str, ids: Sequence[str]) -> list[dict[str, Any] | None]:
        assert self._google is not None
        conn, gate = self._google, asyncio.Semaphore(READ_PARALLEL)

        async def one(mid: str) -> dict[str, Any] | None:
            async with gate:
                try:
                    m = await conn.request(
                        uid, "GET", f"{MESSAGES_URL}/{mid}", params={"format": "full"}
                    )
                except GoogleNotConnected:
                    raise
                except GoogleAPIError:
                    return None  # read again next time
            return m if isinstance(m, dict) else None

        return list(await asyncio.gather(*(one(i) for i in ids)))

    async def scan_owner(self, uid: str) -> dict[str, int]:
        """Read his new receipts and keep their totals; counts only."""
        if not self.can_scan:
            raise KitchenOff()
        state = await self.store.scan(uid)
        seen = set(state.seen)
        keyed = [
            (i, self.store.key(uid, f"msg:{i}")) for i in await self._ids(uid, self._days(state))
        ]
        fresh = [(i, k) for i, k in keyed if k not in seen]
        mails = await self._read(uid, [i for i, _ in fresh])
        got = [
            read_receipt(m, mac=lambda t: self.store.key(uid, t), tz=self._tz)
            for m in mails
            if m is not None
        ]
        receipts = [r for r in got if r is not None]
        await self.store.apply(uid, receipts)
        read = tuple(k for (_, k), m in zip(fresh, mails, strict=True) if m is not None)
        at = self._now().isoformat()
        await self.store.set_scan(
            uid, lambda s: s.model_copy(update={"last_at": at, "seen": (*s.seen, *read)})
        )
        return {"mails": len(keyed), "read": len(read), "orders": len(receipts),
                "ignored": len(read) - len(receipts)}  # fmt: skip


class GrocerySpendJob:
    """The daily `grocery_spend` job (D3: the morning tick's `helpers_daily`)."""

    name = JOB
    budget_s = JOB_BUDGET_S

    def __init__(
        self,
        svc: SpendService,
        *,
        owners: tuple[str, ...],
        permissions: Callable[[], OwnerRules | None],
        audit: AuditTrail,
    ) -> None:
        self._svc = svc
        self._owners = owners
        self._permissions = permissions
        self._audit = audit

    async def _allowed(self, uid: str) -> bool:
        source = self._permissions()
        if source is None:
            return False  # the rows aren't wired: fail closed
        try:
            policy = Policy(await source.rules_for(uid))
        except Exception as exc:  # noqa: BLE001 - fail closed: no read this morning
            log.warning("permissions unreadable for receipts", extra={"error": type(exc).__name__})
            return False
        return all(policy.decide(t, ActionRisk.READ_ONLY, {}) is Effect.ALLOW for t in ROW_TOOLS)

    async def _note(self, outcome: str, detail: str) -> None:
        try:
            await self._audit.append(
                agent=AGENT,
                tool=JOB,
                risk=ActionRisk.READ_ONLY,
                outcome=outcome,
                args={"kind": JOB},
                detail=detail,
            )
        except Exception as exc:  # noqa: BLE001 - the read already happened; say so loudly
            log.error(
                "AUDIT WRITE FAILED for grocery receipts", extra={"error": type(exc).__name__}
            )

    async def _one(self, uid: str) -> str:
        svc = self._svc
        if not svc.can_scan or not (await svc.store.scan(uid)).on:
            return "off"
        if not await self._allowed(uid):
            await self._note("skipped", "permissions")
            return "skipped"
        try:
            c = await svc.scan_owner(uid)
        except GoogleNotConnected:
            await self._note("skipped", "google not linked")
            return "skipped"
        detail = f"mails={c['mails']} read={c['read']} orders={c['orders']} ignored={c['ignored']}"
        await self._note("executed", detail)
        return "ok"

    async def run(self, owners: Sequence[str]) -> dict[str, int]:
        """`owners` (the caller's list) is ignored: the helpers serve the configured owners."""
        counts = {"owners": len(self._owners), "ok": 0, "off": 0, "skipped": 0, "failed": 0}
        for uid in self._owners:
            try:
                counts[await self._one(uid)] += 1
            except Exception as exc:  # noqa: BLE001 - one owner never stops the others
                log.warning("grocery receipts not read", extra={"error": type(exc).__name__})
                await self._note("error", type(exc).__name__)
                counts["failed"] += 1
        return counts


__all__ = ["JOB", "OFF_LINE", "GrocerySpendJob", "SpendService", "month_label"]
