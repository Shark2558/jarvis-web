# src/jarvis/wardrobe/laundry/part.py
"""R13 Part B's one join (docs/plans/r13-wardrobe.md "Part split"): Laundry (LND-01-08,
LND-10-15, OPS-02).

`build(ctx)` returns WardrobePart("laundry") with:
- tools: `laundry_status`, `laundry_move`, `laundry_review`, `laundry_correct`,
  `laundry_send_out` (every call through the gateway; the `laundry` permission row);
- daily job: `laundry_daily` (the morning tick: overdue and short batches, the review queue's
  morning line, the sweep);
- data: B's `WardrobeData` ("laundry") for D's Privacy rows;
- services: `review_writer` (a `ReviewWriter`, bound into A's store by the wiring: every
  `ReviewNeeded` gets its entry in A's commit). Its `desk` is B's own service, read by B's routes
  (`api/laundry.py`) through the part: no other service name is offered.
A's store is read late (`ctx.store()`); without a token key the part still builds, its tools and
routes say plainly that laundry is off, and nothing is ever kept in clear.
"""

from __future__ import annotations

from jarvis.wardrobe.laundry.flows import Desk
from jarvis.wardrobe.laundry.jobs import LaundryDaily
from jarvis.wardrobe.laundry.store import LaundryData, LaundryStore
from jarvis.wardrobe.laundry.texts import READY, READY_NO_KEY
from jarvis.wardrobe.laundry.tools import laundry_tools
from jarvis.wardrobe.laundry.writer import LaundryWriter
from jarvis.wardrobe.ports import WardrobeContext, WardrobePart


def build(ctx: WardrobeContext) -> WardrobePart:
    store = LaundryStore(ctx.docs, ctx.keyring, prefix=ctx.s.firestore_prefix)
    writer = LaundryWriter(store, ctx.now)
    writer.desk = Desk(ctx, store, writer)
    return WardrobePart(
        "laundry",
        tools=tuple(laundry_tools(writer.desk)),
        daily_jobs=(LaundryDaily(ctx, store),),
        data=(LaundryData(store),),
        services={"review_writer": writer},
        ready=READY if store.available else READY_NO_KEY,
    )


__all__ = ["READY", "READY_NO_KEY", "build"]
