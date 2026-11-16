# src/jarvis/wardrobe/catalog/logs.py
"""A piece's event log (docs/plans/r13-wardrobe.md D2): pages of 200 sealed events, append-only.

    {prefix}wardrobe_log/{uid}_{piece}_{page}   {v, kid, owner, n, blob, updated_at}
        blob = AES-GCM(the page's events, short keys), purpose `wardrobe`,
        AAD `wardrobe/log/{uid}/{piece}/{page}/v1` (a page moved to another piece does not open)

A page that is missing or can't be opened is an error the store turns into "unavailable": the
log is never rewritten from what could be read.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from datetime import datetime
from typing import Any

from jarvis.storage.docs import Delete, Op, Set
from jarvis.wardrobe.catalog.sealed import VERSION, Sealer, aad_log, check_owner, check_piece
from jarvis.wardrobe.model import Event, Piece

PAGE = 200  # events a log page


def pages(n_events: int) -> int:
    return (n_events + PAGE - 1) // PAGE


class LogPages:
    def __init__(self, sealer: Sealer, prefix: str) -> None:
        self._s, self._p = sealer, prefix

    def path(self, uid: str, pid: str, n: int) -> str:
        return f"{self._p}wardrobe_log/{check_owner(uid)}_{check_piece(pid)}_{n}"

    def _open(self, uid: str, pid: str, n: int, doc: Mapping[str, Any] | None) -> list[Event]:
        if doc is None or doc.get("v") != VERSION:
            raise ValueError("a log page is missing")
        raw = self._s.open("wardrobe", aad_log(uid, pid, n), doc.get("blob"))
        return [Event.model_validate(x) for x in raw]

    async def read(self, get: Callable[[str], Awaitable[Any]], uid: str, p: Piece) -> list[Event]:
        out: list[Event] = []
        for n in range(pages(p.events)):
            out += self._open(uid, p.id, n, await get(self.path(uid, p.id, n)))
        return out

    def writes(
        self, uid: str, pid: str, log: list[Event], first_new: int, now: datetime
    ) -> list[Op]:
        """The pages from the one holding the first new event to the last (append-only)."""
        stamp = now.isoformat()
        ops: list[Op] = []
        for n in range(first_new // PAGE, pages(len(log))):
            page = [e.to_json() for e in log[n * PAGE : (n + 1) * PAGE]]
            blob = self._s.seal("wardrobe", aad_log(uid, pid, n), page)
            body = {"v": VERSION, "kid": self._s.kid, "owner": uid, "n": len(page), "blob": blob}
            ops.append(Set(self.path(uid, pid, n), {**body, "updated_at": stamp}))
        return ops

    def drops(self, uid: str, p: Piece) -> list[Op]:
        """Every page of a piece (a purge from Recently deleted, D16)."""
        return [Delete(self.path(uid, p.id, n)) for n in range(pages(p.events))]


__all__ = ["PAGE", "LogPages", "pages"]
