# src/jarvis/wardrobe/catalog/undo.py
"""Recently deleted for wardrobe pieces (docs/plans/r13-wardrobe.md D16; kind `wardrobe_item`).

- `remove`: a copy goes into the bin FIRST (no copy, nothing is removed), under the fixed title
  "A wardrobe piece" (the bin is Firestore, in clear: never his label) with `{ref: <piece id>,
  ev: <the archived event's id>}` (ids only); then the piece is archived in place by that event
  (`via` "bin"): out of every count, its record, log, photos and fingerprints kept sealed.
- An entry acts only while ITS event is still the piece's newest applied state-setting event: a
  piece brought back with the retire card and archived again on purpose since is his to keep
  (INV-17), so a stale entry restores nothing ("still there") and purges nothing.
- `restore` (the bin's restorer, in place: same id): the piece comes back "Missing or in review"
  (it was away up to 30 days); a merge's entry (`{ref, merge}`) only drops the link. One purged
  since is gone.
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
from jarvis.wardrobe.catalog.fold import fold
from jarvis.wardrobe.catalog.merge import Merge
from jarvis.wardrobe.catalog.photos import Get, PhotoVault
from jarvis.wardrobe.catalog.purges import PurgeCount
from jarvis.wardrobe.catalog.store import NOT_IN, CatalogStore
from jarvis.wardrobe.model import Event, Piece, WardrobeView
from jarvis.wardrobe.ports import Commit, Refused
from jarvis.wardrobe.redact import BIN_TITLE
from jarvis.wardrobe.states import STATE_SETTING

KIND: Kind = "wardrobe_item"
BIN_OFF = "Recently deleted is off on this server, so nothing was changed."
BACK_WORDS = "It is back in your wardrobe, waiting for a quick check of its condition."
STALE = "That piece is already back in your wardrobe, or was archived again since."


class _Stale(Refused):
    """The entry's removal is no longer what the piece is (never leaves `restore`)."""


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
        self.purges = PurgeCount(store)

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
        gone = event(pid, "archived", self.store.now(), via="bin", note="removed")
        # the entry names the event it makes: it acts only while that event is the newest (H2)
        kept = await self.keep(uid, {"ref": pid, "ev": gone.id}, owner_authored=owner_authored)

        async def fn(view: WardrobeView, tx: DocTx) -> Commit:
            if view.piece(pid) is None:
                raise Refused(NOT_IN)
            return Commit(events=(gone,))

        try:
            await self.store.transact(uid, fn)
        except Exception:
            await self.bin().discard(uid, kept.id)
            raise
        return kept

    async def _ours(self, uid: str, item: DeletedItem, p: Piece, get: Get) -> bool:
        """The entry's removal is still what the piece is: its `archived` event is the newest
        applied state-setting event (a later restore or a retire card makes the entry stale)."""
        made = item.snapshot.get("ev")
        if p.state != "archived" or not isinstance(made, str):
            return False
        log_ = await self.store.log_of(uid, p, get)
        marks = fold(log_).marks
        live = [e for e in log_ if marks[e.id] == "applied" and e.kind in STATE_SETTING]
        return bool(live) and max(live, key=Event.sort_key).id == made

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
        now = self.store.now()

        async def fn(view: WardrobeView, tx: DocTx) -> Commit:
            found = view.piece(ref)
            if found is None or not await self._ours(uid, item, found, tx.get):
                raise _Stale(STALE)
            return Commit(events=(event(ref, "restored", now, via="bin"),))

        try:
            await self.store.transact(uid, fn)
        except _Stale:
            raise StillThere(STALE) from None
        return Restored(ref, BACK_WORDS)

    async def purge(self, uid: str, item: DeletedItem) -> None:
        ref = str(item.snapshot.get("ref", ""))
        if "merge" in item.snapshot:
            return  # the tombstone keeps the merged history

        async def fn(view: WardrobeView, tx: DocTx) -> tuple[WardrobeView, list[Op]]:
            p = view.piece(ref)
            if p is None or not await self._ours(uid, item, p, tx.get):
                return view, []  # gone already, brought back or retired since: nothing to purge
            ops = self.store.logs.drops(uid, p) + await self.vault.drop_ops(uid, p, tx.get)
            ops += await self.purges.purge_ops(uid, tx.get)  # a restore token covers it (L2)
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
