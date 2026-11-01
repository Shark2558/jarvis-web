# src/jarvis/core/brain.py
"""The core loop (Layer 4): session in → context → LLM → session out.

    load/create session ─► guard input ─► append user turn ─► build window
          ─► router.complete(tier) ─► append assistant turn ─► save ─► ChatResponse

Everything here is vendor-neutral. Phase 2 inserts the tool-calling loop between
`router.complete` and `append assistant turn`; the data model already carries what it needs.
"""

from __future__ import annotations

import asyncio
import contextlib
import time
import weakref
from collections.abc import AsyncIterator

from jarvis.config import Settings
from jarvis.core.guardrails import guard_input
from jarvis.core.models import ChatRequest, ChatResponse, PendingApproval, Session, Turn
from jarvis.core.prompts import PERSONA_VERSION, build_system_prompt, build_trailer
from jarvis.core.window import build_window
from jarvis.llm.base import (
    ChatMessage,
    Completion,
    Effort,
    LLMError,
    Role,
    TextBlock,
    ToolResultBlock,
)
from jarvis.llm.brains import BrainRegistry, BrainSpec
from jarvis.llm.router import ModelRouter, ModelTier
from jarvis.logging import get_logger, get_trace_id
from jarvis.memory.base import SessionNotFound, SessionStore
from jarvis.tools.gateway import Gateway, GatewayOutcome

log = get_logger(__name__)

BRAIN_KEY = "brain"  # session.metadata key remembering the owner's brain choice
CUTOFF_KEY = "brain_cutoff"  # turn index before which history is withheld from training brains


