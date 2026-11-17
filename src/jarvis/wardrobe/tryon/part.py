# src/jarvis/wardrobe/tryon/part.py
"""R13.1 Part A's one join (docs/plans/r13-1-try-on.md "Part split" A, D4-D7, D16).

`build(ctx) -> WardrobePart("tryon", privacy=..., services={"tryon_looks": TryonService},
ready=...)`: no tool, no job, no `data` (the wiring refuses `data` on this part, M4). Its Privacy
rows are `tryon_figure`, `tryon_all` and `tryon_device` (`ports.PRIVACY_OWNER`). With no storage,
no token key, or Try-on switched off, `ready` says so in words ("Off: ..."), no service is offered
(the routes say the same words), nothing is ever kept in clear, and the rows still answer for
what is on disk (I0's `kept` stand-ins: found and deleted by path with no key).

`TryonService` is what the routes and C use: the looks (`ports.TryonLooks.look`), his
measurements and their versions, his figure choices, saved comparisons, the fresh check before
"Use this look", and OPS-05's `erase_all`. Each reads fresh; nothing is cached between calls.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any, TypeVar

from jarvis.wardrobe.ports import WardrobeContext, WardrobePart
from jarvis.wardrobe.tryon import confirm, saved
from jarvis.wardrobe.tryon.http import ConfirmIn, Deleted, SavedIn, SavedList, SavedView, TryonLook
from jarvis.wardrobe.tryon.looks import Looks
from jarvis.wardrobe.tryon.store import Saved, TryonDoc, TryonStore

READY = "ready"
OFF_NO_STORE = "Off: no storage is set up, so Try-on keeps nothing."
OFF_NO_KEY = "Off: JARVIS has no token key to seal your measurements."
OFF_SWITCHED = "Off: Try-on is switched off on this server."
R = TypeVar("R")


class TryonService:
    """The `tryon_looks` service (A's; `ports.SERVICE_OWNER`)."""

    def __init__(self, ctx: WardrobeContext) -> None:
        self.ctx = ctx
        self.store = TryonStore(ctx.docs, ctx.keyring, prefix=ctx.s.firestore_prefix, now=ctx.now)
        self.looks = Looks(ctx, self.store)

    async def look(self, uid: str, plan: str) -> TryonLook:
        """`ports.TryonLooks`: a plan's look as the figure shows it, read fresh (for C)."""
        return await self.looks.for_plan(uid, plan)

    async def confirm(
        self, uid: str, body: ConfirmIn, call: Callable[[dict[str, Any]], Awaitable[R]]
    ) -> R:
        """ "Use this look": the fresh check, then ONE `outfit_plan` lock through `call`."""
        return await confirm.check_and_lock(self.looks, uid, body, call)

    # ---- saved comparisons (AVT-11) ---------------------------------------------------------
    async def save(self, uid: str, body: SavedIn) -> SavedView:
        r = await self.looks.read(uid)
        made: list[Saved] = []

        def fn(doc: TryonDoc) -> TryonDoc:
            new, one = saved.add(doc, r, body, self.ctx.now())
            made[:] = [one]  # a retried transaction keeps only its last run's
            return new

        await self.store.change(uid, fn)
        return saved.saved_view(r, made[0])

    async def saved_list(self, uid: str) -> SavedList:
        doc, r = await self.store.read(uid), await self.looks.read(uid)
        return SavedList(saved=tuple(saved.saved_view(r, x) for x in doc.saved))

    async def saved_one(self, uid: str, sid: str) -> SavedView:
        found = saved.find(await self.store.read(uid), sid)
        return saved.saved_view(await self.looks.read(uid), found)

    async def saved_drop(self, uid: str, sid: str) -> Deleted:
        gone: list[bool] = []

        def fn(doc: TryonDoc) -> TryonDoc:
            new, went = saved.drop(doc, sid)
            gone[:] = [went]
            return new

        await self.store.change(uid, fn)
        return saved.deleted(gone[0])


def off_words(ctx: WardrobeContext) -> str | None:
    if ctx.docs is None:
        return OFF_NO_STORE
    if ctx.keyring is None:
        return OFF_NO_KEY
    if not ctx.s.tryon_enabled:
        return OFF_SWITCHED
    return None


def build(ctx: WardrobeContext) -> WardrobePart:
    off = off_words(ctx)
    if off is not None:
        return WardrobePart("tryon", ready=off)
    return WardrobePart("tryon", services={"tryon_looks": TryonService(ctx)}, ready=READY)


__all__ = ["OFF_NO_KEY", "OFF_NO_STORE", "OFF_SWITCHED", "READY", "TryonService", "build"]
