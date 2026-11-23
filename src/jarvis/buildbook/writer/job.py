# src/jarvis/buildbook/writer/job.py
"""R6.3 D5, D11, D12: `book_write`, the writer's resumable job on the existing clocks (the 5-minute
clock, LAST, Home on or off; the morning tick after `book_sweep`), and the steps of a run.

`BookWriteJob.run` does the FREE work on every run (sweep.py: no brain call, no YES), then, ONLY
inside an approved run (his typed YES on its rupees, or "update by itself" granted by its own YES),
one clock step: a page call starts only when its brain's measured p90 + 5 s fits the time left
(none measured: none, so the trial runs on the console step). `Steps` is the step itself, shared
with `POST /v1/book/writer/step` (its own 150 s): the run's pages (`todo`), each page's calls
(run.py), what is kept (a sealed draft or trial page), and the end of a run: its pages sealed in
the release's pages file (D11: attach or replace) and his notice. Never at start-up.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any

from jarvis.buildbook.facts_model import FactPack
from jarvis.buildbook.model import MIB
from jarvis.buildbook.ports import BookError
from jarvis.buildbook.writer import carry, model, pages, sweep, texts
from jarvis.buildbook.writer.model import (
    DRAFTS,
    JOB_BUDGET_S,
    JOB_NAME,
    Draft,
    Page,
    PageMeta,
    PagesFile,
    Run,
    Skipped,
    TrialPage,
    WriterDoc,
)
from jarvis.buildbook.writer.ports import WriterContext
from jarvis.buildbook.writer.run import (
    ACTIVE,
    CLOCK_CALLS,
    Busy,
    Item,
    Out,
    Runner,
    run_key,
    trial_items,
)
from jarvis.buildbook.writer.run import trial_brains as brains_for_trial
from jarvis.buildbook.writer.store import WriterStore
from jarvis.buildbook.writer.vault import PagesVault
from jarvis.logging import get_logger

log = get_logger(__name__)
TIMEOUT_SPARE_S = 3.0


class Steps:
    def __init__(
        self, ctx: WriterContext, store: WriterStore, vault: PagesVault, runner: Runner
    ) -> None:
        self.ctx, self.store, self.vault, self.runner = ctx, store, vault, runner

    async def pages_file(self, uid: str, rid: str) -> PagesFile | None:
        try:
            return pages.decode_file(await self.vault.read(uid, rid))
        except LookupError:
            return None

    async def todo(self, uid: str, doc: WriterDoc, facts: FactPack) -> list[Item]:
        run = doc.run
        if run is None:
            return []
        if run.kind == "trial":
            have = set(await self.store.trials(uid))
            return trial_items(facts, brains_for_trial(self.ctx.brains.list()), have)
        brain = doc.pick.confirmed.brain
        if brain is None:
            return []
        done = await self.store.drafts(uid, run.release)
        if run.kind == "update":
            ready = doc.update_ready
            ids = ready.pages if ready is not None and ready.release == run.release else ()
        else:
            ids = carry.to_write(facts, await self.pages_file(uid, run.release))
        found = [facts.page(i) for i in ids if i not in done]
        return [Item(ip, brain) for ip in found if ip is not None]

    def same_release(self, run: Run) -> bool:
        """A run is bound to its release: a new current release stops it (M5)."""
        current = self.ctx.source.current()
        return current is not None and current.id == run.release

    async def step(self, uid: str, *, on_clock: bool) -> WriterDoc:
        doc = await self.store.doc(uid)
        run = doc.run
        if run is None or run.state not in ACTIVE:
            return doc
        if not self.same_release(run):
            await self.finish(uid, "stopped", "new_release")  # M5: a YES never carries
            return await self.store.doc(uid)
        holder = await self.runner.lease(uid, on_clock)
        try:
            await self.runner.ledger.close_later(uid)
            await self.runner.ledger.settle_old(uid)
            await self._go(uid, on_clock)
        finally:
            await self.store.unlease(uid, holder)
        return await self.store.doc(uid)

    async def _go(self, uid: str, on_clock: bool) -> None:
        doc = await self.store.doc(uid)
        facts = self.ctx.source.facts()
        todo = await self.todo(uid, doc, facts)
        if not todo:
            await self.finish(uid, "done", "done")
            return
        await self.mark(uid, state="running", why="")
        start, calls = self.runner.now_s(), 0
        budget = JOB_BUDGET_S if on_clock else model.STEP_BUDGET_S

        def left() -> float:
            return self.runner.left(start, budget, on_clock)

        for n, item in enumerate(todo):
            doc = await self.store.doc(uid)
            if doc.run is None or doc.run.state not in ACTIVE:
                return  # stopped meanwhile (his Stop): nothing more starts
            need = self.runner.need(doc.seconds.get(item.brain, ()), on_clock)
            if need is None or left() < need or (on_clock and calls >= CLOCK_CALLS):
                if on_clock and calls == 0:
                    await self.mark(uid, why=texts.WHY["slow"])
                return
            out = await self.runner.page(uid, doc.run, doc, item, facts, left, need)
            calls += out.calls
            if out.stop:
                state = "paused" if out.stop == "no_ai" else "stopped"
                await self.finish(uid, state, out.stop, left_pages=len(todo) - n)
                return
            if out.wait:
                await self.mark(uid, why=texts.WHY["unavailable"])
                return
            await self.keep(uid, doc, item, out, facts)
        await self.finish(uid, "done", "done")

    async def mark(self, uid: str, *, state: str | None = None, why: str | None = None) -> None:
        def fn(doc: WriterDoc) -> tuple[WriterDoc | None, None]:
            if doc.run is None:
                return None, None
            upd: dict[str, Any] = {} if why is None else {"why": why}
            if state is not None:
                upd["state"] = state
                if doc.run.started_at is None:
                    upd["started_at"] = self.ctx.clock().isoformat()
            return doc.model_copy(update={"run": doc.run.model_copy(update=upd)}), None

        await self.store.change(uid, fn)

    def meta(self, doc: WriterDoc, item: Item, out: Out, facts: FactPack) -> PageMeta | None:
        w = out.written
        if w is None or doc.run is None:
            return None
        spec = self.ctx.brains.get(item.brain)
        version = facts.release.version if facts.release is not None else None
        return PageMeta(
            brain=spec.id, brain_label=spec.label[:60], model=w.model[:80],
            provider=w.provider[:40], release=doc.run.release, version=version,
            written_at=self.ctx.clock().isoformat(), attempt=out.attempt,
            tokens_in=w.usage.input_tokens, tokens_out=w.usage.output_tokens,
            inr=round(out.inr, 2),
        )  # fmt: skip

    async def keep(self, uid: str, doc: WriterDoc, item: Item, out: Out, facts: FactPack) -> None:
        """What a page's calls gave, sealed: a draft (first or update) or a trial page."""
        run, meta = doc.run, self.meta(doc, item, out, facts)
        if run is None or meta is None:
            return
        codes, blob, fid = out.codes, "", ""
        if not codes:
            template = pages.written(item.page, out.sections, meta)
            try:
                filled = pages.fill_page(template, facts)
            except ValueError:
                codes = ("shape",)
            else:
                body = {
                    "page": filled.model_dump(mode="json"),
                    "template": template.model_dump(mode="json"),
                }
                fid, blob = self.store.seal(uid, run.release, json.dumps(body).encode("utf-8"))
        if item.nn is not None:
            trial = TrialPage(
                owner=uid, nn=item.nn, brain=item.brain, page=item.page.id, attempt=out.attempt,
                checks=out.first if not codes else codes, meta=meta, seconds=round(out.seconds, 2),
                inr=round(out.inr, 2), blob=f"{fid}:{blob}" if blob else "",
            )  # fmt: skip
            await self.store.put_trial(uid, trial)
        else:
            if not blob:
                fid, blob = self.store.seal(uid, run.release, b"{}")
            state = "failed" if codes else "ok"
            draft = Draft(
                owner=uid, page=item.page.id, attempt=out.attempt, state=state,
                checks=codes or out.first, meta=meta, blob=blob, fid=fid,
            )  # fmt: skip
            await self.store.put_draft(uid, run.release, draft)
        await self.progress(uid, failed=bool(codes))

    async def progress(self, uid: str, *, failed: bool) -> None:
        def fn(doc: WriterDoc) -> tuple[WriterDoc | None, None]:
            if doc.run is None:
                return None, None
            r = doc.run
            new = r.model_copy(update={"done": r.done + 1, "failed": r.failed + int(failed)})
            return doc.model_copy(update={"run": new}), None

        await self.store.change(uid, fn)

    async def seal(self, uid: str, rid: str) -> int:
        """The run's drafts into its release's pages file (attach or replace, D11); how many pages
        were written. The drafts go once it is sealed."""
        drafts = await self.store.drafts(uid, rid)
        new: dict[str, tuple[Page, Page]] = {}
        skipped: list[Skipped] = []
        for d in drafts.values():
            if d.state != "ok":
                skipped.append(Skipped(page=d.page, why=(d.checks[0] if d.checks else "failed")))
                continue
            body = json.loads(self.store.open(uid, rid, d.fid, d.blob))
            new[d.page] = (Page.model_validate(body["page"]), Page.model_validate(body["template"]))
        if not new and not skipped:
            return 0
        file = carry.merge(rid, await self.pages_file(uid, rid), new, tuple(skipped))
        waiting = sum(1 for p in file.pages if p.changed)
        await self.vault.put(
            uid, rid, pages.encode_file(file), counts=(len(new), waiting, len(file.skipped)),
            limit_bytes=self.ctx.limit_mb * MIB, others_bytes=await self.ctx.vault.used_bytes(uid),
        )  # fmt: skip
        await self.store.drop(DRAFTS, uid, f"{uid}_{rid}_")
        return len(new)

    async def finish(self, uid: str, state: str, why: str, *, left_pages: int = 0) -> None:
        """A run ends (done, stopped) or waits (paused): its pages sealed, his notice."""
        doc = await self.store.doc(uid)
        run = doc.run
        if run is None:
            return
        written = 0
        if run.kind != "trial" and state != "paused":
            try:
                written = await self.seal(uid, run.release)
            except BookError as exc:
                log.error("book writer pages not sealed", extra={"error": type(exc).__name__})
                state, why = "stopped", "unavailable"
        pct = doc.pick.confirmed.caps.limit_pct
        words = texts.WHY.get(why, texts.WHY["unavailable"]).format(left=left_pages, pct=pct)
        ended = None if state == "paused" else self.ctx.clock().isoformat()

        def fn(d: WriterDoc) -> tuple[WriterDoc | None, None]:
            if d.run is None:
                return None, None
            upd: dict[str, Any] = {
                "run": d.run.model_copy(update={"state": state, "why": words, "ended_at": ended})
            }
            if d.run.kind == "update" and state == "done":
                upd["update_ready"] = None
            return d.model_copy(update=upd), None

        await self.store.change(uid, fn)
        await self.tell_end(uid, run, written, why, words)

    async def tell_end(self, uid: str, run: Run, written: int, why: str, words: str) -> None:
        rid = run.release
        if written:
            label = getattr(self.ctx.source.current(), "label", None) or rid
            inr = await self.runner.ledger.run_spent(uid, run_key(run), run.kind)
            text = texts.NOTICE_PAGES.format(label=label, count=written, inr=texts.inr(inr))
            await sweep.tell(self.ctx, self.store, uid, rid, "pages", text)
        if why in ("over_hold", "unreadable", "unavailable"):
            await sweep.tell(
                self.ctx, self.store, uid, rid, "failed", texts.NOTICE_FAILED.format(why=words)
            )


class BookWriteJob:
    name = JOB_NAME
    budget_s = JOB_BUDGET_S

    def __init__(self, ctx: WriterContext, service: Any = None) -> None:
        self._ctx = ctx
        self.service = service

    async def run(self, owners: Sequence[str]) -> dict[str, int]:
        """The free work, then one clock step of an approved run (primary owner only, L11)."""
        if self.service is None or self._ctx.uid not in owners:
            return {}
        out: dict[str, int] = await self.service.tick(self._ctx.uid)
        return out


__all__ = ["BookWriteJob", "Busy", "Steps"]
