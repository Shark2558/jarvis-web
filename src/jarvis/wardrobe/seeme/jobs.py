# src/jarvis/wardrobe/seeme/jobs.py
"""R13.1 Part C: `seeme_daily`, on the morning tick (docs/plans/r13-1-try-on.md D14, D18), bounded
by its time budget like R13's jobs, one owner never stopping the others.

For each owner: the pictures past their time (`keep_days`, 30, unless Keep), unreadable, or showing
a piece of his now private, merged or gone; the garment photos past their time and shown by no kept
picture; holds older than an hour settled at their hold (a call that may have been billed); spend
months older than 13 months. Everything goes by PATH, so it needs no token key (a deployment whose
key is missing still forgets on time). The panel's end-date notice is computed when the panel is
read (from the fixed end date and the clock), so nothing else runs on a clock.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence

from jarvis.logging import get_logger
from jarvis.storage.docs import Delete
from jarvis.wardrobe.model import WardrobeView
from jarvis.wardrobe.ports import WardrobeContext
from jarvis.wardrobe.seeme.cap import TryonCap
from jarvis.wardrobe.seeme.garments import GarmentStore
from jarvis.wardrobe.seeme.pictures import PictureStore
from jarvis.wardrobe.seeme.texts import SeeMeRefused
from jarvis.wardrobe.tryon.model import SPEND_KEEP_MONTHS

log = get_logger(__name__)
NAME = "seeme_daily"


def months_back(month: str, n: int) -> str:
    """ "2026-11" less 13 months is "2025-10"."""
    year, mon = (int(x) for x in month.split("-"))
    total = year * 12 + (mon - 1) - n
    return f"{total // 12:04d}-{total % 12 + 1:02d}"


class SeeMeDaily:
    name = NAME
    budget_s = 20.0

    def __init__(
        self, ctx: WardrobeContext, pictures: PictureStore, garments: GarmentStore, cap: TryonCap
    ) -> None:
        self.ctx, self.pictures, self.garments, self.cap = ctx, pictures, garments, cap

    async def run(self, owners: Sequence[str]) -> dict[str, int]:
        counts: Counter[str] = Counter()
        for uid in owners:
            try:
                counts.update(await self.owner(uid))
            except Exception as exc:  # noqa: BLE001 - one owner never stops the others
                log.warning("seeme_daily failed for an owner", extra={"error": type(exc).__name__})
                counts["failed"] += 1
        return {"owners": len(owners), **counts}

    async def _keep_days(self, uid: str) -> int:
        try:
            days = (await self.cap.prefs(uid)).keep_days
        except SeeMeRefused:
            days = None  # his settings unreadable: the deployment's (kept pictures stay kept)
        return days if days is not None else self.ctx.s.tryon_keep_days

    async def _view(self, uid: str) -> WardrobeView | None:
        store = self.ctx.store()
        if store is None:
            return None
        try:
            return await store.view(uid)
        except Exception as exc:  # noqa: BLE001 - can't tell what is private: time only today
            log.warning("seeme_daily: no wardrobe view", extra={"error": type(exc).__name__})
            return None

    async def owner(self, uid: str) -> Counter[str]:
        days, view = await self._keep_days(uid), await self._view(uid)
        pictures = await self.pictures.expired(uid, keep_days=days, view=view)
        going = {p.rsplit("/", 1)[1].removeprefix(f"{uid}_") for p in pictures}
        kept = {
            str(d.get("garment")) for pid, d in await self.pictures.rows(uid)
            if d.get("kept") is True and pid not in going
        }  # fmt: skip
        garments = await self.garments.expired(uid, keep_days=days, kept=kept)
        if pictures or garments:
            await self.ctx.docs.write([Delete(p) for p in (*pictures, *garments)])  # type: ignore[union-attr]
        held = await self.cap.settle_old(uid)
        months = await self._old_months(uid)
        return Counter(pictures=len(pictures), garments=len(garments), holds=held, months=months)

    async def _old_months(self, uid: str) -> int:
        cutoff = months_back(self.cap.month_of(self.ctx.now()), SPEND_KEEP_MONTHS)
        old = [m.month for m in await self.cap.months(uid) if m.month < cutoff]
        if old:
            await self.ctx.docs.write([Delete(self.cap.path(uid, m)) for m in old])  # type: ignore[union-attr]
        return len(old)


__all__ = ["NAME", "SeeMeDaily", "months_back"]
