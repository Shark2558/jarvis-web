# src/jarvis/wardrobe/laundry/jobs.py
"""R13 Part B's `laundry_daily` on the existing morning tick (docs/plans/r13-wardrobe.md D19, D11;
no new Scheduler job).

For each owner, in his local day:
- `laundry_overdue` (important: rings by day, held at night) for every open batch past its `due`
  (once a batch a day), or that came back short (once a batch: with no due date there is no day
  to count from, so a batch without one is never told as overdue and never told daily);
- `wardrobe_review` (info, feed only) when checks opened before today still wait: once a day;
- the sweep: closed loads and batches after 90 days, answered checks after
  `wardrobe_review_keep_days`, B's claims after 30 days.
Each alert is claimed in `wardrobe_told` (`laundry_...`) BEFORE it is sent; a send that raises
releases its claim (tried again at the next tick). Fixed words only (`texts`): counts, never a
label, a shop or a private piece. One owner's failure stops no one (`failed`).
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from datetime import date, datetime, timedelta
from typing import Literal

from jarvis.logging import get_logger
from jarvis.notify.ports import Signal
from jarvis.storage.docs import Delete, DocTx
from jarvis.ticks import FAILED_COUNT
from jarvis.wardrobe.laundry import loads, providers, review, texts
from jarvis.wardrobe.laundry.store import LaundryDoc, LaundryStore, ReviewDoc
from jarvis.wardrobe.ports import WardrobeContext

log = get_logger(__name__)

CLAIMS_KEEP = timedelta(days=30)
Kind = Literal["laundry_overdue", "wardrobe_review"]


def _waiting(queue: ReviewDoc, start: datetime) -> int:
    """Pieces in checks opened before today (a check about no piece counts once)."""
    pieces: set[str] = set()
    loose = 0
    for e in review.open_entries(queue):
        if e.opened_at >= start:
            continue
        named = set(e.pieces or e.candidates)
        pieces |= named
        loose += 0 if named else 1
    return len(pieces) + loose


def _batch_alerts(laundry: LaundryDoc, today: date) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for b in providers.open_batches(laundry):
        out_n = len(providers.outstanding(b))
        if providers.overdue(b, today):
            days = providers.days_overdue(b, today)
            out.append(
                (f"laundry_overdue_{b.id}_{today.isoformat()}", texts.overdue_alert(out_n, days))
            )
        elif b.short and out_n:  # told once: with no due date there is no day to count from
            out.append((f"laundry_short_{b.id}", texts.short_alert(out_n)))
    return out


class LaundryDaily:
    name = "laundry_daily"
    budget_s = 20.0

    def __init__(self, ctx: WardrobeContext, store: LaundryStore) -> None:
        self._ctx, self._store = ctx, store

    async def run(self, owners: Sequence[str]) -> dict[str, int]:
        if not self._store.available:
            return {"off": 1}
        counts: Counter[str] = Counter()
        for uid in owners:
            try:
                for word in await self._owner(uid):
                    counts[word] += 1
            except Exception as exc:  # noqa: BLE001 - one owner never stops the others
                log.warning(
                    "laundry_daily failed for an owner", extra={"error": type(exc).__name__}
                )
                counts[FAILED_COUNT] += 1
        return dict(counts)

    async def _owner(self, uid: str) -> list[str]:
        zone = await self._ctx.zone(uid)
        now = self._ctx.now()
        local = now.astimezone(zone)
        today = local.date()
        start = local.replace(hour=0, minute=0, second=0, microsecond=0)
        assert self._store.docs is not None  # `available` checked it
        get = self._store.docs.get
        laundry = await self._store.read_laundry(get, uid)
        queue = await self._store.read_review(get, uid)
        words = [
            await self._tell(uid, "laundry_overdue", key, said, now)
            for key, said in _batch_alerts(laundry, today)
        ]
        waiting = _waiting(queue, start)
        if waiting:
            key = f"laundry_review_{today.isoformat()}"
            words.append(
                await self._tell(uid, "wardrobe_review", key, texts.review_alert(waiting), now)
            )
        await self._sweep(uid, now)
        return [w for w in words if w]

    async def _tell(self, uid: str, kind: Kind, key: str, said: str, now: datetime) -> str:
        notifier = self._ctx.notifier()
        if notifier is None:
            return "no_notifier"
        if not await self._store.claim(uid, key, now):
            return ""  # told already today
        try:
            await notifier.notify(uid, Signal(source="system", kind=kind), said)
        except Exception as exc:  # noqa: BLE001 - not sent: release, try at the next tick
            log.warning("a laundry alert was not sent", extra={"error": type(exc).__name__})
            await self._store.release(uid, key)
            return "not_sent"
        return "overdue" if kind == "laundry_overdue" else "review"

    async def _sweep(self, uid: str, now: datetime) -> None:
        store = self._store
        keep_days = self._ctx.s.wardrobe_review_keep_days
        assert store.docs is not None

        async def work(tx: DocTx) -> None:
            laundry = await store.read_laundry(tx.get, uid)
            queue = await store.read_review(tx.get, uid)
            kept = loads.prune(providers.prune(laundry, now), now)
            answered = review.prune(queue, now, keep_days=keep_days)
            if kept != laundry:
                op = store.laundry_op(uid, kept, now)
                tx.set(op.path, op.data)
            if answered != queue:
                op = store.review_op(uid, answered, now)
                tx.set(op.path, op.data)

        await store.docs.transaction(work)
        old = [Delete(p) for p, at in await store.claims(uid) if now - at > CLAIMS_KEEP]
        if old:
            await store.write(old)  # type: ignore[arg-type]


__all__ = ["CLAIMS_KEEP", "LaundryDaily"]
