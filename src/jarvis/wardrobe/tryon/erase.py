# src/jarvis/wardrobe/tryon/erase.py
"""R13.1 D16 (OPS-05): "Delete all my try-on data", the Privacy delete of `tryon_all`.

`erase_all(ctx, store, uid)`, in this order:
1. C's half through C's `seeme` service (`ports.seeme_service`, read now: A is built before C):
   his See it on me pictures, the garment photos (D22), his photo and his YES;
2. then by path (`kept.erase_seeme`, no key needed) whatever of C's half is still on disk: all of
   it when C is off, failed or not built, nothing when C's own erase did its job;
3. `tryon/{uid}` LAST (his measurements, figure choices, saved comparisons), so a delete cut
   halfway leaves the figure and a second delete finishes.

The month's spend stays (his cap's record, 13 months). The wardrobe catalog is never touched:
no piece, photo or ledger line of R13's, so its `rev` is the same. Ids and counts only in logs.
"""

from __future__ import annotations

from jarvis.logging import get_logger
from jarvis.wardrobe.ports import WardrobeContext
from jarvis.wardrobe.tryon.kept import erase_seeme
from jarvis.wardrobe.tryon.ports import seeme_service
from jarvis.wardrobe.tryon.store import TryonStore

log = get_logger(__name__)


async def erase_all(ctx: WardrobeContext, store: TryonStore, uid: str) -> int:
    """How many documents went (C's half, then the figure)."""
    n = 0
    c = seeme_service(ctx)
    if c is not None:
        try:
            n += await c.erase(uid)
        except Exception as exc:  # noqa: BLE001 - its documents still go, by path, below
            log.error("OPS-05: See it on me's erase failed", extra={"error": type(exc).__name__})
    if ctx.docs is not None:
        n += await erase_seeme(ctx.docs, ctx.s.firestore_prefix, uid)
    n += await store.delete(uid)  # LAST (D16)
    log.info("OPS-05: try-on data deleted", extra={"documents": n})
    return n


__all__ = ["erase_all"]
