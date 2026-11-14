# src/jarvis/selfwatch/spend.py
"""A day's AI spend far above normal (docs/plans/r14-hardening.md D5, review A6).

Once a day (the first morning tick of the owner's local day) the month's total so far in rupees
(`Billing.month(uid).inr_total`, the meter's own figure) is kept as that day's snapshot in
`{prefix}selfwatch/spend` (`{owners: {uid: {"YYYY-MM-DD": inr}}}`, the newest `KEEP` days: today
and 15 days back, so the average covers 14 whole days). A day's spend is its snapshot minus the
day before's; on the 1st the month total starts again (`billing/meter.py` `month_of`), so it is
that day's snapshot alone. A day with no snapshot the day before is no "day".

A spike: today's figure is more than `factor` (3) times the average of the up to 14 days before
it and at least `min_inr` (₹50); never before `HISTORY_MIN` (7) days of history. The alert says
only that figure (D6: the one amount an alert may carry). Counts and rupees only.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from datetime import date, datetime, timedelta
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
    """(day, rupees spent that day), oldest first."""
    out: list[tuple[str, float]] = []
    days = sorted(snaps)
    for prev, cur in zip([None, *days], days, strict=False):
        d = date.fromisoformat(cur)
        if d.day == 1:
            out.append((cur, max(0.0, snaps[cur])))
        elif prev is not None and d - date.fromisoformat(prev) == timedelta(days=1):
            out.append((cur, max(0.0, snaps[cur] - snaps[prev])))
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


def _series(raw: object) -> dict[str, float]:
    if not isinstance(raw, dict):
        return {}
    out: dict[str, float] = {}
    for k, v in raw.items():
        if isinstance(k, str) and len(k) == 10 and isinstance(v, int | float) and v >= 0:
            out[k] = float(v)
    return out


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

    async def snapshot(self, docs: Docs, owners: Sequence[str], now: datetime) -> dict[str, float]:
        """Today's snapshot for each owner (once a day); uid -> rupees for those that spiked."""
        billing = self._billing()
        if billing is None:
            return {}
        day = now.astimezone(self._tz).date().isoformat()
        out: dict[str, float] = {}
        for uid in owners:
            if self._done.get(uid) == day or not owner_ok(uid):
                continue
            try:
                total = float((await billing.month(uid)).inr_total)
            except Exception as exc:  # noqa: BLE001 - one owner's figure never stops the rest
                log.warning("selfwatch spend unreadable", extra={"error": type(exc).__name__})
                continue
            snaps = await self._keep(docs, uid, day, total)
            self._done[uid] = day
            got = spike(snaps, day, self._factor, self._min) if snaps is not None else None
            if got is not None:
                out[uid] = got
        return out

    async def _keep(self, docs: Docs, uid: str, day: str, total: float) -> dict[str, float] | None:
        """The owner's snapshots with today's (the first of the day wins); None: already kept."""

        async def fn(tx: DocTx) -> dict[str, float] | None:
            doc: dict[str, Any] = await tx.get(self._path) or {}
            owners = doc.get("owners") if isinstance(doc.get("owners"), dict) else {}
            mine = _series(owners.get(uid))
            if day in mine:
                return None
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
    "SpendWatch",
    "day_spends",
    "spike",
]
