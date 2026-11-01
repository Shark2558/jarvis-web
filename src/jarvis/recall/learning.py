# src/jarvis/recall/learning.py
"""Background learning (Layer 3 orchestration, slice 8 D4/D5/D7/D8/D9; review findings 3/5/6).

    gate (private brain) → switched on with consent → batch due (≥ 3 new owner messages, or one
    ≥ 10 min old) → no live lease → today's runs < cap (a retry is not a new run) → monthly
    limit (Billing.ensure_allowed; at the limit: skip, nothing counted) → claim (transaction: a
    lease; a new run is counted; the cursor does NOT move) → audit "executing" (fail closed) →
    one FAST call → apply (transaction, only while our lease is the stored one and no "Forget
    everything" / "learning off" happened since: filter, dedupe, replace learned facts only,
    never delete; the cursor moves to the batch end) — and in `finally`, whatever happened
    (error, cancel on shutdown): meter as "memory" (an estimate if no usage came back), mark
    the lease failed if nothing was applied, audit the result. See `jarvis.recall.lease`.

The input is the owner's own messages only: user turns without blocks (never tool results,
approval narration, or replies), minus pasted third-party text (`pasted.looks_pasted`). Errors
never reach the owner. Audit and logs carry ids and counts, never fact text.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Any
from zoneinfo import ZoneInfo

import anyio

from jarvis.billing import Billing, BudgetError
from jarvis.core.guardrails import ActionRisk
from jarvis.core.models import Session
from jarvis.llm.base import Role
from jarvis.llm.brains import BrainSpec
from jarvis.logging import get_logger
from jarvis.recall import gate
from jarvis.recall.errors import MemoryFull
from jarvis.recall.extract import (
    Extraction,
    Extractor,
    Outcome,
    Prepared,
    Replacement,
    estimate_cost,
)
from jarvis.recall.lease import (
    MAX_ATTEMPTS,
    Claim,
    ClaimKind,
    NoClaim,
    abandoned,
    claim,
    mark_failed,
    release,
    skippable,
)
from jarvis.recall.models import Fact, FactSource, Lease, MemoryState
from jarvis.recall.ops import (
    add_fact,
    fact_text,
    find_duplicate,
    new_fact,
    purge,
    replace_fact,
)
from jarvis.recall.pasted import looks_pasted
from jarvis.recall.retrieval import scores
from jarvis.recall.sensitive import special_category
from jarvis.recall.store import MemoryStore
from jarvis.recall.text import norm_key
from jarvis.tools.audit import AuditTrail

log = get_logger(__name__)

AGENT = "memory_learn"
TOOL = "memory_learn.extract"
METER_LABEL = "memory"
BATCH = 3
STALE_AFTER = timedelta(minutes=10)
MAX_NOTES_IN_PROMPT = 30
SETTLE_GRACE_S = 5.0  # metering, lease and audit still happen when the run is cancelled


class LearnStatus(StrEnum):
    OFF = "off"
    TRAINING_BRAIN = "training_brain"
    NOT_DUE = "not_due"
    BUSY = "busy"  # another run holds this conversation's batch
    CAPPED = "capped"
    BUDGET = "budget"
    FAILED = "failed"  # will be retried (once) without counting a run
    SKIPPED = "skipped"  # failed twice, or claimed before a wipe / learning off: moved past
    STALE = "stale"  # finished after a wipe / learning off / a takeover: nothing applied
    DONE = "done"


@dataclass(frozen=True)
class OwnerLine:
    index: int
    text: str
    at: datetime


@dataclass(frozen=True)
class Snapshot:
    """What learning may read of a conversation, taken when the reply is stored."""

    session_id: str
    turn_count: int
    owner: tuple[OwnerLine, ...]


@dataclass(frozen=True)
class LearnResult:
    status: LearnStatus
    added: int = 0
    replaced: int = 0
    dropped: int = 0
    cost_usd: float = 0.0


def snapshot(session: Session) -> Snapshot:
    """Owner messages only: user turns with text and no blocks, and not pasted text."""
    owner = tuple(
        OwnerLine(i, t.content, t.created_at)
        for i, t in enumerate(session.turns)
        if t.role is Role.USER
        and not t.blocks
        and t.content.strip()
        and not looks_pasted(t.content)
    )
    return Snapshot(session.id, len(session.turns), owner)


def pending(state: MemoryState, snap: Snapshot) -> list[OwnerLine]:
    cursor = state.learn.cursors.get(snap.session_id, 0)
    return [line for line in snap.owner if line.index >= cursor]


def is_due(lines: Sequence[OwnerLine], now: datetime) -> bool:
    if len(lines) >= BATCH:
        return True
    return bool(lines) and now - min(line.at for line in lines) >= STALE_AFTER


def learning_on(state: MemoryState) -> bool:
    return state.settings.learn and state.settings.learn_consented_at is not None


class _Skip(Exception):
    def __init__(self, status: LearnStatus) -> None:
        super().__init__(status.value)
        self.status = status


class _LeaseLost(Exception):
    """Our lease is no longer the stored one (taken over after 5 minutes): apply nothing."""


_NO_CLAIM = {
    "busy": LearnStatus.BUSY,
    "capped": LearnStatus.CAPPED,
    "not_due": LearnStatus.NOT_DUE,
}


@dataclass
class _Tally:
    added: int = 0
    replaced: int = 0
    dropped: int = 0
    ids: list[str] = field(default_factory=list)


@dataclass
class _Run:
    """One claimed run as the call, the apply and the `finally` see it."""

    uid: str
    snap: Snapshot
    lease: Lease
    prep: Prepared
    lines: tuple[OwnerLine, ...]
    out: Outcome | None = None
    started: bool = False
    applied: bool = False
    outcome: str = "error"
    detail: str = "cancelled"

    def args(self) -> dict[str, Any]:
        return {
            "session": self.snap.session_id,
            "model": self.prep.model,
            "input_chars": len(self.prep.prompt),
            "attempt": self.lease.attempts,
        }

    def cost(self) -> float:
        if self.out is not None:
            return self.out.cost_usd
        return estimate_cost(self.prep.model, self.prep.prompt) if self.started else 0.0


def _items(ext: Extraction | None) -> int:
    return 0 if ext is None else len(ext.facts) + len(ext.replace)


class Learner:
    def __init__(
        self,
        *,
        store: MemoryStore,
        extractor: Extractor,
        billing: Billing | None,
        audit: AuditTrail,
        tz: str,
        clock: Callable[[], datetime],
        max_runs: int,
    ) -> None:
        self._store = store
        self._extractor = extractor
        self._billing = billing
        self._audit = audit
        self._tz = ZoneInfo(tz)
        self._clock = clock
        self.max_runs = max_runs

    def day(self, now: datetime) -> str:
        return now.astimezone(self._tz).date().isoformat()

    def runs_today(self, state: MemoryState, now: datetime) -> int:
        return state.learn.runs if state.learn.day == self.day(now) else 0

    # ---- the run ---------------------------------------------------------------------------

    async def run(
        self, uid: str, snap: Snapshot, spec: BrainSpec, state: MemoryState | None
    ) -> LearnResult:
        if not gate.memory_allowed(spec):
            return LearnResult(LearnStatus.TRAINING_BRAIN)
        now = self._clock()
        cur = state if state is not None else await self._store.load(uid)
        if not learning_on(cur):
            return LearnResult(LearnStatus.OFF)
        early = self._precheck(cur, snap, now)
        if early is not None:
            return LearnResult(early)
        held = cur.learn.leases.get(snap.session_id)
        skip_only = held is not None and skippable(held, cur.learn.gen)
        if not skip_only and not await self._allowed(uid, spec):
            return LearnResult(LearnStatus.BUDGET)
        try:
            claimed, got = await self._claim(uid, snap, now)
        except _Skip as skip:
            return LearnResult(skip.status)
        if got.kind is ClaimKind.SKIP:
            return await self._skipped(snap, got)
        lines = tuple(x for x in snap.owner if got.lease.start <= x.index < got.lease.end)
        notes = self._notes(claimed, lines, now)
        prep = self._extractor.prepare(spec, [x.text for x in lines], notes)
        return await self._call_and_apply(_Run(uid, snap, got.lease, prep, lines), now)

    def _precheck(self, cur: MemoryState, snap: Snapshot, now: datetime) -> LearnStatus | None:
        """The cheap checks on the state already read (the claim re-checks in a transaction)."""
        held = cur.learn.leases.get(snap.session_id)
        if held is not None and not abandoned(held, now):
            return LearnStatus.BUSY
        if held is not None and skippable(held, cur.learn.gen):
            return None  # the claim moves past it: no call
        if not is_due(pending(cur, snap), now):
            return LearnStatus.NOT_DUE
        if held is None and self.runs_today(cur, now) >= self.max_runs:
            return LearnStatus.CAPPED
        return None

    async def _allowed(self, uid: str, spec: BrainSpec) -> bool:
        if self._billing is None:
            return True
        try:
            await self._billing.ensure_allowed(uid, spec)
        except BudgetError as exc:
            log.info("learning skipped: monthly limit", extra={"reason": type(exc).__name__})
            return False
        return True

    @staticmethod
    def _notes(state: MemoryState, lines: Sequence[OwnerLine], now: datetime) -> list[Fact]:
        """Existing notes the messages might repeat or contradict (so a "replace" has an id)."""
        active = state.active()
        if len(active) <= MAX_NOTES_IN_PROMPT:
            return active
        sc = scores(active, " ".join(x.text for x in lines), now)
        ranked = sorted((f for f in active if f.id in sc), key=lambda f: -sc[f.id])
        return ranked[:MAX_NOTES_IN_PROMPT]

    async def _claim(self, uid: str, snap: Snapshot, now: datetime) -> tuple[MemoryState, Claim]:
        """Phase one: a lease (and, for a new batch, the day's run count) in one transaction;
        the cursor stays until the result is applied."""
        day = self.day(now)
        got: list[Claim] = []

        def take(cur: MemoryState) -> MemoryState:
            if not learning_on(cur):
                raise _Skip(LearnStatus.OFF)
            try:
                learn, c = claim(
                    cur.learn,
                    snap.session_id,
                    snap.turn_count,
                    day=day,
                    max_runs=self.max_runs,
                    now=now,
                )
            except NoClaim as no:
                raise _Skip(_NO_CLAIM[no.reason]) from None
            got[:] = [c]
            return cur.with_learn(learn)

        claimed = await self._store.mutate(uid, take)
        return claimed, got[0]

    async def _skipped(self, snap: Snapshot, got: Claim) -> LearnResult:
        lease = got.lease
        args = {"session": snap.session_id, "attempt": lease.attempts}
        why = "attempts" if lease.attempts >= MAX_ATTEMPTS else "forgotten_or_off"
        await self._log(args, "skipped", f"reason={why} turns={lease.start}-{lease.end}")
        log.warning("learning batch skipped", extra={"reason": why, "attempts": lease.attempts})
        return LearnResult(LearnStatus.SKIPPED)

    async def _call_and_apply(self, run: _Run, now: datetime) -> LearnResult:
        before = (
            f"model={run.prep.model} input_chars={len(run.prep.prompt)} "
            f"messages={len(run.lines)} attempt={run.lease.attempts}"
        )
        if not await self._log(run.args(), "executing", before):
            await self._mark_failed(run)
            return LearnResult(LearnStatus.FAILED)  # fail closed: no record, no call
        try:
            run.started = True
            run.out = await self._extractor.run(run.prep)
            tally, note, stale = await self._apply(run, now)
            run.outcome = "executed"
            run.detail = (
                f"model={run.out.model} added={tally.added} replaced={tally.replaced} "
                f"dropped={tally.dropped} ids={','.join(tally.ids)}{note}"
            )
        except Exception as exc:  # noqa: BLE001 — never reaches the owner; retried once
            log.warning("learning call failed", extra={"reason": type(exc).__name__})
            run.detail = type(exc).__name__
            return LearnResult(LearnStatus.FAILED)
        finally:
            await self._settle(run)
        log.info(
            "learning run done",
            extra={"added": tally.added, "replaced": tally.replaced, "stale": stale},
        )
        status = LearnStatus.STALE if stale else LearnStatus.DONE
        return LearnResult(status, tally.added, tally.replaced, tally.dropped, run.cost())

    async def _settle(self, run: _Run) -> None:
        """Always, even when cancelled: meter what the call may have cost, hand the batch back
        if nothing was applied, and audit the result."""
        with anyio.move_on_after(SETTLE_GRACE_S, shield=True):
            cost = run.cost()
            if self._billing is not None:
                await self._billing.record(run.uid, METER_LABEL, cost)  # never raises
            if not run.applied:
                await self._mark_failed(run)
            await self._log(run.args(), run.outcome, f"{run.detail} cost_usd={cost:.6f}")

    async def _mark_failed(self, run: _Run) -> None:
        def change(cur: MemoryState) -> MemoryState | None:
            learn = mark_failed(cur.learn, run.snap.session_id, run.lease.lease_id)
            return None if learn is None else cur.with_learn(learn)

        try:
            await self._store.mutate(run.uid, change)
        except Exception as exc:  # noqa: BLE001 — the lease then expires after 5 minutes
            log.warning("learning lease not handed back", extra={"reason": type(exc).__name__})

    async def _apply(self, run: _Run, now: datetime) -> tuple[_Tally, str, bool]:
        """Phase two: only while our lease is the stored one. Moves the cursor to the batch end
        and drops the lease in the same transaction; a wipe or "learning off" since the claim
        (another generation) means the results are dropped, the batch consumed."""
        assert run.out is not None
        ext, sid = run.out.extraction, run.snap.session_id
        source = FactSource(session_id=sid, turn=run.lines[-1].index if run.lines else None)
        tally, stale = _Tally(), False

        def change(cur: MemoryState) -> MemoryState:
            nonlocal tally, stale
            held = cur.learn.leases.get(sid)
            if held is None or held.lease_id != run.lease.lease_id:
                raise _LeaseLost()
            base = cur.with_learn(release(cur.learn, sid, held.end))
            stale = held.gen != cur.learn.gen or not learning_on(cur)
            if stale or ext is None:
                tally = _Tally(dropped=_items(ext) if stale else 1)
                return base
            tally = _Tally(dropped=ext.dropped)
            return _merge(purge(base, now), ext, source, now, tally)

        try:
            await self._store.mutate(run.uid, change)
        except _LeaseLost:
            return _Tally(dropped=_items(ext)), " lease=lost", True
        run.applied = True
        note = " stale=yes" if stale else (" output=invalid" if ext is None else "")
        return tally, note, stale

    async def _log(self, args: dict[str, object], outcome: str, detail: str) -> bool:
        try:
            await self._audit.append(
                agent=AGENT,
                tool=TOOL,
                risk=ActionRisk.REVERSIBLE,
                outcome=outcome,
                args=args,
                detail=detail,
            )
        except Exception as exc:  # noqa: BLE001
            log.error(
                "AUDIT WRITE FAILED for a learning run",
                extra={"outcome": outcome, "error": type(exc).__name__},
            )
            return False
        return True


# ---- applying an extraction (pure) ----------------------------------------------------------


def _replace_one(
    cur: MemoryState, r: Replacement, source: FactSource, now: datetime
) -> tuple[MemoryState, str] | None:
    old = next((f for f in cur.active() if f.id == r.id), None)
    if old is None or old.origin != "learned":  # what the owner told / added is theirs
        return None
    text = fact_text(r.text)
    if special_category(text) or norm_key(text) == norm_key(old.text):
        return None
    new = new_fact(
        cur,
        text,
        r.category or old.category,
        origin="learned",
        now=now,
        keywords=r.keywords or old.keywords,
        source=source,
    )
    return replace_fact(cur, old.id, new, now), new.id


def _merge(
    cur: MemoryState, ext: Extraction, source: FactSource, now: datetime, tally: _Tally
) -> MemoryState:
    """Replacements first (they name existing ids), then new facts; each item that fails a rule
    is dropped on its own. Never deletes."""
    start = cur
    for r in ext.replace:
        try:
            done = _replace_one(cur, r, source, now)
        except (ValueError, LookupError, MemoryFull):
            done = None
        if done is None:
            tally.dropped += 1
            continue
        cur = done[0]
        tally.replaced += 1
        tally.ids.append(done[1])
    for item in ext.facts:
        try:
            text = fact_text(item.text)
            if special_category(text) or find_duplicate(cur, text) is not None:
                raise ValueError("not kept")
            f = new_fact(
                cur,
                text,
                item.category,
                origin="learned",
                now=now,
                keywords=item.keywords,
                source=source,
            )
            cur = add_fact(cur, f)
        except (ValueError, MemoryFull):
            tally.dropped += 1
            continue
        tally.added += 1
        tally.ids.append(f.id)
    return cur if (tally.added or tally.replaced) else start


__all__ = [
    "AGENT",
    "METER_LABEL",
    "LearnResult",
    "LearnStatus",
    "Learner",
    "OwnerLine",
    "Snapshot",
    "is_due",
    "learning_on",
    "pending",
    "snapshot",
]
