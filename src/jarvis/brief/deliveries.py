# src/jarvis/brief/deliveries.py
"""The brief's Deliveries section (R1 D13): parcels on their way, from the owner's order emails.

Deterministic: `packages.parse` reads the mails, no model is involved, and the section is never
part of the AI-summary input (`brief.summarize` names its blocks one by one). Shows parcels that are
ordered, shipped or out for delivery, and ones delivered today; at most 5. It fails on its own: the
service turns any error here into `state: unavailable` and the rest of the brief is unaffected.

R11.1 I1 (security review M1): the scan reads mail, so it asks the "Search and read email" row
first through `BackgroundReads.allowed`, the same gate as the inbox section: only "Allow" reads,
with one audit line; "Never" and "Ask first" raise `NotRead` before any Gmail request (the
service shows the section as paused by his Permissions). No `reads`: the old path (tests).
"""

from __future__ import annotations

from datetime import date, tzinfo

from jarvis.brief.models import DeliveriesSection, DeliveryItem
from jarvis.packages.parse import Package, carrier_name
from jarvis.packages.tools import PackageScanner
from jarvis.tools.background import BackgroundReads, NotRead
from jarvis.tools.card import one_line
from jarvis.tools.spoken import withhold_if_sensitive

MAX_SHOWN = 5
SCAN_DAYS = 14
ITEM_LIMIT = 120
ACTIVE = frozenset({"ordered", "shipped", "out_for_delivery"})
DELIVERIES_TOOL = "gmail_track_packages"  # the same mail read, under the same row
READ_JOB = "brief"  # the background read's name in the audit chain (as the inbox section's)


def relevant(p: Package, day: date, tz: tzinfo) -> bool:
    return p.status in ACTIVE or (
        p.status == "delivered" and p.updated.astimezone(tz).date() == day
    )


def shape(p: Package) -> DeliveryItem:
    return DeliveryItem(
        # a code or bank message in someone else's subject is never stored in the brief
        item=withhold_if_sensitive(one_line(p.item, ITEM_LIMIT)) or "(no subject)",
        status=p.status,
        merchant=p.merchant or "",
        carrier=carrier_name(p.carrier) or "",
        expected=p.expected.isoformat() if p.expected else "",
    )


class DeliveriesBrief:
    def __init__(
        self,
        scanner: PackageScanner,
        *,
        days: int = SCAN_DAYS,
        reads: BackgroundReads | None = None,
    ) -> None:
        self._scanner = scanner
        self._days = days
        self._reads = reads

    async def section(self, uid: str, tz: tzinfo, day: date) -> DeliveriesSection:
        if self._reads is None:
            packages, _ = await self._scanner.scan(uid, self._days)
        elif not await self._reads.allowed(uid, DELIVERIES_TOOL, job=READ_JOB):
            raise NotRead("the mail row does not allow a background read")
        else:
            async with self._reads.reading(DELIVERIES_TOOL, job=READ_JOB):
                packages, _ = await self._scanner.scan(uid, self._days)
        kept = [p for p in packages if relevant(p, day, tz)]
        return DeliveriesSection(
            total=len(kept), items=tuple(shape(p) for p in kept[:MAX_SHOWN]), state="ok"
        )


__all__ = ["ACTIVE", "DELIVERIES_TOOL", "MAX_SHOWN", "DeliveriesBrief", "relevant", "shape"]
