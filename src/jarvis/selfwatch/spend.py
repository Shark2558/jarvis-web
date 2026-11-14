# src/jarvis/selfwatch/spend.py
"""A day's AI spend far above normal (docs/plans/r14-hardening.md D5, review A6).

Once a day (the first morning tick of the owner's local day) the month's total so far in rupees
(`Billing.month(uid).inr_total`, the meter's own figure) is kept as that day's snapshot in
`{prefix}selfwatch/spend` (`{owners: {uid: {"YYYY-MM-DD": inr}}}`, the newest `KEEP` days: today
and 15 days back, so the average covers 14 whole days). A day's spend is its snapshot minus the
day before's; on the 1st the month total starts again (`billing/meter.py` `month_of`), so it is
that day's snapshot alone. After a missed snapshot (no morning tick that day) the difference is
spread evenly over the days since the last one (or since the 1st, when the month began again),
so the next day is still checked; the oldest snapshot, mid-month, has no day before it.

A spike: today's figure is more than `factor` (3) times the average of the up to 14 days before
it and at least `min_inr` (₹50); never before `HISTORY_MIN` (7) days of history. The alert says
only that figure (D6: the one amount an alert may carry). Counts and rupees only.

An owner's day is done (`settle`) only once his snapshot is kept and his spike (if any) was
said: a figure that could not be read or kept is tried again at the next tick the same day
(`Snapshot.failed`, so the job says so), and one owner's failure never costs another his.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Protocol
from zoneinfo import ZoneInfo

from jarvis.logging import get_logger
from jarvis.storage.docs import Docs, DocTx
from jarvis.undo.store import owner_ok

log = get_logger(__name__)

KEEP = 16
HISTORY_DAYS = 14
HISTORY_MIN = 7
MAX_OWNERS = 20


class MonthLike(Protocol):
    inr_total: float


class BillingLike(Protocol):
    async def month(self, uid: str) -> MonthLike: ...


def day_spends(snaps: Mapping[str, float]) -> list[tuple[str, float]]:
    """(day, rupees spent a day), oldest first; after a gap, the average over the gap."""
    out: list[tuple[str, float]] = []
    days = sorted(snaps)
    for prev, cur in zip([None, *days], days, strict=False):
        d = date.fromisoformat(cur)
        p = date.fromisoformat(prev) if prev is not None else None
        if prev is not None and p is not None and (p.year, p.month) == (d.year, d.month):
            spent, over = snaps[cur] - snaps[prev], (d - p).days
        elif d.day == 1 or p is not None:
            spent, over = snaps[cur], d.day  # the month total began again on the 1st
        else:
            continue
        out.append((cur, max(0.0, spent) / max(1, over)))
    return out


def spike(snaps: Mapping[str, float], day: str, factor: float, min_inr: float) -> float | None:
    """That day's spend when it is a spike, else None."""
    spends = day_spends(snaps)
    if not spends or spends[-1][0] != day:
        return None
    today = spends[-1][1]
    history = [v for _, v in spends[:-1]][-HISTORY_DAYS:]
    if len(history) < HISTORY_MIN or today < min_inr:
        return None
    return today if today > factor * (sum(history) / len(history)) else None


def _day_key(k: object) -> bool:
    if not isinstance(k, str) or len(k) != 10:
        return False
    try:
        date.fromisoformat(k)
    except ValueError:
        return False
    return True


def _series(raw: object) -> dict[str, float]:
    """An owner's stored snapshots; a damaged key or figure is left out."""
    if not isinstance(raw, dict):
        return {}
    out: dict[str, float] = {}
    for k, v in raw.items():
        ok = isinstance(v, int | float) and not isinstance(v, bool) and v >= 0
        if ok and _day_key(k):
            out[k] = float(v)
    return out


@dataclass(frozen=True)
class Snapshot:
    spikes: dict[str, float] = field(default_factory=dict)  # uid -> today's rupees, to tell
    failed: bool = False  # an owner's figure could not be read or kept (tried again later)


class SpendWatch:
    def __init__(
        self,
        billing: Callable[[], BillingLike | None],
        *,
        tz: ZoneInfo,
        factor: float,
        min_inr: float,
        prefix: str = "jarvis_",
    ) -> None:
        self._billing = billing
        self._tz = tz
        self._factor, self._min = factor, min_inr
        self._path = f"{prefix}selfwatch/spend"
        self._done: dict[str, str] = {}  # uid -> the local day already snapshotted

    def day_of(self, now: datetime) -> str:
        return now.astimezone(self._tz).date().isoformat()

    async def snapshot(self, docs: Docs, owners: Sequence[str], now: datetime) -> Snapshot:
        """Today's snapshot for each owner whose day is not done; the spikes to tell. Without
        billing yet (read late) nothing is done and nothing failed: the next tick tries."""
        billing = self._billing()
        if billing is None:
            return Snapshot()
        day = self.day_of(now)
        spikes: dict[str, float] = {}
        failed = False
        for uid in owners:
            if self._done.get(uid) == day or not owner_ok(uid):
                continue
            try:
                total = float((await billing.month(uid)).inr_total)
                got = spike(await self._keep(docs, uid, day, total), day, self._factor, self._min)
            except Exception as exc:  # noqa: BLE001 - one owner's figure never stops the rest
                log.warning("selfwatch spend not kept", extra={"error": type(exc).__name__})
                failed = True
                continue
            if got is None:
                self.settle(uid, day)
            else:
                spikes[uid] = got
        return Snapshot(spikes, failed)

    def settle(self, uid: str, day: str) -> None:
        """His day is done: kept, and its spike (if any) said."""
        self._done[uid] = day

    async def _keep(self, docs: Docs, uid: str, day: str, total: float) -> dict[str, float]:
        """The owner's snapshots with today's (the first of the day wins)."""

        async def fn(tx: DocTx) -> dict[str, float]:
            doc: dict[str, Any] = await tx.get(self._path) or {}
            raw = doc.get("owners")
            owners: dict[str, Any] = raw if isinstance(raw, dict) else {}
            mine = _series(owners.get(uid))
            if day in mine:
                return mine
            mine[day] = round(total, 2)
            mine = {k: mine[k] for k in sorted(mine)[-KEEP:]}
            kept = {k: v for k, v in owners.items() if k != uid}
            kept = dict(list(kept.items())[: MAX_OWNERS - 1])
            tx.set(self._path, {"owners": {**kept, uid: mine}})
            return mine

        return await docs.transaction(fn)


__all__ = [
    "HISTORY_DAYS",
    "HISTORY_MIN",
    "KEEP",
    "BillingLike",
    "Snapshot",
    "SpendWatch",
    "day_spends",
    "spike",
]
