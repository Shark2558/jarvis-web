# src/jarvis/wardrobe/catalog/jobs.py
"""A's daily job on the morning tick (docs/plans/r13-wardrobe.md D3, D4.4; STY-17, H1):
`wardrobe_sweep`. No new Scheduler job: it rides R14's morning tick (`api/tick_wiring.py`).

1. **A forgotten wear is closed** from `wardrobe_wear_close` (04:00) HIS local time: a piece
   still In use whose wear started before local midnight gets `wear_done` by the rewear rule,
   one wear, never two. The rule and the closing are Part C's (`close_forgotten`, joined by the
   wiring as `closer`; A keeps no copy). Before 04:00 nothing is closed (he may still be out).
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
from jarvis.wardrobe.catalog.store import CatalogStore
from jarvis.wardrobe.model import WardrobeView
from jarvis.wardrobe.ports import Commit, ReviewNeeded

log = get_logger(__name__)

NAME = "wardrobe_sweep"
# The rewear rule lives in ONE place: Part C's `styling/rules.json` (Workshop decision 1). The
# wiring binds `WardrobeSweep.closer` to C's `close_forgotten` with C's checked rules; without
# the styling part the step is skipped and the rest of the sweep goes on.
Closer = Callable[[str, datetime, ZoneInfo, str], Awaitable[int]]


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
        closer: Closer | None = None,
    ) -> None:
        self.store, self._zone, self._close = store, zone, _close_at(close)
        self.close_text, self.closer = close, closer

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
        return await self._close_wears(uid), await self._repair_holds(uid, view)

    async def _close_wears(self, uid: str) -> int:
        if self.closer is None:  # no styling part: no rule to close by
            return 0
        return await self.closer(uid, self.store.now(), await self._zone(uid), self.close_text)

    async def _repair_holds(self, uid: str, view: WardrobeView) -> int:
        held = [p for p in view.active() if p.state == "review" and p.hold]
        if not held:
            return 0
        needed = tuple(ReviewNeeded("hold", p.id, back_to=p.back_to, reason="sweep") for p in held)

        async def fn(v: WardrobeView, tx: DocTx) -> Commit:
            return Commit()

        await self.store.transact(uid, fn, needed=needed)
        return len(held)


__all__ = ["NAME", "Closer", "WardrobeSweep"]
