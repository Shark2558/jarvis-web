# src/jarvis/helpers/kitchen/spend.py
"""Grocery spend a month from his e-mailed receipts (docs/plans/r11-free-helpers.md D15, item 15).

`GrocerySpendJob` (`grocery_spend`, the morning tick's daily composite) runs for the configured
owners (`ctx.owners`; the caller's list is ignored), each only when:
  - the keyring is there (receipts are sealed, purpose `spend`): otherwise "off";
  - he switched receipts on in the Kitchen tab (`spend_scan.on`, default off): otherwise "off";
  - the gateway's governed path (I1, `ctx.reads`) ALLOWs both "Search and read email"
    (`gmail_*`, R1) and the Kitchen row (`spend_*`, R1); "Ask first" counts as no (a background
    reader can't ask), and rows that can't be read, or no gateway, mean no (fail closed): "skipped".
Then it lists his Gmail (the fixed merchants' mail only, since the last complete scan, at most 35
days), page after page (Gmail's `nextPageToken`, up to 10 pages of 100), skips mails already read
(keyed hashes in `spend_scan`), reads the rest as the parcels reader does
(`GoogleConnector.request`, format=full, a few at a time, at most 150 a run; one unreadable mail
never hides the others) and keeps, per month, only merchant, day, amount and a keyed hash
(`receipts.read_receipt`, `store.SpendStore`). The last scan moves only when the whole window was
listed and every new mail read; out of time (an 11 s budget for the whole run, inside the job's
15 s), or a mail that failed, leaves it where it was, so the next run looks back as far and
reads what is left: an older receipt is never lost. The governed path's one kind-only audit line
per owner (agent `helpers`, `gmail_search`, "grocery_spend"); the counts go to the log only
(class names and counts, never an amount or a merchant).
"""

from __future__ import annotations

import asyncio
import re
import time
from collections.abc import Callable, Sequence
from datetime import datetime
from typing import Any

from jarvis.billing.service import rupees
from jarvis.helpers.kitchen.models import ScanState, SpendMonth
from jarvis.helpers.kitchen.receipts import PLAUSIBLE_PAISE, gmail_query, read_receipt
from jarvis.helpers.kitchen.store import KitchenOff, SpendStore
from jarvis.integrations.google import GoogleAPIError, GoogleConnector, GoogleNotConnected
from jarvis.logging import get_logger
from jarvis.notify.quiet import local
from jarvis.tools.background import BackgroundReads, Outcome
from jarvis.tools.gmail import MESSAGES_URL

log = get_logger(__name__)

JOB = "grocery_spend"
JOB_BUDGET_S = 15.0
SCAN_BUDGET_S = 11.0  # the whole run's listing and reading, leaving the job time to save
FIRST_DAYS = MAX_DAYS = 35
OVERLAP_DAYS = 2
PAGE = 100
MAX_PAGES = 10
MAX_READS = 150
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
        "flagged": len(m.flagged),
        "by_merchant": {k: rupees(v / 100) for k, v in m.by_merchant().items()},
    }


def flagged_line(n: int) -> str:
    """A fixed line for receipts whose total was too large to be groceries (never added)."""
    if not n:
        return ""
    many = n != 1
    return (
        f" {n} receipt{'s' if many else ''} over {rupees(PLAUSIBLE_PAISE / 100)} "
        f"{'weren' if many else 'wasn'}'t counted: check {'them' if many else 'it'} in your mail."
    )


def _token(listing: Any) -> tuple[bool, str | None]:
    """(the listing is over, the next page's token); a token we can't follow ends it unread."""
    raw = listing.get("nextPageToken") if isinstance(listing, dict) else None
    if raw is None:
        return True, None
    ok = isinstance(raw, str) and 0 < len(raw) <= 512 and set(raw) <= _ID_OK
    return False, raw if ok else None


def _page_ids(listing: Any) -> list[str]:
    rows = listing.get("messages") if isinstance(listing, dict) else None
    ids = [str(x.get("id")) for x in rows or [] if isinstance(x, dict) and x.get("id")]
    return [i for i in ids if set(i) <= _ID_OK]


