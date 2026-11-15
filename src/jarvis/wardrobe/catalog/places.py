# src/jarvis/wardrobe/catalog/places.py
"""His places (docs/plans/r13-wardrobe.md D2, D6; INV-01, INV-02, INV-13, INV-14).

A place is his label (<= 40 characters: "Drawer 2", "Shoe rack", "Travel bag") and a kind
(`storage`, `intake`, `basket`, `return`, `travel`, `out`). `resolve_place` finds one by its id or
his words (the Things key: case, plurals and "the" do not matter); an unknown place is refused
with his places listed, never made up (D6: a watch is never in two lists). A baseline scan of a
place records a `seen` event for each piece he resolved there and the place's `baseline_at` in
ONE commit; the scans he could not resolve come back as a count, apart (never a guess); every
place still without a baseline is listed ("scope covered", INV-02, INV-14).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from jarvis.belongings.text import thing_key
from jarvis.storage.docs import DocTx, Op
from jarvis.wardrobe.catalog.edits import clean_label
from jarvis.wardrobe.catalog.events import event
from jarvis.wardrobe.catalog.store import CatalogStore
from jarvis.wardrobe.model import PLACE_LABEL_MAX, Event, Place, PlaceKind, WardrobeView, new_id
from jarvis.wardrobe.ports import Commit, Refused

MAX_PLACES = 50
NO_PLACES = "I don't know that place, and you have no places yet: add one in Helpers, Wardrobe."
KINDS: tuple[str, ...] = ("storage", "intake", "basket", "return", "travel", "out")


def resolve_place(view: WardrobeView, words: str) -> Place | None:
    if not isinstance(words, str) or not words.strip():
        return None
    if words in view.places:
        return view.places[words]
    key = thing_key(words)
    return next((p for p in view.places.values() if thing_key(p.label) == key), None)


def unknown_place(view: WardrobeView) -> str:
    if not view.places:
        return NO_PLACES
    names = ", ".join(p.label for p in view.places.values())
    return f"I don't know that place. Your places: {names}."


def without_baseline(view: WardrobeView) -> tuple[str, ...]:
    return tuple(p.id for p in view.places.values() if p.baseline_at is None)


@dataclass(frozen=True)
class Baseline:
    place: str
    seen: tuple[str, ...]
    unresolved: int
    without_baseline: tuple[str, ...]


class Places:
    def __init__(self, store: CatalogStore) -> None:
        self.store = store

    async def add(self, uid: str, label: str, kind: str = "storage") -> Place:
        words = clean_label(label, PLACE_LABEL_MAX)
        if not words or kind not in KINDS:
            raise Refused("A place needs a short name and one of the place kinds.")
        found: list[Place] = []

        async def fn(view: WardrobeView, tx: DocTx) -> tuple[WardrobeView, list[Op]]:
            same = resolve_place(view, words)
            if same is not None:  # idempotent: the same name is the same place
                found[:] = [same]
                return view, []
            if len(view.places) >= MAX_PLACES:
                raise Refused(f"You can keep at most {MAX_PLACES} places.")
            made = Place.model_validate({"id": new_id("wl"), "label": words, "kind": kind})
            found[:] = [made]
            return view.model_copy(update={"places": {**view.places, made.id: made}}), []

        await self.store.rewrite(uid, fn)
        return found[0]

    async def rename(self, uid: str, place: str, label: str) -> Place:
        words = clean_label(label, PLACE_LABEL_MAX)
        if not words:
            raise Refused("A place needs a short name.")
        out: list[Place] = []

        async def fn(view: WardrobeView, tx: DocTx) -> tuple[WardrobeView, list[Op]]:
            found = resolve_place(view, place)
            if found is None:
                raise Refused(unknown_place(view))
            other = resolve_place(view, words)
            if other is not None and other.id != found.id:
                raise Refused("You already have a place by that name.")
            new = found.model_copy(update={"label": words})
            out[:] = [new]
            return view.model_copy(update={"places": {**view.places, new.id: new}}), []

        await self.store.rewrite(uid, fn)
        return out[0]

    async def remove(self, uid: str, place: str) -> str:
        out: list[str] = []

        async def fn(view: WardrobeView, tx: DocTx) -> tuple[WardrobeView, list[Op]]:
            found = resolve_place(view, place)
            if found is None:
                raise Refused(unknown_place(view))
            if any(p.place == found.id for p in view.active()):
                raise Refused("Pieces are still kept there: move them first.")
            out[:] = [found.id]
            rest = {k: v for k, v in view.places.items() if k != found.id}
            return view.model_copy(update={"places": rest}), []

        await self.store.rewrite(uid, fn)
        return out[0]

    async def baseline(
        self, uid: str, place: str, *, seen: Sequence[str], unresolved: int = 0
    ) -> Baseline:
        now = self.store.now()
        target: list[str] = []

        async def fn(view: WardrobeView, tx: DocTx) -> Commit:
            found = resolve_place(view, place)
            if found is None:
                raise Refused(unknown_place(view))
            target[:] = [found.id]
            events: list[Event] = []
            for pid in dict.fromkeys(seen):
                if view.piece(pid) is None:
                    raise Refused("That piece isn't in your wardrobe.")
                events.append(event(pid, "seen", now, place=found.id, source="phone"))
            return Commit(events=tuple(events))

        def stamp(fresh: WardrobeView) -> WardrobeView:
            p = fresh.places[target[0]].model_copy(update={"baseline_at": now})
            return fresh.model_copy(update={"places": {**fresh.places, p.id: p}})

        got = await self.store.transact(uid, fn, index=stamp)
        return Baseline(
            target[0], tuple(dict.fromkeys(seen)), max(0, int(unresolved)),
            without_baseline(got.view),
        )  # fmt: skip


__all__ = [
    "KINDS",
    "MAX_PLACES",
    "Baseline",
    "PlaceKind",
    "Places",
    "resolve_place",
    "unknown_place",
    "without_baseline",
]
