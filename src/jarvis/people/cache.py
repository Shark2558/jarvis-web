# src/jarvis/people/cache.py
"""The owner's last research (R4 D10, py-M7, D-D1.5): the dossier, and the last TARGET asked about.

- LRU with a 1 hour TTL, bounded to `MAX_OWNERS`; `get` refreshes recency.
- With a Docs store, the entry is also kept in the owner's own document
  `<prefix>people_last/<uid>` (carries `expires_at`; deleted on an expired read and by `clear`),
  so a restart or a second instance still finds it. Without one it is in-process only (single
  instance). There is no TTL policy (R14 D13): `expires_at` is a float, which a Firestore TTL
  policy can't read (it needs a timestamp), and TTL deletes are billed with no free usage, so
  the code deletes what has expired itself.
- The last target is kept IN PROCESS even when the request was refused, so a follow-up ("what
  about her home?") is checked together with what came before. A refused target is NEVER
  written to the store: the name of a refused private person is not persisted (I2 F3).
"""

from __future__ import annotations

import time
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import asdict, dataclass

from jarvis.logging import get_logger
from jarvis.people.models import Dossier, dossier_from_dict
from jarvis.storage.docs import Docs, DocTx

log = get_logger(__name__)

TTL_S = 3600.0
MAX_OWNERS = 50


@dataclass(frozen=True)
class Entry:
    at: float
    name: str
    context: str
    dossier: Dossier | None = None


class DossierCache:
    def __init__(
        self,
        docs: Docs | None = None,
        *,
        clock: Callable[[], float] = time.time,
        prefix: str = "jarvis_",
    ) -> None:
        self._docs, self._clock, self._prefix = docs, clock, prefix
        self._mem: OrderedDict[str, Entry] = OrderedDict()

    def _path(self, uid: str) -> str:
        return f"{self._prefix}people_last/{uid}"

    def _fresh(self, e: Entry) -> bool:
        return self._clock() - e.at < TTL_S

    async def get(self, uid: str) -> Entry | None:
        e = self._mem.get(uid)
        if e is None and self._docs is not None:
            e = await self._load(self._docs, uid)
        if e is None or not self._fresh(e):
            self._mem.pop(uid, None)
            if e is not None:
                await self.clear(uid)  # expired: the stored copy goes too
            return None
        self._mem[uid] = e
        self._mem.move_to_end(uid)
        return e

    async def _load(self, docs: Docs, uid: str) -> Entry | None:
        try:
            raw = await docs.get(self._path(uid))
            if raw is None:
                return None
            d = raw.get("dossier")
            return Entry(
                float(raw["at"]), str(raw["name"]), str(raw["context"]),
                dossier_from_dict(d) if d else None,
            )  # fmt: skip
        except Exception as exc:  # noqa: BLE001 — a cache miss, never an error for the owner
            log.warning("people cache unreadable", extra={"reason": type(exc).__name__})
            return None

    async def put(self, uid: str, name: str, context: str, dossier: Dossier | None) -> None:
        e = Entry(self._clock(), name, context, dossier)
        self._mem[uid] = e
        self._mem.move_to_end(uid)
        while len(self._mem) > MAX_OWNERS:
            self._mem.popitem(last=False)
        if self._docs is None or dossier is None:  # a refused target stays in memory only
            return
        doc = {"at": e.at, "expires_at": e.at + TTL_S, "name": name, "context": context,
               "dossier": asdict(dossier)}  # fmt: skip

        async def work(tx: DocTx) -> None:
            tx.set(self._path(uid), doc)

        try:
            await self._docs.transaction(work)
        except Exception as exc:  # noqa: BLE001 — still cached in memory
            log.warning("people cache not saved", extra={"reason": type(exc).__name__})

    async def clear(self, uid: str) -> None:
        self._mem.pop(uid, None)
        if self._docs is None:
            return

        async def work(tx: DocTx) -> None:
            tx.delete(self._path(uid))

        try:
            await self._docs.transaction(work)
        except Exception as exc:  # noqa: BLE001
            log.warning("people cache not cleared", extra={"reason": type(exc).__name__})


__all__ = ["MAX_OWNERS", "TTL_S", "DossierCache", "Entry"]
