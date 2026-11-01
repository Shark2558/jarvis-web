# src/jarvis/core/brain.py
"""The core loop (Layer 4): session in → context → LLM → session out.

    load/create session ─► guard input ─► append user turn ─► build window
          ─► router.complete(tier) ─► append assistant turn ─► save ─► ChatResponse

Everything here is vendor-neutral. Phase 2 inserts the tool-calling loop between
`router.complete` and `append assistant turn`; the data model already carries what it needs.

Long-term memory (slice 8): the owner's notes go into the dynamic trailer (never the cached
system prompt) for brains that keep content private; the reply reports which were sent; learning
is scheduled after the reply is stored and never delays or breaks it. At the start of a request
the owner's other conversations with unlearned messages are swept in the background (Cloud Run
gives CPU only while a request runs); the scheduler tick sweeps too (`sweep_memory`). Each tool
round runs with the "untrusted content seen" flag, so memory_save after other people's text
becomes a card.

Persona (slice 9): the owner's wit level (voice settings, cached; any failure or a slow read →
"film", never a failed reply) picks one of three stable, cacheable system prompts; a spoken
message (`channel: voice`) adds the spoken-reply rule to the per-request trailer only.

Spending (slice 7b): every model call — chat, each tool round, the round-limit summary, approval
narration, the stream — goes through `_admit` (the owner's monthly limit, `Billing.ensure_allowed`)
BEFORE it is made, and its cost is added to the month after it (`Billing.record`, never fails the
reply). A turn is also admitted before the owner's message is stored, so a refused turn leaves
no unanswered message behind.
"""

from __future__ import annotations

import asyncio
import contextlib
import time
import weakref
from collections.abc import AsyncGenerator, AsyncIterator, Sequence
from dataclasses import dataclass, field
from typing import Protocol

from jarvis.billing import Billing, BudgetError
from jarvis.config import Settings
from jarvis.core.guardrails import PendingAction, guard_input
from jarvis.core.models import ChatRequest, ChatResponse, PendingApproval, Session, Turn
from jarvis.core.prompts import (
    DEFAULT_WIT,
    PERSONA_VERSION,
    WIT_IDS,
    build_system_prompt,
    build_trailer,
)
from jarvis.core.window import build_window
from jarvis.llm.base import (
    ChatMessage,
    Completion,
    Effort,
    LLMError,
    Role,
    TextBlock,
    ToolCall,
    ToolResultBlock,
    Usage,
)
from jarvis.llm.brains import BrainRegistry, BrainSpec
from jarvis.llm.pricing import cost_usd as priced_cost
from jarvis.llm.pricing import estimate_usage
from jarvis.llm.router import ModelRouter, ModelTier
from jarvis.logging import get_logger, get_trace_id
from jarvis.memory.base import SessionNotFound, SessionStore
from jarvis.recall.models import MemoryRef
from jarvis.recall.service import MemoryService, Recall
from jarvis.tools.gateway import Gateway, GatewayOutcome, GatewayResult
from jarvis.tools.taint import context_trust, untrusted_seen

log = get_logger(__name__)

BRAIN_KEY = "brain"  # session.metadata key remembering the owner's brain choice
CUTOFF_KEY = "brain_cutoff"  # turn index before which history is withheld from training brains
SWEEP_TICK_S = 20.0  # the scheduler tick's memory sweep is awaited, at most this long
WIT_READ_TIMEOUT_S = 1.5  # the owner's wit level is a nicety: never hold a reply for it


class WitSource(Protocol):
    """The owner's wit level (slice 9 D8): the voice settings, cached by the implementation."""

    async def wit_for(self, user_id: str) -> str: ...


@dataclass(frozen=True)
class _Decision:
    """What an owner's approve / decline produced, before it is narrated."""

    call: ToolCall
    result: GatewayResult
    fallback: str
    instruction: str


def _record_exchange(session: Session, d: _Decision, trace_id: str | None) -> None:
    """The decided action as a tool exchange (tool_use → tool_result + instruction)."""
    session.append(Turn(role=Role.ASSISTANT, content="", blocks=[d.call], trace_id=trace_id))
    result = ToolResultBlock(
        tool_use_id=d.call.id,
        content=d.result.for_model(),
        is_error=d.result.outcome is not GatewayOutcome.EXECUTED,
    )
    session.append(
        Turn(
            role=Role.USER,
            content="",
            blocks=[result, TextBlock(text=d.instruction)],
            trace_id=trace_id,
        )
    )


