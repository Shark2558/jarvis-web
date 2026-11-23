# src/jarvis/buildbook/writer/sweep.py
"""R6.3 D11, D13: the writer's sweep (free work on every `book_write` run). A pages file whose
release has left R6's index goes, except the newest one while R6's index still holds a release (the
next free carry's source); once R6's index is empty (after Privacy -> Delete of the sealed books)
every one goes. Pending sets of a seal that died half-way and orphans go too.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Collection

from jarvis.buildbook.writer.vault import PagesVault


async def sweep(vault: PagesVault, uid: str, *, kept: Collection[str]) -> int:
    """How many pages files went; `kept` is R6's sealed release ids."""
    ix = await vault.index(uid)
    order = sorted(
        enumerate(ix.files), key=lambda p: (dt.datetime.fromisoformat(p[1].sealed_at), p[0])
    )
    newest = order[-1][1].release if order and kept else None
    gone = [f.release for _, f in order if f.release not in kept and f.release != newest]
    count = await vault.drop(uid, gone) if gone else 0
    await vault.sweep_stale(uid)
    return count


__all__ = ["sweep"]
