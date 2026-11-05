# tests/belongings_fakes.py -- a Things service over MemoryDocs with a real keyring and bin (R2 B).
from __future__ import annotations

from dataclasses import dataclass

from jarvis.belongings.service import BelongingsService
from jarvis.belongings.store import BelongingsStore
from jarvis.keyring import Keyring
from jarvis.storage.docs import MemoryDocs
from jarvis.undo.service import UndoBin
from jarvis.undo.store import DeletedStore

UID = "u_owner"
OTHER = "u_other"
ROOT = bytes(range(1, 33))


@dataclass
class Things:
    docs: MemoryDocs
    store: BelongingsStore
    undo: UndoBin
    svc: BelongingsService


def things(docs: MemoryDocs | None = None, *, bin_on: bool = True) -> Things:
    docs = docs or MemoryDocs()
    ring = Keyring(ROOT)
    store = BelongingsStore(docs, ring)
    undo = UndoBin(DeletedStore(docs))
    svc = BelongingsService(store, undo if bin_on else None)
    undo.register("thing", svc, svc)  # type: ignore[arg-type]
    return Things(docs, store, undo, svc)
