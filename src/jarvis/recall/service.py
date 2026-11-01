# src/jarvis/recall/service.py
"""MemoryService (Layer 3): recall for a turn, background learning after it, the owner's API
operations, and the backends of the memory tools.

recall      gate (private brain) → header read (1 Firestore read when warm) → "use" on? →
            select ≤ 12 relevant facts → the notes block + "what I used". Never raises: a
            memory outage means a reply without notes, never a failed reply.
after_turn  a cheap in-memory check on the state recall already read (no extra read); when a
            batch is due, learning runs as a background task (never during the reply). Use
            counters are buffered and written at most every 15 minutes, in the background.
API         every write runs the sensitive filter and the limits (`ops`), in one transaction.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Coroutine, Iterable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from jarvis.billing import Billing
from jarvis.billing.fx import DEFAULT_RATE
from jarvis.billing.service import rupees
from jarvis.config import LLMBackend
from jarvis.core.models import Session
from jarvis.llm.base import Usage
from jarvis.llm.brains import BrainRegistry, BrainSpec
from jarvis.llm.pricing import cost_usd, is_priced
from jarvis.llm.router import ModelTier
from jarvis.logging import get_logger
from jarvis.recall import gate
from jarvis.recall.errors import ConsentRequired
from jarvis.recall.extract import Extractor
from jarvis.recall.learning import (
    Learner,
    LearnResult,
    Snapshot,
    is_due,
    learning_on,
    pending,
    snapshot,
)
from jarvis.recall.models import (
    MAX_ACTIVE,
    Counts,
    Fact,
    FactPatch,
    FactSource,
    ImportResult,
    MemoryRef,
    MemorySettings,
    MemoryState,
    MemoryView,
    Origin,
    Profile,
    SettingsPatch,
    UseStat,
)
from jarvis.recall.ops import (
    add_fact,
    delete_facts,
    edit_fact,
    export_data,
    find_duplicate,
    import_data,
    new_fact,
    purge,
    set_profile,
    wipe,
)
from jarvis.recall.retrieval import render_block, scores, select_facts, used_facts
from jarvis.recall.store import MemoryStore
from jarvis.storage.docs import Docs
from jarvis.tools.audit import AuditTrail

log = get_logger(__name__)

FLUSH_EVERY = timedelta(minutes=15)
SEARCH_LIMIT = 8
TYPICAL_RUN = Usage(input_tokens=1_500, output_tokens=150)
TYPICAL_RUNS_PER_DAY = 8
WORST_RUN = Usage(input_tokens=2_500, output_tokens=300)
DATA_SENT = "To learn, JARVIS sends {ai} your messages in the conversation and related notes."
MSG_CONSENT = (
    "Learning from your messages has a small cost ({cost}) and sends {ai} your messages in the "
    "conversation; confirm to switch it on."
)


def utcnow() -> datetime:
    return datetime.now(UTC)


def ai_name(spec: BrainSpec | None) -> str:
    if spec is None:
        return "the AI service"
    if spec.id == LLMBackend.ANTHROPIC.value:
        return "Anthropic's Claude"
    return f"the {spec.label} AI service"


@dataclass(frozen=True)
class Recall:
    """What one turn sends: the trailer block, the facts in it, and the state it was read from
    (re-used by `after_turn`, so a plain turn costs one read)."""

    block: str = ""
    used: tuple[MemoryRef, ...] = ()
    state: MemoryState | None = None


class MemoryService:
    def __init__(
        self,
        *,
        store: MemoryStore,
        brains: BrainRegistry,
        billing: Billing | None,
        audit: AuditTrail,
        tz: str = "Asia/Kolkata",
        clock: Callable[[], datetime] = utcnow,
        max_runs: int = 20,
        extractor: Extractor | None = None,
    ) -> None:
        self.store = store
        self._brains = brains
        self._billing = billing
        self._tz = tz
        self._clock = clock
        self.learner = Learner(
            store=store,
            extractor=extractor or Extractor(brains),
            billing=billing,
            audit=audit,
            tz=tz,
            clock=clock,
            max_runs=max_runs,
        )
        self._tasks: set[asyncio.Task[Any]] = set()
        self._running: set[tuple[str, str]] = set()
        self._uses: dict[str, dict[str, int]] = {}
        self._flushed: dict[str, datetime] = {}

    # ---- recall ------------------------------------------------------------------------------

    async def recall(self, uid: str, spec: BrainSpec, query: str) -> Recall:
        if not gate.memory_allowed(spec):
            return Recall()
        try:
            state = await self.store.load(uid)
            if not state.settings.use:
                return Recall(state=state)
            now = self._clock()
            active = state.active()
            chosen = select_facts(active, query, now)
            block = render_block(state.profile, chosen, active, tz=self._tz, now=now)
        except Exception as exc:  # noqa: BLE001 — a reply without notes, never a failed reply
            log.warning("memory not recalled this turn", extra={"reason": type(exc).__name__})
            return Recall()
        used = used_facts(chosen, block)
        self._note_use(uid, [f.id for f in used])
        refs = tuple(MemoryRef(id=f.id, text=f.text) for f in used)
        return Recall(block=block, used=refs, state=state)

    def _note_use(self, uid: str, ids: Iterable[str]) -> None:
        bucket = self._uses.setdefault(uid, {})
        for fid in ids:
            bucket[fid] = bucket.get(fid, 0) + 1

    # ---- after the reply ----------------------------------------------------------------------

    def after_turn(self, uid: str, session: Session, spec: BrainSpec, recall: Recall) -> None:
        """Schedule background work; returns at once and never raises."""
        try:
            if not gate.memory_allowed(spec):
                return
            now = self._clock()
            last = self._flushed.get(uid)
            if self._uses.get(uid) and (last is None or now - last >= FLUSH_EVERY):
                self._flushed[uid] = now
                self._spawn(self._flush(uid))
            state = recall.state
            if state is None or not learning_on(state):
                return
            snap = snapshot(session)
            if not is_due(pending(state, snap), now) or (uid, snap.session_id) in self._running:
                return
            self._spawn(self._learn_bg(uid, snap, spec, state))
        except Exception as exc:  # noqa: BLE001
            log.warning("memory follow-up not scheduled", extra={"reason": type(exc).__name__})

    def _spawn(self, coro: Coroutine[Any, Any, Any]) -> None:
        task = asyncio.get_running_loop().create_task(coro)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def drain(self) -> None:
        """Wait for background work (tests, evals, shutdown)."""
        while self._tasks:
            await asyncio.gather(*list(self._tasks), return_exceptions=True)

    async def _learn_bg(
        self, uid: str, snap: Snapshot, spec: BrainSpec, state: MemoryState
    ) -> None:
        key = (uid, snap.session_id)
        self._running.add(key)
        try:
            res = await self.learner.run(uid, snap, spec, state)
            log.info("background learning", extra={"status": res.status.value})
        except Exception as exc:  # noqa: BLE001 — errors never reach the owner
            log.warning("background learning failed", extra={"reason": type(exc).__name__})
        finally:
            self._running.discard(key)

    async def _flush(self, uid: str) -> None:
        counts = self._uses.pop(uid, {})
        if not counts:
            return
        now = self._clock()

        def bump(cur: MemoryState) -> MemoryState | None:
            known = cur.ids()
            upd = {
                fid: UseStat(at=now, n=(cur.usage[fid].n if fid in cur.usage else 0) + k)
                for fid, k in counts.items()
                if fid in known
            }
            return cur.with_usage(upd) if upd else None

        try:
            await self.store.mutate(uid, bump)
        except Exception as exc:  # noqa: BLE001 — counters only
            log.warning("memory use counters not saved", extra={"reason": type(exc).__name__})

    async def learn(self, uid: str, session: Session, spec: BrainSpec) -> LearnResult:
        """Run learning for `session` now (if due), reading the state fresh."""
        return await self.learner.run(uid, snapshot(session), spec, None)

    # ---- the owner's view --------------------------------------------------------------------

    def private_brain(self) -> BrainSpec | None:
        if self._brains.default.tools_allowed:
            return self._brains.default
        return next((b for b in self._brains.list() if b.tools_allowed), None)

    def _inr_per_usd(self) -> float:
        return self._billing.fx.peek().inr_per_usd if self._billing is not None else DEFAULT_RATE

    def _cost_words(self, spec: BrainSpec) -> str | None:
        model = spec.tiers[ModelTier.FAST]
        if not is_priced(model):
            return None
        rate = self._inr_per_usd()
        typical = cost_usd(model, TYPICAL_RUN) * TYPICAL_RUNS_PER_DAY * 31 * rate
        worst = cost_usd(model, WORST_RUN) * self.learner.max_runs * 31 * rate
        if worst <= 0:
            return "no charge (₹0) on this brain"
        about = f"about {rupees(round(typical))} a month" if typical >= 0.5 else "under ₹1 a month"
        return f"{about}, at most {rupees(round(worst))} at {self.learner.max_runs} runs a day"

    def learn_cost_note(self) -> str:
        """Shown before the owner agrees (≤ 300 characters): the cost and what goes where."""
        spec = self.private_brain()
        if spec is None:
            return "No private AI brain is configured, so learning can't run (₹0)."
        sent = DATA_SENT.format(ai=ai_name(spec))
        words = self._cost_words(spec)
        if words is None:
            return f"The cost in ₹ is unknown (no price for this model). {sent}"
        return f"{words[0].upper()}{words[1:]} on the fast model. {sent}"

    def today(self) -> str:
        """The owner's local date (YYYY-MM-DD)."""
        return self.learner.day(self._clock())

    async def view(self, uid: str) -> MemoryView:
        s = await self.store.load(uid)
        facts = s.all_facts()
        active = [f for f in facts if f.active]
        return MemoryView(
            settings=s.settings,
            profile=s.profile,
            facts=active,
            counts=Counts(active=len(active), replaced=len(facts) - len(active), limit=MAX_ACTIVE),
            learn_cost_note_inr=self.learn_cost_note(),
            runs_today=self.learner.runs_today(s, self._clock()),
        )

    # ---- the owner's changes -----------------------------------------------------------------

    async def update_settings(self, uid: str, patch: SettingsPatch) -> MemorySettings:
        now = self._clock()

        def change(cur: MemoryState) -> MemoryState:
            s = cur.settings
            upd: dict[str, Any] = {}
            if patch.use is not None:
                upd["use"] = patch.use
            if patch.learn is True and not s.learn:
                if not patch.confirm_spend:
                    raise ConsentRequired(self._consent_message())
                upd.update(learn=True, learn_consented_at=now)
            elif patch.learn is False:
                upd.update(learn=False, learn_consented_at=None)
            return cur.with_settings(s.model_copy(update=upd))

        new = await self.store.mutate(uid, change)
        log.info(
            "memory settings changed",
            extra={"use": new.settings.use, "learn": new.settings.learn},
        )
        return new.settings

    def _consent_message(self) -> str:
        spec = self.private_brain()
        words = self._cost_words(spec) if spec is not None else None
        return MSG_CONSENT.format(cost=words or "₹ cost unknown", ai=ai_name(spec))

    async def put_profile(self, uid: str, label: str, text: str) -> Profile:
        now = self._clock()
        new = await self.store.mutate(uid, lambda cur: set_profile(purge(cur, now), label, text))
        return new.profile

    async def remember(
        self,
        uid: str,
        text: str,
        category: str,
        *,
        origin: Origin,
        keywords: Iterable[object] = (),
        source: FactSource | None = None,
    ) -> tuple[Fact, bool]:
        """Add a fact unless an equivalent one exists: (the fact, created?)."""
        now = self._clock()
        out: list[tuple[Fact, bool]] = []

        def change(cur: MemoryState) -> MemoryState | None:
            out.clear()
            cur = purge(cur, now)
            f = new_fact(
                cur, text, category, origin=origin, now=now, keywords=keywords, source=source
            )
            dup = find_duplicate(cur, f.text)
            if dup is not None:
                out.append((dup, False))
                return None
            out.append((f, True))
            return add_fact(cur, f)

        await self.store.mutate(uid, change)
        return out[0]

    async def add_fact(
        self, uid: str, text: str, category: str, *, keywords: Iterable[object] = ()
    ) -> Fact:
        return (await self.remember(uid, text, category, origin="added", keywords=keywords))[0]

    async def patch_fact(self, uid: str, fid: str, patch: FactPatch) -> Fact:
        now = self._clock()
        out: list[Fact] = []

        def change(cur: MemoryState) -> MemoryState:
            out.clear()
            new, f = edit_fact(
                cur, fid, text=patch.text, category=patch.category, pinned=patch.pinned, now=now
            )
            out.append(f)
            return new

        await self.store.mutate(uid, change)
        return out[0]

    async def delete_fact(self, uid: str, fid: str) -> None:
        if not await self.forget_ids(uid, [fid]):
            raise LookupError("No such fact.")

    async def forget_ids(self, uid: str, ids: Iterable[str]) -> list[str]:
        gone: list[str] = []
        wanted = list(ids)

        def change(cur: MemoryState) -> MemoryState | None:
            new, deleted = delete_facts(cur, wanted)
            gone[:] = deleted
            return new if deleted else None

        await self.store.mutate(uid, change)
        log.info("memory facts deleted", extra={"count": len(gone)})
        return gone

    async def forget_all(self, uid: str) -> None:
        await self.store.mutate(uid, wipe)
        log.info("memory wiped")

    async def export(self, uid: str) -> dict[str, Any]:
        return export_data(await self.store.load(uid), self._clock())

    async def import_(self, uid: str, data: dict[str, Any]) -> ImportResult:
        now = self._clock()
        out: list[tuple[int, int]] = []

        def change(cur: MemoryState) -> MemoryState:
            new, added, skipped = import_data(purge(cur, now), data, now)
            out[:] = [(added, skipped)]
            return new

        await self.store.mutate(uid, change)
        added, skipped = out[0]
        log.info("memory imported", extra={"added": added, "skipped": skipped})
        return ImportResult(added=added, skipped=skipped)

    # ---- tool backends --------------------------------------------------------------------

    async def search(self, uid: str, query: str, limit: int = SEARCH_LIMIT) -> list[Fact]:
        state = await self.store.load(uid)
        active = state.active()
        sc = scores(active, query, self._clock())
        return sorted((f for f in active if f.id in sc), key=lambda f: -sc[f.id])[:limit]

    async def facts_by_ids(self, uid: str, ids: Iterable[str]) -> list[Fact]:
        wanted = list(dict.fromkeys(ids))
        by_id = {f.id: f for f in (await self.store.load(uid)).all_facts()}
        return [by_id[i] for i in wanted if i in by_id]


def build_memory_service(
    *,
    docs: Docs,
    brains: BrainRegistry,
    billing: Billing | None,
    audit: AuditTrail,
    prefix: str,
    tz: str,
    max_runs: int,
) -> MemoryService:
    return MemoryService(
        store=MemoryStore(docs, prefix=prefix),
        brains=brains,
        billing=billing,
        audit=audit,
        tz=tz,
        max_runs=max_runs,
    )


__all__ = ["MemoryService", "Recall", "ai_name", "build_memory_service"]