@dataclass(frozen=True)
class _ReplyMeta:
    trace_id: str
    total_ms: int
    rounds: int
    pending: list[PendingApproval]
    memory_used: list[MemoryRef]


@dataclass
class StreamMeta:
    """Filled in by `chat_stream` for its caller (the HTTP route's final event)."""

    memory_used: list[MemoryRef] = field(default_factory=list)


class Brain:
    def __init__(
        self,
        *,
        store: SessionStore,
        settings: Settings,
        router: ModelRouter | None = None,
        brains: BrainRegistry | None = None,
        gateway: Gateway | None = None,
        billing: Billing | None = None,
        memory: MemoryService | None = None,
        wit: WitSource | None = None,
    ) -> None:
        if brains is None:
            if router is None:
                raise ValueError("Brain needs either `brains` or a legacy `router`")
            default_id = settings.llm_backend.value
            brains = BrainRegistry(
                [
                    BrainSpec(
                        id=default_id,
                        label=default_id,
                        provider=router.provider,
                        tiers={t: router.resolve(t) for t in ModelTier},
                        trains_on_content=settings.llm_trains_on_content,
                    )
                ],
                default_id=default_id,
            )
        self.brains = brains
        self.router = brains.router_for(brains.default.id)  # default brain (health, CLI)
        self.store = store
        self.s = settings
        self.gateway = gateway
        # the app passes its own (Firestore, daily rate); without one: in-memory, default rate
        self.billing = billing or Billing.in_memory(brains, settings)
        self.memory = memory  # long-term notes about the owner (None: off)
        self.wit = wit  # the owner's wit level (None: always the default)
        self._systems = {
            w: build_system_prompt(honorific=settings.user_honorific, wit=w) for w in WIT_IDS
        }
        self._system = self._systems[DEFAULT_WIT]
        # One owner action at a time per conversation (chat, approve, decline, delete): no
        # lost turns, no double execution, no resurrected deletes. Locks vanish when unused.
        self._locks: weakref.WeakValueDictionary[str, asyncio.Lock] = weakref.WeakValueDictionary()

    @contextlib.asynccontextmanager
    async def _serialised(self, session_id: str | None) -> AsyncIterator[None]:
        if not session_id:
            yield
            return
        lock = self._locks.get(session_id)
        if lock is None:
            lock = asyncio.Lock()
            self._locks[session_id] = lock
        async with lock:
            yield

    def _tools_on(self, spec: BrainSpec) -> bool:
        """Tools exist AND this brain may see them. A training brain never gets tool specs —
        that is the private-data boundary, enforced here rather than by a banner."""
        return bool(
            self.gateway
            and self.s.tools_enabled
            and len(self.gateway.registry)
            and spec.tools_allowed
        )

    def _resolve_brain(self, session: Session, req: ChatRequest) -> BrainSpec:
        """request → session memory → default. Persists the choice on the session.

        Switching INTO a training brain records a history cutoff: everything said before the
        switch (which may include tool output — email, calendar, files) stays with the earlier
        brain and is never replayed to a vendor that may train on it."""
        previous_id = session.metadata.get(BRAIN_KEY)
        brain_id = req.brain or previous_id or self.brains.default.id
        spec = self.brains.get(brain_id)  # LookupError → 404 at the API
        if previous_id != spec.id:
            session.metadata[BRAIN_KEY] = spec.id
            if not spec.tools_allowed and session.turns:
                session.metadata[CUTOFF_KEY] = len(session.turns)
            log.info("brain selected", extra={"session_id": session.id, "brain": spec.id})
        return spec

    def _window_for(self, session: Session, spec: BrainSpec) -> list[ChatMessage]:
        """The context sent to `spec`. A training brain sees only turns after its cutoff, and
        never a turn that carries tool blocks or was produced from a tool / approval outcome
        (`tool_derived`: an approval narrated while a training brain was current, a reply
        written after tool rounds) — defence in depth beyond the cutoff."""
        turns = session.turns
        if not spec.tools_allowed:
            turns = turns[int(session.metadata.get(CUTOFF_KEY, 0)) :]
            turns = [t for t in turns if not t.blocks and not t.tool_derived]
        return build_window(
            turns, max_turns=self.s.session_max_turns, max_chars=self.s.session_max_chars
        )

    async def _persona(self, user_id: str) -> str:
        """The system prompt for the owner's wit level; the default on any failure."""
        if self.wit is None:
            return self._system
        try:
            wit = await asyncio.wait_for(self.wit.wit_for(user_id), WIT_READ_TIMEOUT_S)
        except Exception as exc:  # noqa: BLE001 — a persona nicety never fails a reply
            log.warning(
                "wit level unreadable; using the default", extra={"reason": type(exc).__name__}
            )
            return self._system
        return self._systems.get(wit, self._system)

    # ---- spending ---------------------------------------------------------------------------

    async def _admit(self, user_id: str, spec: BrainSpec) -> None:
        """The spending gate: raises BudgetReached / BudgetUnavailable before a paid call."""
        await self.billing.ensure_allowed(user_id, spec)

    async def check_budget(self, req: ChatRequest) -> None:
        """Would this request be refused by the monthly limit? Read-only: the stream route asks
        first so it can answer 402 instead of breaking a stream that already said 200."""
        brain_id = req.brain
        if brain_id is None and req.session_id:
            session = await self.store.get(req.session_id)
            if session is not None and session.user_id == req.user_id:
                brain_id = session.metadata.get(BRAIN_KEY)
        spec = self.brains.get(brain_id) if brain_id else self.brains.default
        await self._admit(req.user_id, spec)

    async def _rupees(self, *usd: float) -> tuple[float, ...]:
        return tuple([round(await self.billing.inr(u), 4) for u in usd])

    # ---- long-term memory ------------------------------------------------------------------

    async def _recall(self, user_id: str, spec: BrainSpec, text: str) -> Recall:
        """The notes block for this turn (empty for training brains; never raises)."""
        if self.memory is None:
            return Recall()
        return await self.memory.recall(user_id, spec, text)

    def _after_turn(self, user_id: str, session: Session, spec: BrainSpec, rec: Recall) -> None:
        """Background follow-up (learning, use counters) once the reply is stored."""
        if self.memory is not None:
            self.memory.after_turn(user_id, session, spec, rec)

    async def _finish_turn(
        self,
        user_id: str,
        session: Session,
        spec: BrainSpec,
        rec: Recall,
        reply: Turn,
        *,
        model: str,
        cost: float,
    ) -> None:
        """Store the streamed reply, then schedule the background follow-up."""
        session.append(reply.model_copy(update={"model": model, "cost_usd": cost}))
        await self.store.save(session)
        self._after_turn(user_id, session, spec, rec)

    def _sweep(self, user_id: str, rec: Recall, session_id: str) -> None:
        """At the start of a request: learn the owner's other conversations in the background
        while this request holds the CPU (≤ once per 5 minutes; never raises)."""
        if self.memory is not None:
            self.memory.schedule_sweep(
                user_id, self.store, self.brain_of, rec.state, exclude=session_id
            )

    def brain_of(self, session: Session) -> BrainSpec | None:
        """The brain a stored conversation uses now (None when it no longer exists)."""
        try:
            return self.brains.get(session.metadata.get(BRAIN_KEY) or self.brains.default.id)
        except LookupError:
            return None

    async def sweep_memory(self, user_ids: Sequence[str], *, within_s: float = SWEEP_TICK_S) -> int:
        """The scheduler tick's learning sweep: awaited, ≤ `within_s` in all, never raises.
        Returns the number of learning runs attempted."""
        memory = self.memory
        if memory is None:
            return 0
        done = 0

        async def every_owner() -> None:
            nonlocal done
            for uid in user_ids:
                try:
                    done += await memory.sweep(uid, self.store, self.brain_of)
                except Exception as exc:  # noqa: BLE001 — one owner never blocks another
                    log.warning("memory sweep failed", extra={"reason": type(exc).__name__})

        try:
            await asyncio.wait_for(every_owner(), within_s)
        except TimeoutError:
            log.warning("memory sweep stopped at its time bound", extra={"seconds": within_s})
        return done

    # ---- session helpers -----------------------------------------------------------------

    async def _load_or_create(self, req: ChatRequest) -> Session:
        if req.session_id:
            session = await self.store.get(req.session_id)
            if session is None:
                raise SessionNotFound(req.session_id)
            if session.user_id != req.user_id:
                # single-user today, but never let a session id leak across users
                raise SessionNotFound(req.session_id)
            return session
        session = Session(user_id=req.user_id, metadata={"persona": PERSONA_VERSION})
        await self.store.save(session)
        log.info("session created", extra={"session_id": session.id})
        return session

    def _tier(self, req: ChatRequest) -> ModelTier:
        return ModelTier(req.tier or self.s.default_tier)

    def _effort(self) -> Effort | None:
        return Effort(self.s.effort) if self.s.effort else None

    # ---- the loop ------------------------------------------------------------------------

    async def _start(self, req: ChatRequest) -> ChatRequest:
        """A brand-new conversation gets its id (and its lock) before any work happens, so an
        approval proposed in the first reply can't be decided while that reply is written."""
        if req.session_id:
            return req
        if req.brain:
            self.brains.get(req.brain)  # fail before creating an orphan session
        guard_input(req.message, max_chars=self.s.max_input_chars)
        await self.check_budget(req)  # a refused first message leaves no empty conversation
        session = await self._load_or_create(req)
        return req.model_copy(update={"session_id": session.id})

    async def chat(self, req: ChatRequest) -> ChatResponse:
        req = await self._start(req)
        async with self._serialised(req.session_id):
            return await self._chat(req)

    async def _chat(self, req: ChatRequest) -> ChatResponse:
        t0 = time.perf_counter()
        trace_id = get_trace_id()
        if req.brain:
            self.brains.get(req.brain)  # fail before creating an orphan session
        # validate first: a rejected first message must not leave an empty conversation
        text = guard_input(req.message, max_chars=self.s.max_input_chars)
        session = await self._load_or_create(req)
        spec = self._resolve_brain(session, req)
        await self._admit(req.user_id, spec)  # refused → nothing stored, nothing called

        session.append(Turn(role=Role.USER, content=text, trace_id=trace_id))
        # persist the user turn before the LLM call so a crash never loses owner input
        await self.store.save(session)

        messages = self._window_for(session, spec)
        rec = await self._recall(req.user_id, spec, text)
        self._sweep(req.user_id, rec, session.id)
        trailer = self._trailer(session, req) + rec.block
        try:
            completion, pending = await self._run_loop(session, messages, trailer, req, spec)
        except LLMError:
            log.exception("brain: llm failure", extra={"session_id": session.id})
            raise

        rounds = int(session.metadata.pop("_rounds", 0))
        reply = completion.text.strip() or "I have nothing to add, Sir."
        session.append(
            Turn(
                role=Role.ASSISTANT,
                content=reply,
                trace_id=trace_id,
                model=completion.model,
                usage=completion.usage,
                cost_usd=completion.cost_usd,
                latency_ms=completion.latency_ms,
                tool_derived=rounds > 0,  # written from tool results: never to a training brain
            )
        )
        await self.store.save(session)
        self._after_turn(req.user_id, session, spec, rec)
        total_ms = int((time.perf_counter() - t0) * 1000)
        self._log_turn(session, len(messages), spec, completion, total_ms)
        reply_meta = _ReplyMeta(trace_id, total_ms, rounds, pending, list(rec.used))
        return await self._chat_response(session, spec, reply, completion, reply_meta)

    def _trailer(self, session: Session, req: ChatRequest) -> str:
        return build_trailer(
            tz=self.s.user_timezone,
            session_id=session.id,
            turn_index=len(session.turns),
            channel=req.channel,
        )

    @staticmethod
    def _log_turn(
        session: Session, window: int, spec: BrainSpec, completion: Completion, total_ms: int
    ) -> None:
        log.info(
            "brain: turn complete",
            extra={
                "session_id": session.id,
                "turns": len(session.turns),
                "window": window,
                "brain": spec.id,
                "model": completion.model,
                "cost_usd": completion.cost_usd,
                "llm_ms": completion.latency_ms,
                "total_ms": total_ms,
            },
        )

    async def _chat_response(
        self,
        session: Session,
        spec: BrainSpec,
        reply: str,
        completion: Completion,
        meta: _ReplyMeta,
    ) -> ChatResponse:
        cost_inr, total_inr = await self._rupees(completion.cost_usd, session.total_cost_usd)
        return ChatResponse(
            session_id=session.id,
            reply=reply,
            trace_id=meta.trace_id,
            model=completion.model,
            brain=spec.id,
            usage=completion.usage,
            cost_usd=completion.cost_usd,
            cost_inr=cost_inr,
            total_cost_usd=session.total_cost_usd,
            total_cost_inr=total_inr,
            latency_ms=meta.total_ms,
            turn_count=len(session.turns),
            tool_calls=meta.rounds,
            pending_approvals=meta.pending,
            memory_used=meta.memory_used,
        )

    # ---- tool loop ----------------------------------------------------------------------

    async def _complete(
        self,
        messages: list[ChatMessage],
        trailer: str,
        req: ChatRequest,
        spec: BrainSpec,
        *,
        with_tools: bool,
    ) -> Completion:
        """One model call: admitted by the monthly limit first, metered after."""
        give_tools = with_tools and self.gateway is not None and spec.tools_allowed
        await self._admit(req.user_id, spec)
        completion = await self.brains.router_for(spec.id).complete(
            tier=self._tier(req),
            system=await self._persona(req.user_id),
            system_dynamic=trailer,
            messages=messages,
            max_tokens=self.s.max_output_tokens,
            effort=self._effort(),
            tools=self.gateway.registry.specs() if (give_tools and self.gateway) else None,
        )
        await self.billing.record(req.user_id, spec.id, completion.cost_usd)
        return completion

    async def _run_loop(
        self,
        session: Session,
        messages: list[ChatMessage],
        trailer: str,
        req: ChatRequest,
        spec: BrainSpec,
    ) -> tuple[Completion, list[PendingApproval]]:
        """model → tool calls → gateway → results → model, until text or the round cap."""
        pending: list[PendingApproval] = []
        if not self._tools_on(spec):
            return await self._complete(messages, trailer, req, spec, with_tools=False), pending
        assert self.gateway is not None
        rounds = 0
        msgs = list(messages)
        while True:
            completion = await self._complete(msgs, trailer, req, spec, with_tools=True)
            if not completion.tool_calls:
                break
            rounds += 1
            # record the assistant's tool request and our results as block turns
            asst_blocks: list = [TextBlock(text=completion.text)] if completion.text.strip() else []
            asst_blocks += completion.tool_calls
            session.append(
                Turn(
                    role=Role.ASSISTANT,
                    content=completion.text,
                    blocks=asst_blocks,
                    model=completion.model,
                    usage=completion.usage,
                    cost_usd=completion.cost_usd,
                    latency_ms=completion.latency_ms,
                )
            )
            results: list = []
            # what the model had seen when it asked for these calls: other people's text?
            untrusted = untrusted_seen(msgs, self.gateway.registry)
            for call in completion.tool_calls:
                with context_trust(untrusted=untrusted):
                    gr = await self.gateway.execute(call, scope=f"{req.user_id}:{session.id}")
                if gr.outcome is GatewayOutcome.AWAITING_CONFIRMATION and gr.pending:
                    pending.append(PendingApproval.from_action(gr.pending))
                results.append(
                    ToolResultBlock(
                        tool_use_id=call.id,
                        content=gr.for_model(),
                        is_error=gr.outcome is GatewayOutcome.ERROR,
                    )
                )
            session.append(Turn(role=Role.USER, content="", blocks=results))
            await self.store.save(session)
            msgs = msgs + [
                ChatMessage(role=Role.ASSISTANT, content=asst_blocks),
                ChatMessage(role=Role.USER, content=results),
            ]
            if rounds >= self.s.tool_max_rounds:
                log.warning("tool round limit reached", extra={"session_id": session.id})
                msgs = msgs + [
                    ChatMessage(
                        role=Role.USER,
                        content=(
                            "Tool round limit reached. Summarise what you found so far "
                            "and what remains."
                        ),
                    )
                ]
                completion = await self._complete(msgs, trailer, req, spec, with_tools=False)
                break
        session.metadata["_rounds"] = rounds
        return completion, pending

    async def _save_after_action(self, session: Session) -> None:
        """The owner's decision has already taken effect. A storage hiccup must not turn that
        into an error (the owner would ask again and e.g. send twice): log, still answer."""
        try:
            await self.store.save(session)
        except Exception as exc:  # noqa: BLE001
            log.error(
                "SAVE FAILED after an approved action; reply still sent",
                extra={"session_id": session.id, "error": type(exc).__name__},
            )

    # ---- forgetting -----------------------------------------------------------------------

    async def forget(self, session_id: str, *, user_id: str = "owner") -> bool:
        """Owner's delete right: the conversation and its waiting approvals, permanently.
        Waits for any reply still being written, so a delete is never undone by it."""
        async with self._serialised(session_id):
            session = await self.store.get(session_id)
            if session is None or session.user_id != user_id:
                return False
            if self.gateway is not None:
                await self.gateway.gate.cancel_scope(f"{user_id}:{session_id}")
            return await self.store.delete(session_id)

    # ---- approvals ----------------------------------------------------------------------

    async def approve(
        self, approval_id: str, *, session_id: str, user_id: str = "owner"
    ) -> ChatResponse:
        return await self._decide(
            approval_id, approved=True, session_id=session_id, user_id=user_id
        )

    async def decline(
        self, approval_id: str, *, session_id: str, user_id: str = "owner"
    ) -> ChatResponse:
        return await self._decide(
            approval_id, approved=False, session_id=session_id, user_id=user_id
        )

    async def _decide(
        self, approval_id: str, *, approved: bool, session_id: str, user_id: str
    ) -> ChatResponse:
        async with self._serialised(session_id):
            return await self._decide_locked(
                approval_id, approved=approved, session_id=session_id, user_id=user_id
            )

    async def _decide_locked(
        self, approval_id: str, *, approved: bool, session_id: str, user_id: str
    ) -> ChatResponse:
        """Owner decision on a pending R3 action.

        The irreversible step is executed and persisted as a tool exchange BEFORE any model
        call, so a provider outage can never lose the record of what was done; and the
        result reaches the model as a tool_result block, never as an owner instruction. The
        narration is a tool-derived turn: never sent to a brain that may train on content."""
        if self.gateway is None:
            raise SessionNotFound(session_id)
        scope = f"{user_id}:{session_id}"
        action = await self.gateway.gate.get(approval_id)
        if action is None or action.scope != scope:
            raise LookupError(f"no pending approval {approval_id} in this session")
        req = ChatRequest(message="-", session_id=session_id, user_id=user_id)
        session = await self._load_or_create(req)
        call = ToolCall(id=f"approve_{approval_id}", name=action.tool, arguments=action.arguments)
        if approved:
            d = await self._approved(call, action, approval_id, scope)
        else:
            d = await self._declined(call, action, approval_id)
        trace_id = get_trace_id()
        _record_exchange(session, d, trace_id)
        await self._save_after_action(session)
        spec = self._resolve_brain(session, req)
        reply, completion = await self._narrate(session, req, spec, d.fallback)
        session.append(
            Turn(
                role=Role.ASSISTANT,
                content=reply,
                trace_id=trace_id,
                model=completion.model if completion else "none",
                usage=completion.usage if completion else None,
                cost_usd=completion.cost_usd if completion else 0.0,
                tool_derived=True,
            )
        )
        await self._save_after_action(session)
        return await self._decision_response(session, spec, reply, completion, trace_id, approved)

    async def _approved(
        self, call: ToolCall, action: PendingAction, approval_id: str, scope: str
    ) -> _Decision:
        assert self.gateway is not None
        gr = await self.gateway.execute(call, confirmation_id=approval_id, scope=scope)
        if gr.outcome is GatewayOutcome.CONFIRMATION_INVALID:
            # lost a race with another approve/decline: nothing ran, touch nothing
            raise LookupError(f"no pending approval {approval_id} in this session")
        done = gr.outcome is GatewayOutcome.EXECUTED
        fallback = (
            f"Done, Sir: {action.summary}."
            if done
            else f"That did not go through: {gr.error or gr.outcome.value}."
        )
        return _Decision(
            call, gr, fallback, "Owner approved this action; report the outcome in one sentence."
        )

    async def _declined(self, call: ToolCall, action: PendingAction, approval_id: str) -> _Decision:
        assert self.gateway is not None
        if not await self.gateway.gate.cancel(approval_id):
            # approved (or declined) concurrently: never record a decline that didn't happen
            raise LookupError(f"no pending approval {approval_id} in this session")
        tool = self.gateway.registry.get(action.tool)
        await self.gateway.audit.append(
            agent=tool.agent if tool else "gateway",
            tool=action.tool,
            risk=action.risk,
            outcome="declined",
            args=action.arguments,
        )
        return _Decision(
            call,
            GatewayResult(GatewayOutcome.DENIED, error="declined by owner"),
            "Understood, Sir. Nothing was sent or changed.",
            "Owner declined this action; acknowledge in one sentence, nothing was done.",
        )

    async def _narrate(
        self, session: Session, req: ChatRequest, spec: BrainSpec, fallback: str
    ) -> tuple[str, Completion | None]:
        """The model reports the outcome; plainly (deterministic) when it can't or mustn't."""
        messages = self._window_for(session, spec)
        trailer = build_trailer(
            tz=self.s.user_timezone, session_id=session.id, turn_index=len(session.turns)
        )
        try:
            if not spec.tools_allowed:
                # The owner switched to a training brain after this action was proposed. The
                # tool result is private data: narrate deterministically, never send it there.
                raise LLMError("narration skipped: current brain may train on content")
            completion = await self._complete(messages, trailer, req, spec, with_tools=False)
        except (LLMError, BudgetError) as exc:  # the action stands: narrate it plainly
            log.warning(
                "approval narration failed; using deterministic reply",
                extra={"session_id": session.id, "error": str(exc)[:120]},
            )
            return fallback, None
        return completion.text.strip() or fallback, completion

    async def _decision_response(
        self,
        session: Session,
        spec: BrainSpec,
        reply: str,
        completion: Completion | None,
        trace_id: str,
        approved: bool,
    ) -> ChatResponse:
        cost = completion.cost_usd if completion else 0.0
        cost_inr, total_inr = await self._rupees(cost, session.total_cost_usd)
        return ChatResponse(
            session_id=session.id,
            reply=reply,
            trace_id=trace_id,
            model=completion.model if completion else "none",
            brain=spec.id,
            usage=completion.usage if completion else Usage(),
            cost_usd=cost,
            cost_inr=cost_inr,
            total_cost_usd=session.total_cost_usd,
            total_cost_inr=total_inr,
            latency_ms=0,
            turn_count=len(session.turns),
            tool_calls=1 if approved else 0,
            pending_approvals=[],
        )

    async def chat_stream(
        self, req: ChatRequest, *, meta: StreamMeta | None = None
    ) -> AsyncIterator[str]:
        """Streaming variant for the CLI (and Phase 1 TTS). Persists the full reply at the end.
        `meta` (optional) receives the notes sent with the reply before the first delta."""
        req = await self._start(req)
        async with self._serialised(req.session_id):
            inner = self._chat_stream(req, meta or StreamMeta())
            try:
                async for delta in inner:
                    yield delta
            finally:  # a reader that leaves early closes the inner stream now (and its meter)
                await inner.aclose()

    async def _chat_stream(self, req: ChatRequest, meta: StreamMeta) -> AsyncGenerator[str, None]:
        trace_id = get_trace_id()
        if req.brain:
            self.brains.get(req.brain)
        # validate first: a rejected first message must not leave an empty conversation
        text = guard_input(req.message, max_chars=self.s.max_input_chars)
        session = await self._load_or_create(req)
        spec = self._resolve_brain(session, req)
        router = self.brains.router_for(spec.id)
        await self._admit(req.user_id, spec)  # turn-level: refused → nothing stored
        session.append(Turn(role=Role.USER, content=text, trace_id=trace_id))
        await self.store.save(session)

        messages = self._window_for(session, spec)
        rec = await self._recall(req.user_id, spec, text)
        self._sweep(req.user_id, rec, session.id)
        meta.memory_used = list(rec.used)
        trailer = self._trailer(session, req) + rec.block
        system = await self._persona(req.user_id)
        chunks: list[str] = []
        model = router.resolve(self._tier(req))
        # Streams report no usage: estimate tokens from characters so a paid streamed reply is
        # metered (and counts toward the limit) instead of costing "₹0".
        sent = len(system) + len(trailer) + sum(len(m.text()) for m in messages)
        await self._admit(req.user_id, spec)  # call-level, like every other model call
        finished = False
        cost = 0.0
        try:
            async for delta in router.stream(
                tier=self._tier(req),
                system=system,
                system_dynamic=trailer,
                messages=messages,
                max_tokens=self.s.max_output_tokens,
                effort=self._effort(),
            ):
                chunks.append(delta)
                yield delta
            finished = True
        finally:
            # Metered here, once, for a finished stream AND one cut short (client gone, provider
            # error): either way the provider bills what it wrote. `record` is shielded, so the
            # cancellation of a disconnected response can't skip it.
            if finished or chunks:
                cost = priced_cost(model, estimate_usage(sent, len("".join(chunks))))
                await self.billing.record(req.user_id, spec.id, cost)

        reply = Turn(role=Role.ASSISTANT, content="".join(chunks).strip(), trace_id=trace_id)
        await self._finish_turn(req.user_id, session, spec, rec, reply, model=model, cost=cost)
