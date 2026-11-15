# tests/belongings_fakes.py -- a Things service over MemoryDocs with a real keyring and bin (R2 B).
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

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


def things(
    docs: MemoryDocs | None = None,
    *,
    bin_on: bool = True,
    clock: Callable[[], datetime] | None = None,
) -> Things:
    """`clock` (R14 hotfix 2): the service's and the bin's clock, for a test whose words name a
    day (when a thing was noted or deleted); without it both read the real clock, as before."""
    docs = docs or MemoryDocs()
    ring = Keyring(ROOT)
    store = BelongingsStore(docs, ring)
    if clock is None:
        undo = UndoBin(DeletedStore(docs))
        svc = BelongingsService(store, undo if bin_on else None)
    else:
        undo = UndoBin(DeletedStore(docs), clock=clock)
        svc = BelongingsService(store, undo if bin_on else None, clock=clock)
    undo.register("thing", svc, svc)  # type: ignore[arg-type]
    return Things(docs, store, undo, svc)
