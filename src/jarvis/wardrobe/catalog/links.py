# src/jarvis/wardrobe/catalog/links.py
"""Pairs and sets (docs/plans/r13-wardrobe.md D2, D3; INV-11, INV-12, LND-13).

A pair is two pieces of one type (a left and a right shoe, two socks): each side stays its own
piece with its own id and state, and the pair is wearable only while both are eligible
(`states.wearable_pair`). A set is 2-6 pieces (a kurta and its bottoms) with "can be worn alone"
per part (`states.wearable_set`). A piece is in at most one pair; a replacement half joins only
when he re-pairs it himself (LND-13). Every change is one commit of the sealed index.
"""

from __future__ import annotations

from collections.abc import Sequence

from jarvis.storage.docs import DocTx, Op
from jarvis.wardrobe.catalog.edits import clean_label
from jarvis.wardrobe.catalog.store import NOT_IN, CatalogStore
from jarvis.wardrobe.model import (
    PAIRED_TYPES,
    PLACE_LABEL_MAX,
    SET_PARTS,
    Pair,
    PieceSet,
    SetPart,
    WardrobeView,
    new_id,
)
from jarvis.wardrobe.ports import Refused

ALREADY_PAIRED = "That piece is already in a pair: unpair it first."
NOT_A_PAIR = "A pair is two pieces of the same type, such as two socks or two shoes."


def pair_of(view: WardrobeView, pid: str) -> Pair | None:
    return next((p for p in view.pairs.values() if pid in p.pieces), None)


def pair_refusal(view: WardrobeView, a: str, b: str, *, freeing: str | None = None) -> str | None:
    """Why `a` and `b` can't be paired now (None: they can). `freeing`: a piece whose pair is
    undone first, in the same change (an edit's `unpair` + `pair_with`)."""
    for pid in (a, b):
        p = view.piece(pid)
        if p is None or p.merged_into is not None:
            return NOT_IN
    pa, pb = view.pieces[a], view.pieces[b]
    if a == b or pa.type != pb.type or pa.type not in PAIRED_TYPES:
        return NOT_A_PAIR
    busy = {i for x in view.pairs.values() if freeing not in x.pieces for i in x.pieces}
    return ALREADY_PAIRED if {a, b} & busy else None


def set_refusal(view: WardrobeView, ids: Sequence[str]) -> str | None:
    """Why these pieces can't be a set (None: they can)."""
    low, high = SET_PARTS
    if not low <= len(ids) <= high or len(set(ids)) != len(ids):
        return f"A set is {low} to {high} different pieces."
    found = [view.piece(pid) for pid in ids]
    return NOT_IN if any(p is None or p.merged_into is not None for p in found) else None


class Links:
    def __init__(self, store: CatalogStore) -> None:
        self.store = store

    async def pair(self, uid: str, a: str, b: str) -> Pair:
        out: list[Pair] = []

        async def fn(view: WardrobeView, tx: DocTx) -> tuple[WardrobeView, list[Op]]:
            if (why := pair_refusal(view, a, b)) is not None:
                raise Refused(why)
            made = Pair.model_validate(
                {"id": new_id("wp"), "pieces": (a, b), "paired_on": self.store.now().date()}
            )
            out[:] = [made]
            return view.model_copy(update={"pairs": {**view.pairs, made.id: made}}), []

        await self.store.rewrite(uid, fn)
        return out[0]

    async def unpair(self, uid: str, piece_or_pair: str) -> str:
        out: list[str] = []

        async def fn(view: WardrobeView, tx: DocTx) -> tuple[WardrobeView, list[Op]]:
            found = view.pairs.get(piece_or_pair) or pair_of(view, piece_or_pair)
            if found is None:
                raise Refused("That piece isn't in a pair.")
            out[:] = [found.id]
            rest = {k: v for k, v in view.pairs.items() if k != found.id}
            return view.model_copy(update={"pairs": rest}), []

        await self.store.rewrite(uid, fn)
        return out[0]

    async def make_set(
        self, uid: str, parts: Sequence[tuple[str, bool]], *, label: str = ""
    ) -> PieceSet:
        ids = [pid for pid, _ in parts]
        low, high = SET_PARTS
        if not low <= len(ids) <= high or len(set(ids)) != len(ids):
            raise Refused(f"A set is {low} to {high} different pieces.")
        words = clean_label(label, PLACE_LABEL_MAX)
        out: list[PieceSet] = []

        async def fn(view: WardrobeView, tx: DocTx) -> tuple[WardrobeView, list[Op]]:
            if (why := set_refusal(view, ids)) is not None:
                raise Refused(why)
            made = PieceSet.model_validate(
                {"id": new_id("ws"), "label": words, "parts": [
                    SetPart.model_validate({"piece": pid, "alone": bool(ok)}) for pid, ok in parts
                ]}
            )  # fmt: skip
            out[:] = [made]
            return view.model_copy(update={"sets": {**view.sets, made.id: made}}), []

        await self.store.rewrite(uid, fn)
        return out[0]

    async def unset(self, uid: str, set_id: str) -> str:
        async def fn(view: WardrobeView, tx: DocTx) -> tuple[WardrobeView, list[Op]]:
            if set_id not in view.sets:
                raise Refused("That set isn't in your wardrobe.")
            rest = {k: v for k, v in view.sets.items() if k != set_id}
            return view.model_copy(update={"sets": rest}), []

        await self.store.rewrite(uid, fn)
        return set_id


__all__ = ["ALREADY_PAIRED", "NOT_A_PAIR", "Links", "pair_of", "pair_refusal", "set_refusal"]
