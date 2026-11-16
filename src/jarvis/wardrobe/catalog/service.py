# src/jarvis/wardrobe/catalog/service.py
"""The catalog's changes (docs/plans/r13-wardrobe.md D2, D3, D7, D10; INV-01 ... INV-15).

- `add`: one id a physical piece. A box the phone keeps sending (20 frames of one shirt, a retry)
  carries its `client_id`: the id is a keyed hash of it, so the same box is the same piece and its
  `registered` event is applied once (INV-08). Every new piece is a record AND a `registered`
  event in one commit.
- `intake`: a scan he resolved. With the candidate he tapped, a `seen` event on that id (the
  owned count stays, INV-05); without one, a new piece. Nothing is decided without his tap.
- `edit`: `edits.apply_edit` in one commit; marking a piece private deletes its photos and
  fingerprints in the same change (D9); a question ("Make it private?") changes nothing.
- `move`: a `seen` event at one of HIS places (by id or his words); an unknown place is refused
  with his places listed, so a watch is never in two lists (D6, INV-13).
Every change goes through the store's `transact` (the fold, the guards, one commit).
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

from jarvis.storage.docs import DocTx, Op
from jarvis.wardrobe.catalog.edits import ASK_PRIVATE, Edit, NewPiece, apply_edit, new_record
from jarvis.wardrobe.catalog.events import event
from jarvis.wardrobe.catalog.places import resolve_place, unknown_place
from jarvis.wardrobe.catalog.store import NOT_IN, CatalogStore
from jarvis.wardrobe.model import Piece, WardrobeView, new_id
from jarvis.wardrobe.ports import Commit, Committed, Refused

MAX_ADD = 20  # pieces in one add (a result lists at most 20)


@dataclass(frozen=True)
class Added:
    ids: tuple[str, ...]
    new: tuple[bool, ...]


@dataclass(frozen=True)
class Edited:
    status: str  # "done" | "ask"
    piece: Piece | None = None
    question: str = ""


@dataclass(frozen=True)
class Moved:
    piece: str
    place: str
    mark: str


# A hook the photo vault offers (D9): the deletes that go with marking a piece private.
PrivateOps = Callable[[str, Piece, DocTx], Any]


class CatalogService:
    def __init__(self, store: CatalogStore, *, private_ops: PrivateOps | None = None) -> None:
        self.store = store
        self._private_ops = private_ops

    def piece_id(self, uid: str, client_id: str | None) -> str:
        if client_id is None:
            return new_id("wi")
        return "wi_" + self.store.sealer.mac(f"piece/{uid}/{client_id}")[:12]

    async def add(
        self, uid: str, specs: Sequence[NewPiece], *, source: str = "tap", via: str = "panel"
    ) -> Added:
        if not 1 <= len(specs) <= MAX_ADD:
            raise Refused(f"Add 1 to {MAX_ADD} pieces at a time.")
        ids = [self.piece_id(uid, s.client_id) for s in specs]
        if len(set(ids)) != len(ids):
            raise Refused("One box was sent twice in the same add.")
        now = self.store.now()
        known: list[bool] = []

        async def fn(view: WardrobeView, tx: DocTx) -> Commit:
            known[:] = [pid in view.pieces for pid in ids]
            custom = view.settings.custom_types
            recs, events = [], []
            for pid, spec, there in zip(ids, specs, known, strict=True):
                if spec.place is not None and spec.place not in view.places:
                    raise unknown_place(view)
                if not there:
                    recs.append(new_record(spec, pid, custom, now))
                fields = {"source": source, "via": via, "client_id": spec.client_id}
                fields |= {"place": spec.place, "to": spec.state}
                events.append(event(pid, "registered", now, **fields))
            return Commit(events=tuple(events), records=tuple(recs))

        await self.store.transact(uid, fn)
        return Added(tuple(ids), tuple(not k for k in known))

    async def intake(
        self, uid: str, spec: NewPiece, *, candidate: str | None, source: str = "phone"
    ) -> Added:
        """A scan he resolved: his tapped candidate is a sighting; none is a new piece."""
        if candidate is None:
            return await self.add(uid, [spec], source=source)
        now = self.store.now()

        async def fn(view: WardrobeView, tx: DocTx) -> Commit:
            if view.piece(candidate) is None:
                raise Refused(NOT_IN)
            how = {"how": "match"}
            e = event(candidate, "seen", now, source=source, place=spec.place, evidence=how)
            return Commit(events=(e,))

        await self.store.transact(uid, fn)
        return Added((candidate,), (False,))

    async def edit(self, uid: str, pid: str, change: Edit) -> Edited:
        out: list[Piece | str] = []

        async def fn(view: WardrobeView, tx: DocTx) -> Commit:
            out.clear()
            p = view.piece(pid)
            if p is None or p.merged_into is not None:
                raise Refused(NOT_IN)
            got = apply_edit(p, change, view.settings.custom_types)
            out.append(got)
            if isinstance(got, str):
                return Commit()
            extra: tuple[Op, ...] = ()
            if got.private and not p.private and self._private_ops is not None:
                extra = tuple(await self._private_ops(uid, p, tx))
                got = got.model_copy(update={"photos": (), "fp_model": None})
                out[-1] = got
            return Commit(records=(got,), extra=extra)

        await self.store.transact(uid, fn)
        found = out[-1]
        if isinstance(found, str):
            return Edited("ask", question=found)
        return Edited("done", piece=(await self.store.view(uid)).piece(pid))

    async def move(
        self, uid: str, pid: str, place: str, *, source: str = "tap", via: str = "panel"
    ) -> Moved:
        now = self.store.now()
        where: list[str] = []

        async def fn(view: WardrobeView, tx: DocTx) -> Commit:
            p = view.piece(pid)
            if p is None or p.merged_into is not None:
                raise Refused(NOT_IN)
            found = resolve_place(view, place)
            if found is None:
                raise unknown_place(view)
            where[:] = [found.id]
            return Commit(events=(event(pid, "seen", now, place=found.id, source=source, via=via),))

        got: Committed = await self.store.transact(uid, fn)
        mark = next(iter(got.marks.values()), "applied")
        return Moved(pid, where[0], mark)


__all__ = [
    "ASK_PRIVATE",
    "MAX_ADD",
    "Added",
    "CatalogService",
    "Edit",
    "Edited",
    "Moved",
    "NewPiece",
    "event",
]