class Brain:
    def __init__(
        self,
        *,
        store: SessionStore,
        settings: Settings,
        router: ModelRouter | None = None,
        brains: BrainRegistry | None = None,
        gateway: Gateway | None = None,
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
        self._system = build_system_prompt(honorific=settings.user_honorific)
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
        never a turn that carries tool blocks (defence in depth for sessions created before
        the cutoff existed or edited by hand)."""
        turns = session.turns
        if not spec.tools_allowed:
            turns = turns[int(session.metadata.get(CUTOFF_KEY, 0)) :]
            turns = [t for t in turns if not t.blocks]
        return build_window(
            turns, max_turns=self.s.session_max_turns, max_chars=self.s.session_max_chars
        )

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

        user_turn = Turn(role=Role.USER, content=text, trace_id=trace_id)
        session.append(user_turn)
        # persist the user turn before the LLM call so a crash never loses owner input
        await self.store.save(session)

        messages = self._window_for(session, spec)
        trailer = build_trailer(
            tz=self.s.user_timezone, session_id=session.id, turn_index=len(session.turns)
        )

        try:
            completion, pending = await self._run_loop(session, messages, trailer, req, spec)
        except LLMError:
            log.exception("brain: llm failure", extra={"session_id": session.id})
            raise

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
            )
        )
        await self.store.save(session)
        rounds = session.metadata.pop("_rounds", 0)

        total_ms = int((time.perf_counter() - t0) * 1000)
        log.info(
            "brain: turn complete",
            extra={
                "session_id": session.id,
                "turns": len(session.turns),
                "window": len(messages),
                "brain": spec.id,
                "model": completion.model,
                "cost_usd": completion.cost_usd,
                "llm_ms": completion.latency_ms,
                "total_ms": total_ms,
            },
        )
        return ChatResponse(
            session_id=session.id,
            reply=reply,
            trace_id=trace_id,
            model=completion.model,
            brain=spec.id,
            usage=completion.usage,
            cost_usd=completion.cost_usd,
            latency_ms=total_ms,
            turn_count=len(session.turns),
            tool_calls=rounds,
            pending_approvals=pending,
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
        give_tools = with_tools and self.gateway is not None and spec.tools_allowed
        return await self.brains.router_for(spec.id).complete(
            tier=self._tier(req),
            system=self._system,
            system_dynamic=trailer,
            messages=messages,
            max_tokens=self.s.max_output_tokens,
            effort=self._effort(),
            tools=self.gateway.registry.specs() if (give_tools and self.gateway) else None,
        )

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
            for call in completion.tool_calls:
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
        result reaches the model as a tool_result block, never as an owner instruction."""
        if self.gateway is None:
            raise SessionNotFound(session_id)
        scope = f"{user_id}:{session_id}"
        action = await self.gateway.gate.get(approval_id)
        if action is None or action.scope != scope:
            raise LookupError(f"no pending approval {approval_id} in this session")
        session = await self._load_or_create(
            ChatRequest(message="-", session_id=session_id, user_id=user_id)
        )
        from jarvis.llm.base import ToolCall

        call = ToolCall(id=f"approve_{approval_id}", name=action.tool, arguments=action.arguments)
        if approved:
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
            instruction = "Owner approved this action; report the outcome in one sentence."
        else:
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
            from jarvis.tools.gateway import GatewayResult

            gr = GatewayResult(GatewayOutcome.DENIED, error="declined by owner")
            fallback = "Understood, Sir. Nothing was sent or changed."
            instruction = (
                "Owner declined this action; acknowledge in one sentence, nothing was done."
            )

        # persist the exchange first (tool_use → tool_result), then ask the model to narrate
        trace_id = get_trace_id()
        session.append(Turn(role=Role.ASSISTANT, content="", blocks=[call], trace_id=trace_id))
        session.append(
            Turn(
                role=Role.USER,
                content="",
                blocks=[
                    ToolResultBlock(
                        tool_use_id=call.id,
                        content=gr.for_model(),
                        is_error=gr.outcome is not GatewayOutcome.EXECUTED,
                    ),
                    TextBlock(text=instruction),
                ],
                trace_id=trace_id,
            )
        )
        await self._save_after_action(session)

        req = ChatRequest(message="-", session_id=session_id, user_id=user_id)
        spec = self._resolve_brain(session, req)
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
            reply = completion.text.strip() or fallback
            usage, cost, model = completion.usage, completion.cost_usd, completion.model
        except LLMError as exc:
            log.warning(
                "approval narration failed; using deterministic reply",
                extra={"session_id": session.id, "error": str(exc)[:120]},
            )
            reply, usage, cost, model = fallback, None, 0.0, "none"
        session.append(
            Turn(
                role=Role.ASSISTANT,
                content=reply,
                trace_id=trace_id,
                model=model,
                usage=usage,
                cost_usd=cost,
            )
        )
        await self._save_after_action(session)
        from jarvis.llm.base import Usage

        return ChatResponse(
            session_id=session.id,
            reply=reply,
            trace_id=trace_id,
            model=model,
            brain=spec.id,
            usage=usage or Usage(),
            cost_usd=cost,
            latency_ms=0,
            turn_count=len(session.turns),
            tool_calls=1 if approved else 0,
            pending_approvals=[],
        )

    async def chat_stream(self, req: ChatRequest) -> AsyncIterator[str]:
        """Streaming variant for the CLI (and Phase 1 TTS). Persists the full reply at the end."""
        req = await self._start(req)
        async with self._serialised(req.session_id):
            async for delta in self._chat_stream(req):
                yield delta

    async def _chat_stream(self, req: ChatRequest) -> AsyncIterator[str]:
        trace_id = get_trace_id()
        if req.brain:
            self.brains.get(req.brain)
        # validate first: a rejected first message must not leave an empty conversation
        text = guard_input(req.message, max_chars=self.s.max_input_chars)
        session = await self._load_or_create(req)
        spec = self._resolve_brain(session, req)
        router = self.brains.router_for(spec.id)
        session.append(Turn(role=Role.USER, content=text, trace_id=trace_id))
        await self.store.save(session)

        messages = self._window_for(session, spec)
        trailer = build_trailer(
            tz=self.s.user_timezone, session_id=session.id, turn_index=len(session.turns)
        )
        chunks: list[str] = []
        async for delta in router.stream(
            tier=self._tier(req),
            system=self._system,
            system_dynamic=trailer,
            messages=messages,
            max_tokens=self.s.max_output_tokens,
            effort=self._effort(),
        ):
            chunks.append(delta)
            yield delta

        reply = "".join(chunks).strip()
        session.append(
            Turn(
                role=Role.ASSISTANT,
                content=reply,
                trace_id=trace_id,
                model=router.resolve(self._tier(req)),
            )
        )
        await self.store.save(session)