class SpendService:
    def __init__(
        self,
        store: SpendStore,
        *,
        google: GoogleConnector | None,
        now: Callable[[], datetime],
        tz: str = "Asia/Kolkata",
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.store = store
        self._google = google
        self._now = now
        self._tz = tz
        self.clock = clock

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
        odd = flagged_line(len(found.flagged) if found else 0)
        if found is None or not found.orders:
            return {"message": f"No grocery receipts found for {month_label(want)}, Sir.{odd}"}
        v = _view(found)
        n = v["orders"]
        shops = ", ".join(v["by_merchant"])
        v["message"] = (
            f"Groceries in {v['label']}: about {v['total']} from {n} order{'s' if n != 1 else ''} "
            f"(from your e-mailed receipts: {shops}).{odd}"
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

    async def _ids(self, uid: str, days: int, deadline: float) -> tuple[list[str], bool]:
        """Every message id in the window, page after page: (ids, the window was covered)."""
        assert self._google is not None
        ids: list[str] = []
        token: str | None = None
        for _ in range(MAX_PAGES):
            if self.clock() >= deadline:
                break
            params: dict[str, Any] = {"q": gmail_query(days), "maxResults": PAGE}
            if token:
                params["pageToken"] = token
            listing = await self._google.request(uid, "GET", MESSAGES_URL, params=params)
            ids.extend(_page_ids(listing))
            over, token = _token(listing)
            if over or token is None:
                return list(dict.fromkeys(ids)), over
        return list(dict.fromkeys(ids)), False

    async def _read(
        self, uid: str, ids: Sequence[str], deadline: float
    ) -> list[dict[str, Any] | None]:
        """Each message, or None when it failed or the time ran out (read it next run)."""
        assert self._google is not None
        conn, gate = self._google, asyncio.Semaphore(READ_PARALLEL)

        async def one(mid: str) -> dict[str, Any] | None:
            async with gate:
                if self.clock() >= deadline:
                    return None
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

    async def scan_owner(self, uid: str, deadline: float | None = None) -> dict[str, int]:
        """Read his new receipts and keep their totals; counts only. The last scan moves only
        when the window was covered and every new mail was read (`complete`)."""
        if not self.can_scan:
            raise KitchenOff()
        deadline = self.clock() + SCAN_BUDGET_S if deadline is None else deadline
        at = self._now().isoformat()
        state = await self.store.scan(uid)
        ids, covered = await self._ids(uid, self._days(state), deadline)
        fresh = [(i, k) for i in ids if (k := self.store.key(uid, f"msg:{i}")) not in state.seen]
        todo = fresh[:MAX_READS]
        mails = await self._read(uid, [i for i, _ in todo], deadline)
        got = [
            read_receipt(m, mac=lambda t: self.store.key(uid, t), tz=self._tz)
            for m in mails
            if m is not None
        ]
        receipts = [r for r in got if r is not None]
        await self.store.apply(uid, receipts)
        read = tuple(k for (_, k), m in zip(todo, mails, strict=True) if m is not None)
        complete = covered and len(read) == len(fresh)
        moved = {"last_at": at} if complete else {}
        await self.store.set_scan(
            uid, lambda s: s.model_copy(update={**moved, "seen": (*s.seen, *read)})
        )
        flagged = sum(1 for r in receipts if r.flagged)
        return {"mails": len(ids), "read": len(read), "orders": len(receipts) - flagged,
                "ignored": len(read) - len(receipts), "flagged": flagged,
                "complete": int(complete)}  # fmt: skip


class GrocerySpendJob:
    """The daily `grocery_spend` job (D3: the morning tick's `helpers_daily`)."""

    name = JOB
    budget_s = JOB_BUDGET_S

    def __init__(
        self, svc: SpendService, *, owners: tuple[str, ...], reads: BackgroundReads | None
    ) -> None:
        self._svc = svc
        self._owners = owners
        self._reads = reads  # I1: the gateway's governed path (None: no read at all)

    async def _note(self, outcome: Outcome, why: str = "") -> None:
        if self._reads is not None:
            await self._reads.note(ROW_TOOLS[0], job=JOB, outcome=outcome, why=why)

    async def scan_one(self, uid: str, deadline: float | None = None) -> str:
        """One owner: "ok", "off" or "skipped" (the governed path refused, or Google not linked).
        The audit line is kind-only; the counts go to the log (counts only, never an amount)."""
        svc, reads = self._svc, self._reads
        if not svc.can_scan or not (await svc.store.scan(uid)).on:
            return "off"
        if reads is None or not await reads.allowed(uid, *ROW_TOOLS, job=JOB):
            return "skipped"
        try:
            c = await svc.scan_owner(uid, deadline)
        except GoogleNotConnected:
            await self._note("denied", "not linked")
            return "skipped"
        log.info(
            "grocery receipts read",
            extra={k: c[k] for k in ("mails", "read", "orders", "ignored", "flagged", "complete")},
        )
        await self._note("executed")
        return "ok"

    async def run(self, owners: Sequence[str]) -> dict[str, int]:
        """`owners` (the caller's list) is ignored: the helpers serve the configured owners,
        within one time budget for them all."""
        counts = {"owners": len(self._owners), "ok": 0, "off": 0, "skipped": 0, "failed": 0}
        deadline = self._svc.clock() + SCAN_BUDGET_S
        for uid in self._owners:
            try:
                counts[await self.scan_one(uid, deadline)] += 1
            except Exception as exc:  # noqa: BLE001 - one owner never stops the others
                log.warning("grocery receipts not read", extra={"error": type(exc).__name__})
                await self._note("error", "failed")
                counts["failed"] += 1
        return counts


__all__ = ["JOB", "OFF_LINE", "GrocerySpendJob", "SpendService", "flagged_line", "month_label"]
