# src/jarvis/recall/learning.py
"""Background learning (Layer 3 orchestration, slice 8 D4/D5/D7/D8/D9).

    gate (private brain) → switched on with consent → batch due (≥ 3 new owner messages, or one
    ≥ 10 min old) → today's runs < cap → monthly limit (Billing.ensure_allowed; at the limit: skip,
    nothing counted) → claim (transaction: runs + 1, conversation cursor moved) → audit
    "executing" (model, input size; fail closed) → one FAST call → meter as "memory" → apply
    (filter, dedupe, replace; never delete) → audit "executed" with counts.

The input is the owner's own messages only: user turns without blocks (never tool results,
approval narration, or replies). Errors never reach the owner; the caller runs this after the
reply is stored. Audit and logs carry ids and counts, never fact text.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import StrEnum
from zoneinfo import ZoneInfo

from jarvis.billing import Billing, BudgetError
from jarvis.core.guardrails import ActionRisk
from jarvis.core.models import Session
from jarvis.llm.base import Role
from jarvis.llm.brains import BrainSpec
from jarvis.logging import get_logger
from jarvis.recall import gate
from jarvis.recall.errors import MemoryFull
from jarvis.recall.extract import Extraction, Extractor, Outcome, Prepared, Replacement
from jarvis.recall.models import Fact, FactSource, LearnState, MemoryState
from jarvis.recall.ops import (
    add_fact,
    fact_text,
    find_duplicate,
    new_fact,
    purge,
    replace_fact,
)
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
MAX_CURSORS = 50
MAX_NOTES_IN_PROMPT = 30


class LearnStatus(StrEnum):
    OFF = "off"
    TRAINING_BRAIN = "training_brain"
    NOT_DUE = "not_due"
    CAPPED = "capped"
    BUDGET = "budget"
    FAILED = "failed"
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
    """Owner messages only: user turns with text and no blocks."""
    owner = tuple(
        OwnerLine(i, t.content, t.created_at)
        for i, t in enumerate(session.turns)
        if t.role is Role.USER and not t.blocks and t.content.strip()
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


@dataclass
class _Tally:
    added: int = 0
    replaced: int = 0
    dropped: int = 0
    ids: list[str] = field(default_factory=list)


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
        lines = pending(cur, snap)
        if not learning_on(cur):
            return LearnResult(LearnStatus.OFF)
        if not is_due(lines, now):
            return LearnResult(LearnStatus.NOT_DUE)
        if self.runs_today(cur, now) >= self.max_runs:
            return LearnResult(LearnStatus.CAPPED)
        if not await self._allowed(uid, spec):
            return LearnResult(LearnStatus.BUDGET)
        prep = self._extractor.prepare(spec, [x.text for x in lines], self._notes(cur, lines, now))
        try:
            await self._claim(uid, snap, now)
        except _Skip as skip:
            return LearnResult(skip.status)
        return await self._call_and_apply(uid, snap, lines, prep, now)

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

    async def _claim(self, uid: str, snap: Snapshot, now: datetime) -> None:
        """Count the run and move the cursor BEFORE the call: the daily cap holds under
        concurrency, and a call that fails is not retried on the same messages."""
        day = self.day(now)

        def take(cur: MemoryState) -> MemoryState:
            if not learning_on(cur):
                raise _Skip(LearnStatus.OFF)
            runs = cur.learn.runs if cur.learn.day == day else 0
            if runs >= self.max_runs:
                raise _Skip(LearnStatus.CAPPED)
            if cur.learn.cursors.get(snap.session_id, 0) >= snap.turn_count:
                raise _Skip(LearnStatus.NOT_DUE)  # another run took these messages
            cursors = {k: v for k, v in cur.learn.cursors.items() if k != snap.session_id}
            cursors[snap.session_id] = snap.turn_count
            kept = dict(list(cursors.items())[-MAX_CURSORS:])
            return cur.with_learn(LearnState(day=day, runs=runs + 1, cursors=kept))

        await self._store.mutate(uid, take)

    async def _call_and_apply(
        self,
        uid: str,
        snap: Snapshot,
        lines: Sequence[OwnerLine],
        prep: Prepared,
        now: datetime,
    ) -> LearnResult:
        args = {"session": snap.session_id, "model": prep.model, "input_chars": len(prep.prompt)}
        before = f"model={prep.model} input_chars={len(prep.prompt)} messages={len(lines)}"
        if not await self._log(args, "executing", before):
            return LearnResult(LearnStatus.FAILED)  # fail closed: no record, no call
        try:
            out = await self._extractor.run(prep)
        except Exception as exc:  # noqa: BLE001 — never reaches the owner
            log.warning("learning call failed", extra={"reason": type(exc).__name__})
            await self._log(args, "error", type(exc).__name__)
            return LearnResult(LearnStatus.FAILED)
        if self._billing is not None:
            await self._billing.record(uid, METER_LABEL, out.cost_usd)  # never raises
        tally, note = await self._apply(uid, snap, lines, out, now)
        detail = (
            f"model={out.model} cost_usd={out.cost_usd:.6f} added={tally.added} "
            f"replaced={tally.replaced} dropped={tally.dropped} ids={','.join(tally.ids)}{note}"
        )
        await self._log(args, "executed", detail)
        log.info(
            "learning run done",
            extra={"added": tally.added, "replaced": tally.replaced, "dropped": tally.dropped},
        )
        return LearnResult(
            LearnStatus.DONE, tally.added, tally.replaced, tally.dropped, out.cost_usd
        )

    async def _apply(
        self, uid: str, snap: Snapshot, lines: Sequence[OwnerLine], out: Outcome, now: datetime
    ) -> tuple[_Tally, str]:
        ext = out.extraction
        if ext is None:
            return _Tally(dropped=1), " output=invalid"
        source = FactSource(session_id=snap.session_id, turn=lines[-1].index if lines else None)
        tally = _Tally()

        def change(cur: MemoryState) -> MemoryState | None:
            nonlocal tally
            tally = _Tally(dropped=ext.dropped)
            new = _merge(purge(cur, now), ext, source, now, tally)
            return new if new is not cur else None

        try:
            await self._store.mutate(uid, change)
        except Exception as exc:  # noqa: BLE001 — storage trouble: nothing learned this time
            log.error("learning results not stored", extra={"reason": type(exc).__name__})
            return _Tally(dropped=len(ext.facts) + len(ext.replace)), " stored=no"
        return tally, ""

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
    if old is None:
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
        pinned=old.pinned,
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
