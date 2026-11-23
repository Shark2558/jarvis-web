# src/jarvis/buildbook/writer/part.py
"""R6.3 seam 6: part B's ONE join, `build(ctx) -> WriterPart` (`writer/ports.py`): the writer's
service (the routes' `app.state.book_writer`), its `book_write` job and its Privacy row.

`WriterService` is what the routes call, for the PRIMARY owner only (`ctx.uid`, L11). Every grant
of spending is his typed YES on the rupee words shown first (H2): the trial and the first write
on their estimate (`estimate_id`: a changed estimate asks again), Update on its own, the pick's
grants on a `wt_` terms id (consent.py). Nothing here spends by itself: brain calls happen only in
a step of an approved run (job.py, run.py). Rupees only; ids, counts and rupees in the audit.
"""

from __future__ import annotations

import json
from typing import Any, Literal

import jarvis.llm.write as write
from jarvis.buildbook.gen.scrub import default_scrubber
from jarvis.buildbook.model import MIB
from jarvis.buildbook.ports import BookError
from jarvis.buildbook.writer import consent, estimate, pages, texts
from jarvis.buildbook.writer import http as h
from jarvis.buildbook.writer.caps import CapRefused, WriterCaps, money
from jarvis.buildbook.writer.job import BookWriteJob, Steps
from jarvis.buildbook.writer.model import (
    TRIAL,
    Confirmed,
    Consent,
    Page,
    PagesFile,
    Pick,
    Run,
    RunKind,
    WriterDoc,
)
from jarvis.buildbook.writer.ports import WriterContext, WriterPart
from jarvis.buildbook.writer.privacy import WriterSource
from jarvis.buildbook.writer.run import ACTIVE, Busy, Runner, cap_of, run_key
from jarvis.buildbook.writer.store import WriterStore
from jarvis.buildbook.writer.sweep import WARN_SHARE, FreeWork
from jarvis.buildbook.writer.vault import PagesVault
from jarvis.logging import get_logger

Off = Literal["no_key", "no_ai", "no_brain"]  # http.WriterView.why
Said = Literal["first", "redrafted", "refused"]  # http.TrialRow.state
log = get_logger(__name__)
WRITER_BRAINS = ("anthropic", "gemini")  # the registry ids the writer offers (D1, M2)
NOT_SET_UP, PRICE_UNKNOWN = "not set up on this server", "price unknown: not offered"


def refuse(code: str) -> texts.WriterRefused:
    return texts.WriterRefused(code)


