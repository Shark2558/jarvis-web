# src/jarvis/wardrobe/catalog/jobs.py
"""A's daily job on the morning tick (docs/plans/r13-wardrobe.md D3, D4.4; STY-17, H1):
`wardrobe_sweep`. No new Scheduler job: it rides R14's morning tick (`api/tick_wiring.py`).

1. **A forgotten wear is closed** from `wardrobe_wear_close` (04:00) HIS local time: a piece
   still In use whose wear started before local midnight gets `wear_done` by the rewear rule
   (trousers, jeans, outerwear, belts, shoes and the watch are worn again: Ready; shirts,
   T-shirts, vests, underwear and socks go to the laundry), one wear, never two. Before 04:00
   nothing is closed (he may still be out).
2. **A hold without its entry gets one** (a crash between versions): each piece held in review
   is handed to B's review writer again in a commit of its own; the writer adds an entry only
   where none is open.
Counts only in its result and the logs; one owner's trouble never stops the others.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from datetime import datetime, time
from zoneinfo import ZoneInfo

from jarvis.logging import get_logger
from jarvis.storage.docs import DocTx
from jarvis.wardrobe.catalog.events import event
from jarvis.wardrobe.catalog.fold import fold
from jarvis.wardrobe.catalog.store import CatalogStore
from jarvis.wardrobe.model import TYPES, Piece, WardrobeView
from jarvis.wardrobe.ports import Commit, ReviewNeeded
from jarvis.wardrobe.states import State

log = get_logger(__name__)

NAME = "wardrobe_sweep"
WORN_AGAIN: frozenset[str] = frozenset(
    {"trousers", "chinos", "jeans", *TYPES["outerwear"], *TYPES["footwear"], *TYPES["accessories"]}
)


def after_wear(p: Piece) -> State:
    """The rewear rule's default (owner question 6): worn again, or to the laundry."""
    return "ready" if p.type in WORN_AGAIN else "in_laundry"


def _close_at(text: str) -> time:
    hh, mm = (int(x) for x in text.split(":"))
    return time(hh, mm)


class WardrobeSweep:
    name = NAME
    budget_s = 20.0

    def __init__(
        self,
        store: CatalogStore,
        zone: Callable[[str], Awaitable[ZoneInfo]],
        *,
        close: str = "04:00",
    ) -> None:
        self.store, self._zone, self._close = store, zone, _close_at(close)

    async def run(self, owners: Sequence[str]) -> dict[str, int]:
        closed = holds = failed = 0
        for uid in owners:
            try:
                c, h = await self.sweep(uid)
            except Exception as exc:  # noqa: BLE001 - one owner never stops the others
                log.warning("wardrobe sweep failed", extra={"error": type(exc).__name__})
                failed += 1
                continue
            closed, holds = closed + c, holds + h
        return {"owners": len(owners), "closed": closed, "holds": holds, "failed": failed}

    async def sweep(self, uid: str) -> tuple[int, int]:
        view = await self.store.view(uid)
        return await self._close_wears(uid, view), await self._repair_holds(uid, view)

    async def _midnight(self, uid: str, now: datetime) -> datetime | None:
        local = now.astimezone(await self._zone(uid))
        if local.time() < self._close:
            return None
        return local.replace(hour=0, minute=0, second=0, microsecond=0)

    async def _close_wears(self, uid: str, view: WardrobeView) -> int:
        now = self.store.now()
        midnight = await self._midnight(uid, now)
        if midnight is None:
            return 0
        done = []
        for p in (x for x in view.active() if x.state == "in_use"):
            events = await self.store.events(uid, p.id)
            marks = fold(events).marks
            starts = [e for e in events if e.kind == "wear_started" and marks[e.id] == "applied"]
            if starts and max(e.at for e in starts) < midnight:
                done.append(event(p.id, "wear_done", now, to=after_wear(p), via="sweep"))
        if done:

            async def fn(v: WardrobeView, tx: DocTx) -> Commit:
                return Commit(events=tuple(done))

            await self.store.transact(uid, fn)
        return len(done)

    async def _repair_holds(self, uid: str, view: WardrobeView) -> int:
        held = [p for p in view.active() if p.state == "review" and p.hold]
        if not held:
            return 0
        needed = tuple(ReviewNeeded("hold", p.id, back_to=p.back_to, reason="sweep") for p in held)

        async def fn(v: WardrobeView, tx: DocTx) -> Commit:
            return Commit()

        await self.store.transact(uid, fn, needed=needed)
        return len(held)


__all__ = ["NAME", "WORN_AGAIN", "WardrobeSweep", "after_wear"]
