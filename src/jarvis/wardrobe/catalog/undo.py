# src/jarvis/wardrobe/catalog/undo.py
"""Recently deleted for wardrobe pieces (docs/plans/r13-wardrobe.md D16; kind `wardrobe_item`).

- `remove`: a copy goes into the bin FIRST (no copy, nothing is removed), under the fixed title
  "A wardrobe piece" (the bin is Firestore, in clear: never his label) with `{ref: <piece id>}`;
  then the piece is archived in place by an `archived` event (`via` "bin"): out of every count,
  its record, log, photos and fingerprints kept sealed.
- `restore` (the bin's restorer, in place: same id): the piece comes back "Missing or in review"
  (it was away up to 30 days); a merge's entry (`{ref, merge}`) only drops the link. A piece that
  is no longer archived was never removed ("still there"); one purged since is gone.
- `purge` (the bin's purger, "Remove now" and the 30-day sweep; safe to repeat): the record, its
  pairs, sets and label, every log page, its photos and fingerprints go, in one commit. A merge's
  entry purges nothing: the tombstone keeps the merged history (the link is then for good).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from jarvis.logging import get_trace_id
from jarvis.storage.docs import DocTx, Op
from jarvis.tools.context import current_tool_context
from jarvis.undo.models import DeletedItem, Kind
from jarvis.undo.service import Gone, Restored, StillThere, UndoBin
from jarvis.wardrobe.catalog.events import event
from jarvis.wardrobe.catalog.merge import Merge
from jarvis.wardrobe.catalog.photos import PhotoVault
from jarvis.wardrobe.catalog.store import NOT_IN, CatalogStore
from jarvis.wardrobe.model import WardrobeView
from jarvis.wardrobe.ports import Commit, Refused
from jarvis.wardrobe.redact import BIN_TITLE

KIND: Kind = "wardrobe_item"
BIN_OFF = "Recently deleted is off on this server, so nothing was changed."
BACK_WORDS = "It is back in your wardrobe, waiting for a quick check of its condition."


def _where() -> dict[str, str | None]:
    ctx, trace = current_tool_context(), get_trace_id()
    return {
        "session_id": ctx.session_id if ctx else None,
        "trace_id": None if trace == "-" else trace,
    }


class CatalogBin:
    """The bin's restorer and purger for `wardrobe_item` (registered by the wiring)."""

    def __init__(
        self, store: CatalogStore, vault: PhotoVault, merge: Merge, undo: Callable[[], Any]
    ) -> None:
        self.store, self.vault, self.merges, self._undo = store, vault, merge, undo

    def bin(self) -> UndoBin:
        found = self._undo()
        if not isinstance(found, UndoBin):
            raise Refused(BIN_OFF)
        return found

    async def keep(
        self, uid: str, snapshot: dict[str, str], *, owner_authored: bool
    ) -> DeletedItem:
        return await self.bin().keep(
            uid, KIND, BIN_TITLE, snapshot, owner_authored=owner_authored, **_where()
        )

    async def remove(self, uid: str, pid: str, *, owner_authored: bool) -> DeletedItem:
        view = await self.store.view(uid)
        p = view.piece(pid)
        if p is None or p.merged_into is not None:
            raise Refused(NOT_IN)
        kept = await self.keep(uid, {"ref": pid}, owner_authored=owner_authored)
        now = self.store.now()

        async def fn(view: WardrobeView, tx: DocTx) -> Commit:
            if view.piece(pid) is None:
                raise Refused(NOT_IN)
            return Commit(events=(event(pid, "archived", now, via="bin", note="removed"),))

        try:
            await self.store.transact(uid, fn)
        except Exception:
            await self.bin().discard(uid, kept.id)
            raise
        return kept

    async def restore(self, uid: str, item: DeletedItem, *, outside: bool = False) -> Restored:
        ref = str(item.snapshot.get("ref", ""))
        p = (await self.store.view(uid)).piece(ref)
        if p is None:
            raise Gone()
        if "merge" in item.snapshot:
            if p.merged_into is None:
                raise StillThere("That piece is already its own again.")
            await self.merges.unmerge(uid, ref)
            return Restored(ref, BACK_WORDS)
        if p.state != "archived":
            raise StillThere("That piece is already back in your wardrobe.")
        now = self.store.now()

        async def fn(view: WardrobeView, tx: DocTx) -> Commit:
            return Commit(events=(event(ref, "restored", now, via="bin"),))

        await self.store.transact(uid, fn)
        return Restored(ref, BACK_WORDS)

    async def purge(self, uid: str, item: DeletedItem) -> None:
        ref = str(item.snapshot.get("ref", ""))
        if "merge" in item.snapshot:
            return  # the tombstone keeps the merged history

        async def fn(view: WardrobeView, tx: DocTx) -> tuple[WardrobeView, list[Op]]:
            p = view.piece(ref)
            if p is None or p.state != "archived":
                return view, []  # gone already, or brought back since: nothing to purge
            ops = self.store.logs.drops(uid, p) + await self.vault.drop_ops(uid, p, tx.get)
            return _without(view, ref), ops

        await self.store.rewrite(uid, fn)


def _without(view: WardrobeView, pid: str) -> WardrobeView:
    pieces = {k: v for k, v in view.pieces.items() if k != pid}
    pairs = {k: v for k, v in view.pairs.items() if pid not in v.pieces}
    sets = {k: v for k, v in view.sets.items() if all(x.piece != pid for x in v.parts)}
    labels = {k: (v.model_copy(update={"piece": None}) if v.piece == pid else v)
              for k, v in view.labels.items()}  # fmt: skip
    return view.model_copy(
        update={"pieces": pieces, "pairs": pairs, "sets": sets, "labels": labels}
    )


__all__ = ["BACK_WORDS", "BIN_OFF", "KIND", "CatalogBin"]