class WriterService:
    ready = "ok"

    def __init__(self, ctx: WriterContext, store: WriterStore, ledger: WriterCaps,
                 vault: PagesVault, steps: Steps) -> None:  # fmt: skip
        self.ctx, self.store, self.ledger, self.vault, self.steps = ctx, store, ledger, vault, steps
        self.est = estimate.Estimates(ctx, store, steps.runner.first_turn, steps.pages_file)
        self.free = FreeWork(ctx, store, vault, self.est.for_update)

    # ---- helpers -----------------------------------------------------------------------------
    def _rid(self) -> str:
        return self.est.rid()

    async def _no_ai(self) -> bool:
        return bool(await self.ctx.brains.router_for(self.ctx.brains.default.id).blocked_now())

    async def _audit(self, tool: str, args: dict[str, Any]) -> None:
        if self.ctx.audit is None:
            return
        try:
            await self.ctx.audit.append(agent="book", tool=tool, risk="reversible",
                                        outcome="executed", args=args, detail="")  # fmt: skip
        except Exception as exc:  # noqa: BLE001 - it already happened
            log.error("AUDIT WRITE FAILED for the book writer", extra={"error": type(exc).__name__})

    async def _run_view(self, uid: str, doc: WriterDoc) -> h.RunView:
        run = doc.run
        if run is None:
            return h.RunView()
        spent = await self.ledger.run_spent(uid, run_key(run), run.kind)
        return h.RunView(kind=run.kind, state=run.state, done=run.done, total=run.total,
                         inr=round(spent, 2), cap_inr=cap_of(run, doc), why=run.why)  # fmt: skip

    async def estimate(self, uid: str, kind: RunKind) -> h.Estimate:
        return await self.est.of(uid, kind)

    # ---- the runs (D6, D7, D12) --------------------------------------------------------------
    async def _start(
        self, uid: str, kind: RunKind, est: h.Estimate, total: int, *, yes: bool = True
    ) -> h.RunView:
        rid, now = self._rid(), self.ctx.clock().isoformat()
        run = Run(kind=kind, release=rid, estimate_id=est.id, total=total, started_at=now)

        def fn(doc: WriterDoc) -> tuple[WriterDoc, None]:
            if doc.run is not None and doc.run.state in ACTIVE:
                raise refuse("running")  # two YES at once: one run (review I1 L-2)
            consents = dict(doc.consents)
            if kind != "update":
                consents[kind] = Consent(at=now, estimate_id=est.id, release=rid)
            return doc.model_copy(update={"run": run, "consents": consents}), None

        await self.store.change(uid, fn)
        args = {"release": rid, "estimate_id": est.id, "inr_mid": est.mid, "yes_confirmed": yes}
        await self._audit(f"book_write_{kind}", args)
        return await self._run_view(uid, await self.store.doc(uid))

    async def _ready_to_run(self, uid: str, typed: str) -> WriterDoc:
        doc = await self.store.doc(uid)
        if doc.run is not None and doc.run.state in ACTIVE:
            raise refuse("running")
        if not consent.is_yes(typed):
            raise refuse("not_yes")
        if await self._no_ai():
            raise refuse("no_ai")
        return doc

    async def start_trial(self, uid: str, body: h.TrialIn) -> h.RunView:
        await self._ready_to_run(uid, body.typed)
        est = await self.estimate(uid, "trial")
        if est.id != body.estimate_id:
            raise refuse("estimate_changed")
        await self.store.drop(TRIAL, uid)  # a new trial: the last one's pages go
        brains = estimate.trial_brains(self.ctx.brains.list())
        return await self._start(uid, "trial", est, est.pages * len(brains))

    async def first(self, uid: str, body: h.RunIn) -> h.RunView:
        doc = await self.store.doc(uid)
        if doc.pick.confirmed.brain is None or doc.pick.brain != doc.pick.confirmed.brain:
            raise refuse("pick_needed")
        await self._ready_to_run(uid, body.typed)
        est = await self.estimate(uid, "first")
        if est.pages == 0:
            raise refuse("already_written")
        if est.id != body.estimate_id:
            raise refuse("estimate_changed")
        return await self._start(uid, "first", est, est.pages)

    async def update(self, uid: str, body: h.RunIn) -> h.RunView:
        doc = await self.store.doc(uid)
        if doc.update_ready is None or doc.update_ready.release != self._rid():
            raise refuse("nothing_to_update")
        await self._ready_to_run(uid, body.typed)
        est = await self.estimate(uid, "update")
        if est.id != body.estimate_id:
            raise refuse("estimate_changed")
        carried = pages.ai_written(await self.steps.pages_file(uid, self._rid()))
        if est.mid > doc.pick.confirmed.caps.release or not carried:
            raise refuse("use_first")  # H3: never a tap past the release cap
        return await self._start(uid, "update", est, est.pages)

    async def stop(self, uid: str) -> h.RunView:
        doc = await self.store.doc(uid)
        if doc.run is not None and doc.run.state in ACTIVE:
            await self.steps.finish(uid, "stopped", "stopped")
            await self._audit("book_write_stop", {"release": doc.run.release})
        return await self._run_view(uid, await self.store.doc(uid))

    async def step(self, uid: str) -> h.RunView:
        try:
            doc = await self.steps.step(uid, on_clock=False)
        except Busy:
            raise refuse("busy") from None
        return await self._run_view(uid, doc)

    async def tick(self, uid: str) -> dict[str, int]:
        """`book_write`: the free work, the opt-in update, then one clock step (D5). The free
        work's failure is logged and never stops an approved run's step (review I1 L-3)."""
        try:
            out = await self.free.run(uid)
        except (BookError, CapRefused, texts.WriterRefused) as exc:
            log.error("book writer free work failed", extra={"error": type(exc).__name__})
            out = {"free_failed": 1}
        await self._auto_update(uid)
        doc = await self.store.doc(uid)
        if doc.run is not None and doc.run.state in ACTIVE:
            try:
                await self.steps.step(uid, on_clock=True)
            except Busy:
                out["busy"] = 1
        return out

    async def _auto_update(self, uid: str) -> None:
        """ "Update by itself", granted by its own YES (D7): only within the release cap."""
        doc = await self.store.doc(uid)
        auto = doc.pick.auto_update and doc.pick.confirmed.auto_update
        if not auto or doc.update_ready is None or (doc.run and doc.run.state in ACTIVE):
            return
        try:
            est = await self.estimate(uid, "update")
        except texts.WriterRefused:
            return
        carried = pages.ai_written(await self.steps.pages_file(uid, self._rid()))
        if (
            est.id == doc.update_ready.estimate_id
            and est.mid <= doc.pick.confirmed.caps.release
            and carried
        ):
            await self._start(uid, "update", est, est.pages, yes=False)  # granted: his auto YES

    # ---- the pick and its grants (D7, H2) ----------------------------------------------------
    async def pick(self, uid: str, body: h.PickIn) -> Pick:
        try:
            spec = self.ctx.brains.get(body.brain)
        except LookupError:
            raise refuse("unknown_brain") from None
        if not write.offered(spec):
            raise refuse("not_offered")
        doc, rate = await self.store.doc(uid), await self.est.rate(uid)
        held, now = doc.pick.confirmed, self.ctx.clock().isoformat()
        words = consent.grants(
            spec=spec, caps=body.caps, auto=body.auto_update, confirmed=held, rate=rate
        )
        if not words:  # nothing more granted: saved at once (lowering is instant)
            granted = Confirmed(brain=spec.id, caps=body.caps, auto_update=body.auto_update,
                                terms_id=held.terms_id, at=held.at)  # fmt: skip
            return await self._save_pick(uid, body, granted, now, yes=False)
        tid = consent.terms_id(spec.id, body.caps, body.auto_update,
                               price=estimate.price_of(spec), rate=rate)  # fmt: skip
        if body.typed is None or body.terms_id is None:
            raise texts.WriterRefused("yes_needed", {"terms_id": tid, "words": list(words)})
        if not consent.is_yes(body.typed):
            raise refuse("not_yes")
        if body.terms_id != tid:
            raise refuse("terms_changed")
        granted = Confirmed(brain=spec.id, caps=body.caps, auto_update=body.auto_update,
                            terms_id=tid, at=now)  # fmt: skip
        return await self._save_pick(uid, body, granted, now, yes=True)

    async def _save_pick(self, uid: str, body: h.PickIn, granted: Confirmed, now: str,
                         *, yes: bool) -> Pick:  # fmt: skip
        new = Pick(brain=body.brain, caps=body.caps, auto_update=body.auto_update, picked_at=now,
                   confirmed=granted)  # fmt: skip
        await self.store.change(uid, lambda d: (d.model_copy(update={"pick": new}), None))
        fields = ["brain", "caps", "auto_update"]
        args = {"fields": fields, "terms_id": granted.terms_id, "yes_confirmed": yes}
        await self._audit("book_write_pick", args)
        return new

    # ---- the view (`GET /v1/book/writer`) ----------------------------------------------------
    def _offers(self) -> tuple[h.BrainOffer, ...]:
        out = []
        for s in self.ctx.brains.list():
            ok = write.offered(s)
            out.append(
                h.BrainOffer(
                    id=s.id,
                    label=s.label[:60],
                    trains_on_content=s.trains_on_content,
                    model_name=write.model_of(s)[:80],
                    offered=ok,
                    note="" if ok else PRICE_UNKNOWN,
                )  # fmt: skip
            )
        have = {b.id for b in out}
        out += [h.BrainOffer(id=b, label=b, trains_on_content=False, offered=False, note=NOT_SET_UP)
                for b in WRITER_BRAINS if b not in have]  # fmt: skip
        return tuple(out)

    async def _storage(self, uid: str) -> h.StorageView:
        r6, mine = await self.ctx.vault.used_bytes(uid), await self.vault.used_bytes(uid)
        limit = self.ctx.limit_mb * MIB
        return h.StorageView(used_mib=round(r6 / MIB, 2), pages_mib=round(mine / MIB, 2),
                             limit_mib=float(self.ctx.limit_mb),
                             warn=bool(limit) and r6 + mine > WARN_SHARE * limit)  # fmt: skip

    async def _trial_view(self, uid: str, doc: WriterDoc) -> h.TrialView:
        have = await self.store.trials(uid)
        run = doc.run if doc.run is not None and doc.run.kind == "trial" else None
        spent = await self.ledger.run_spent(uid, run_key(run), "trial") if run else 0.0
        state = run.state if run else ("done" if have else "none")
        total = run.total if run else len(have)
        return h.TrialView(state=state, done=len(have), total=total, inr=round(spent, 2),
                           results=tuple(sorted(have)))  # fmt: skip

    async def view(self, uid: str) -> h.WriterView:
        doc = await self.store.doc(uid)
        offers = self._offers()
        why: Off | None = None if any(b.offered for b in offers) else "no_key"
        why = "no_ai" if why is None and await self._no_ai() else why
        try:
            m = await money(self.ctx.billing, uid)
            line = (
                None
                if m.limit_inr is None
                else round(m.limit_inr * doc.pick.caps.limit_pct / 100, 2)
            )
            month = h.MonthView(book_inr=round((await self.ledger.month(uid)).spent_inr, 2),
                                limit_inr=m.limit_inr, line_inr=line)  # fmt: skip
        except CapRefused:
            month = h.MonthView(book_inr=0.0)
        return h.WriterView(
            on=why is None, why=why, brains=offers, trial=await self._trial_view(uid, doc),
            pick=doc.pick, run=await self._run_view(uid, doc), update_ready=doc.update_ready,
            month=month, storage=await self._storage(uid),
        )  # fmt: skip

    # ---- the trial's pages (D6) --------------------------------------------------------------
    async def trial_rows(self, uid: str) -> h.TrialPages:
        rows = []
        for nn, t in sorted((await self.store.trials(uid)).items()):
            state: Said = "refused" if not t.blob else ("redrafted" if t.attempt == 2 else "first")
            rows.append(h.TrialRow(nn=nn, page=t.page, brain=t.brain, state=state, checks=t.checks,
                                   inr=t.inr, seconds=t.seconds))  # fmt: skip
        return h.TrialPages(rows=tuple(rows))

    async def trial_page(self, uid: str, nn: int) -> h.TrialPageView:
        t = (await self.store.trials(uid)).get(nn)
        if t is None:
            raise refuse("no_trial")
        if t.blob:
            fid, _, blob = t.blob.partition(":")
            rid = t.meta.release if t.meta is not None else self._rid()
            page = Page.model_validate(json.loads(self.store.open(uid, rid, fid, blob))["page"])
        else:
            ip = self.ctx.source.facts().page(t.page)
            if ip is None:
                raise refuse("no_trial")
            page = pages.generator_page(ip, self.ctx.source.facts())
        return h.TrialPageView(nn=nn, page=page, checks=t.checks)

    async def delete_trial(self, uid: str) -> h.Deleted:
        doc = await self.store.doc(uid)
        if doc.run is not None and doc.run.kind == "trial" and doc.run.state in ACTIVE:
            raise refuse("running")
        return h.Deleted(deleted=await self.store.drop(TRIAL, uid))

    # ---- the full book (D14) -----------------------------------------------------------------
    async def _kept(self, uid: str, rid: str | None) -> tuple[str, PagesFile | None]:
        rid = rid or self._rid()
        if rid not in {r.id for r in await self.ctx.vault.releases(uid)}:
            raise refuse("no_page")  # a pages file whose release R6 doesn't keep is never served
        return rid, await self.steps.pages_file(uid, rid)

    async def pages_view(self, uid: str, rid: str | None) -> h.PagesView:
        rid, f = await self._kept(uid, rid)
        return pages.view(rid, self.ctx.source.facts(), f)

    async def page(self, uid: str, page_id: str, rid: str | None) -> Page:
        rid, f = await self._kept(uid, rid)
        found = pages.page_for(page_id, self.ctx.source.facts(), f)
        if found is None:
            raise refuse("no_page")
        return found


def build(ctx: WriterContext) -> WriterPart:
    store = WriterStore(ctx.docs, ctx.keyring, prefix=ctx.prefix, clock=ctx.clock)
    ledger = WriterCaps(ctx.docs, ctx.prefix, tz=ctx.timezone, clock=ctx.clock)
    vault = PagesVault(ctx.docs, ctx.keyring, prefix=ctx.prefix, clock=ctx.clock)
    runner = Runner(ctx, store, ledger, default_scrubber())
    service = WriterService(ctx, store, ledger, vault, Steps(ctx, store, vault, runner))
    privacy = WriterSource(ctx, store, vault, service)
    return WriterPart(service=service, job=BookWriteJob(ctx, service), privacy=(privacy,))


__all__ = ["NOT_SET_UP", "PRICE_UNKNOWN", "WRITER_BRAINS", "WriterService", "build"]
