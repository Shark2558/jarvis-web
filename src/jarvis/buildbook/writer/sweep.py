# src/jarvis/buildbook/writer/sweep.py
"""R6.3 D5, D11, D12: the writer's FREE work, on every `book_write` run (no brain call, no YES):

- old trial pages and drafts go after 30 days;
- the sweep: a pages file whose release has left R6's index goes, except the newest one while R6's
  index still holds a release (the next free carry's source); once R6's index is empty (after
  Privacy -> Delete of the sealed books) every one goes; dead pending sets and orphans too;
- the free carry: when R6 has sealed a new current release with no pages file yet, its file is
  built from the newest one (carry.py), and `update_ready` with its rupees is stored and told once;
- the storage line: R6's sealed total plus the pages files past 80 % of the limit is told once a
  release (`http.StorageView` shows it every time).
Notices go through the notifier with R6's kinds and the writer's own words, claimed in
`WriterDoc.told` per (release, what) before they go and given back when they could not.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Awaitable, Callable, Collection
from typing import Literal

from jarvis.alerts import AlertKind
from jarvis.buildbook.model import MIB
from jarvis.buildbook.ports import BookError
from jarvis.buildbook.writer import carry, pages, texts
from jarvis.buildbook.writer.http import Estimate
from jarvis.buildbook.writer.model import UpdateReady, WriterDoc
from jarvis.buildbook.writer.ports import WriterContext
from jarvis.buildbook.writer.store import WriterStore
from jarvis.buildbook.writer.vault import PagesVault
from jarvis.logging import get_logger
from jarvis.notify.ports import Signal

log = get_logger(__name__)
What = Literal["pages", "update", "storage", "failed"]
WARN_SHARE = 0.8  # D11: the 80 % storage line
TOLD_KEPT = 8  # releases whose notice claims are kept
Estimator = Callable[[str, tuple[str, ...], str], Awaitable[Estimate]]


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


async def tell(
    ctx: WriterContext, store: WriterStore, uid: str, rid: str, what: What, text: str
) -> bool:
    """ONE notice per (release, what): claimed first, given back if it could not go."""

    def claim(doc: WriterDoc) -> tuple[WriterDoc | None, bool]:
        have = doc.told.get(rid, ())
        if what in have:
            return None, False
        told = {**doc.told, rid: (*have, what)}
        keep = dict(list(told.items())[-TOLD_KEPT:])
        return doc.model_copy(update={"told": keep}), True

    def unclaim(doc: WriterDoc) -> tuple[WriterDoc, None]:
        have = tuple(w for w in doc.told.get(rid, ()) if w != what)
        return doc.model_copy(update={"told": {**doc.told, rid: have}}), None

    if not await store.change(uid, claim):
        return False
    if ctx.notifier is None:
        return True
    kind: AlertKind = "book_seal_failed" if what == "failed" else "book_sealed"
    try:
        await ctx.notifier.notify(uid, Signal(source="system", kind=kind), text)
    except Exception as exc:  # noqa: BLE001 - the next run tries again
        log.error("book writer notice not sent", extra={"kind": kind, "error": type(exc).__name__})
        await store.change(uid, unclaim)
        return False
    return True


class FreeWork:
    def __init__(
        self, ctx: WriterContext, store: WriterStore, vault: PagesVault, estimator: Estimator
    ) -> None:
        self.ctx, self.store, self.vault, self.estimator = ctx, store, vault, estimator

    async def run(self, uid: str) -> dict[str, int]:
        out = {"old": await self.store.drop_old(uid)}
        kept = {r.id for r in await self.ctx.vault.releases(uid)}
        out["swept"] = await sweep(self.vault, uid, kept=kept)
        current = self.ctx.source.current()
        if current is not None and current.id in kept:
            out["carried"] = await self.carry(uid, current.id, kept)
            await self.storage(uid, current.id, current.label or current.id)
        return out

    async def _old(self, uid: str, kept: Collection[str], rid: str) -> tuple[str, bytes] | None:
        ix = await self.vault.index(uid)
        files = [f for f in ix.files if f.release != rid]
        if not files:
            return None
        newest = max(files, key=lambda f: dt.datetime.fromisoformat(f.sealed_at))
        return newest.release, await self.vault.read(uid, newest.release)

    async def carry(self, uid: str, rid: str, kept: Collection[str]) -> int:
        """The new release's pages file, free (H3), then `update_ready` and its notice (D12)."""
        if (await self.vault.index(uid)).find(rid) is not None:
            return 0
        found = await self._old(uid, kept, rid)
        if found is None:
            return 0
        old_rid, data = found
        old = pages.decode_file(data)
        facts = self.ctx.source.facts()
        new_tree = carry.tree_of(self.ctx.source.read("source"))
        try:
            old_tree = carry.tree_of(await self.ctx.vault.read(uid, old_rid, "source"))
        except (LookupError, BookError):
            old_tree = carry.Tree(files={}, cards={})  # can't tell: every page counts as changed
        known = {p.id for p in old.pages} | {t.id for t in old.templates}
        changed = carry.changed_ids(facts, known, old_tree, new_tree)
        file = carry.carry(rid, facts, old, changed)
        waiting = sum(1 for p in file.pages if p.changed)
        await self.vault.put(
            uid, rid, pages.encode_file(file), counts=(0, waiting, 0),
            limit_bytes=self.ctx.limit_mb * MIB, others_bytes=await self.ctx.vault.used_bytes(uid),
        )  # fmt: skip
        todo = carry.to_write(facts, file)
        if todo and pages.ai_written(old):
            await self.ready(uid, rid, todo)
        return 1

    async def ready(self, uid: str, rid: str, todo: tuple[str, ...]) -> None:
        est = await self.estimator(uid, todo, rid)
        ready = UpdateReady(release=rid, estimate_id=est.id, pages=todo, inr_mid=est.mid)
        await self.store.change(uid, lambda d: (d.model_copy(update={"update_ready": ready}), None))
        await tell(self.ctx, self.store, uid, rid, "update",
                   texts.NOTICE_UPDATE.format(inr=texts.inr(est.mid)))  # fmt: skip

    async def storage(self, uid: str, rid: str, label: str) -> None:
        used = await self.ctx.vault.used_bytes(uid) + await self.vault.used_bytes(uid)
        limit = self.ctx.limit_mb * MIB
        if limit and used > WARN_SHARE * limit:
            words = texts.NOTICE_STORAGE.format(
                used=round(used / MIB), limit=self.ctx.limit_mb, pct=round(100 * used / limit)
            )
            await tell(self.ctx, self.store, uid, rid, "storage", words)


__all__ = ["WARN_SHARE", "FreeWork", "sweep", "tell"]
