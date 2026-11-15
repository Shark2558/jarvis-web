# src/jarvis/wardrobe/catalog/part.py
"""R13 Part A's one join (docs/plans/r13-wardrobe.md "Part split"): Catalog and the ledger
(INV-01-17, OPS-03, OPS-06).

`build(ctx)` makes the sealed store and everything over it and hands back, through the contract
(`jarvis.wardrobe.ports`): the eight `wardrobe_*` tools, the daily `wardrobe_sweep`, the catalog's
`WardrobeData` (D's Privacy rows), and ONLY the three services A owns in `SERVICE_OWNER`:
`store` (the one `WardrobeStore`: B and C build on it, the wiring binds B's writer and C's
refresh into it), `photos` (the `PhotoVault`) and `bin` (Recently deleted's restorer and purger
for `wardrobe_item`). A's own routes (`api/wardrobe.py`) reach the rest through `store.desk`, the
`Desk` below, so no service name outside the contract is offered.

Off, in plain words, never in clear: no document store, or no token key (`OFF_NO_KEY`). Nothing
is read from the app while `build` runs; the bin, the brains and billing are read late.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from jarvis.wardrobe.catalog.backup import Backup
from jarvis.wardrobe.catalog.counts import Tally
from jarvis.wardrobe.catalog.data import CatalogData
from jarvis.wardrobe.catalog.jobs import WardrobeSweep
from jarvis.wardrobe.catalog.labels import Labels
from jarvis.wardrobe.catalog.links import Links
from jarvis.wardrobe.catalog.merge import Merge
from jarvis.wardrobe.catalog.photos import PhotoVault
from jarvis.wardrobe.catalog.pilot import PilotCounts
from jarvis.wardrobe.catalog.places import Places
from jarvis.wardrobe.catalog.restore import Restore
from jarvis.wardrobe.catalog.search import Search
from jarvis.wardrobe.catalog.service import CatalogService
from jarvis.wardrobe.catalog.store import CatalogStore
from jarvis.wardrobe.catalog.tagging import Tagging
from jarvis.wardrobe.catalog.tools import read_tools
from jarvis.wardrobe.catalog.tools_life import life_tools
from jarvis.wardrobe.catalog.tools_write import write_tools
from jarvis.wardrobe.catalog.undo import CatalogBin
from jarvis.wardrobe.catalog.views import Views
from jarvis.wardrobe.ports import WardrobeContext, WardrobePart

READY = "Ready: the catalog and the ledger."
OFF_NO_KEY = "Off: the wardrobe needs this server's token key (it is never kept in clear)."
OFF_NO_DOCS = "Off: no document store on this server."


@dataclass(frozen=True)
class Desk:
    """Part A's own services, for its tools and routes (`store.desk`)."""

    ctx: WardrobeContext
    store: CatalogStore
    service: CatalogService
    places: Places
    links: Links
    labels: Labels
    search: Search
    views: Views
    counts: Tally
    vault: PhotoVault
    merge: Merge
    bin: CatalogBin
    pilot: PilotCounts
    data: CatalogData
    tagging: Tagging
    backup: Backup
    restore: Restore


def _store(ctx: WardrobeContext) -> CatalogStore:
    s = ctx.s
    assert ctx.docs is not None and ctx.keyring is not None
    return CatalogStore(
        ctx.docs, ctx.keyring, ctx.now, prefix=s.firestore_prefix,
        max_pieces=s.wardrobe_max_pieces, index_max_bytes=s.wardrobe_index_max_kb * 1024,
    )  # fmt: skip


def build_desk(ctx: WardrobeContext, *, eyes: Any = None) -> Desk:
    s, store = ctx.s, _store(ctx)
    vault = PhotoVault(
        store, side=s.wardrobe_photo_side, max_kb=s.wardrobe_photo_max_kb,
        per_piece=s.wardrobe_photos_per_piece,
    )  # fmt: skip
    views = Views(ctx.now, stale_days=s.wardrobe_stale_days, cap_inr=s.wardrobe_ai_tag_month_inr)
    merge = Merge(store)

    async def private_ops(uid: str, piece: Any, tx: Any) -> list[Any]:
        return await vault.drop_ops(uid, piece, tx.get)

    desk = Desk(
        ctx, store, CatalogService(store, private_ops=private_ops), Places(store), Links(store),
        Labels(store), Search(store), views, views.tally, vault, merge,
        CatalogBin(store, vault, merge, lambda: ctx.state("undo")), PilotCounts(store),
        CatalogData(store, vault),
        Tagging(store, vault, state=ctx.state, zone=ctx.zone, cap_inr=s.wardrobe_ai_tag_month_inr,
                rate=s.usd_inr_rate, eyes=eyes),
        Backup(store, vault, max_mb=s.wardrobe_backup_max_mb), Restore(store, vault),
    )  # fmt: skip
    store.desk = desk
    return desk


def build(ctx: WardrobeContext, *, eyes: Any = None) -> WardrobePart:
    """`eyes`: a stand-in for `BrainEyes` (tests); the app's is built late from its state."""
    if ctx.docs is None:
        return WardrobePart("catalog", ready=OFF_NO_DOCS)
    if ctx.keyring is None:
        return WardrobePart("catalog", ready=OFF_NO_KEY)
    desk = build_desk(ctx, eyes=eyes)
    tools = (*read_tools(desk), *write_tools(desk), *life_tools(desk))
    sweep = WardrobeSweep(desk.store, ctx.zone, close=ctx.s.wardrobe_wear_close)
    return WardrobePart(
        "catalog",
        tools=tools,
        daily_jobs=(sweep,),
        data=(desk.data,),
        services={"store": desk.store, "photos": desk.vault, "bin": desk.bin},
        ready=READY,
    )


__all__ = ["OFF_NO_DOCS", "OFF_NO_KEY", "READY", "Desk", "build", "build_desk"]
