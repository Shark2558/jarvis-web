# src/jarvis/core/brain.py
"""The core loop (Layer 4): session in → context → LLM → session out.

    load/create session ─► guard input ─► append user turn ─► build window
          ─► router.complete(tier) ─► append assistant turn ─► save ─► ChatResponse

Everything here is vendor-neutral. Phase 2 inserts the tool-calling loop between
`router.complete` and `append assistant turn`; the data model already carries what it needs.
"""

from __future__ import annotations

import time
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
from jarvis.llm.router import ModelRouter, ModelTier
from jarvis.logging import get_logger, get_trace_id
from jarvis.memory.base import SessionNotFound, SessionStore
from jarvis.tools.gateway import Gateway, GatewayOutcome

log = get_logger(__name__)


class Brain:
    def __init__(
        self,
        *,
        router: ModelRouter,
        store: SessionStore,
        settings: Settings,
        gateway: Gateway | None = None,
    ) -> None:
        self.router = router
        self.store = store
        self.s = settings
        self.gateway = gateway
        self._system = build_system_prompt(honorific=settings.user_honorific)

    @property
    def _tools_on(self) -> bool:
        return bool(self.gateway and self.s.tools_enabled and len(self.gateway.registry))

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

    async def chat(self, req: ChatRequest) -> ChatResponse:
        t0 = time.perf_counter()
        trace_id = get_trace_id()
        session = await self._load_or_create(req)

        text = guard_input(req.message, max_chars=self.s.max_input_chars)
        user_turn = Turn(role=Role.USER, content=text, trace_id=trace_id)
        session.append(user_turn)
        # persist the user turn before the LLM call so a crash never loses owner input
        await self.store.save(session)

        messages = build_window(
            session.turns, max_turns=self.s.session_max_turns, max_chars=self.s.session_max_chars
        )
        trailer = build_trailer(
            tz=self.s.user_timezone, session_id=session.id, turn_index=len(session.turns)
        )

        try:
            completion, pending = await self._run_loop(session, messages, trailer, req)
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
            usage=completion.usage,
            cost_usd=completion.cost_usd,
            latency_ms=total_ms,
            turn_count=len(session.turns),
            tool_calls=rounds,
            pending_approvals=pending,
        )

    # ---- tool loop ----------------------------------------------------------------------

    async def _complete(
        self, messages: list[ChatMessage], trailer: str, req: ChatRequest, *, with_tools: bool
    ) -> Completion:
        return await self.router.complete(
            tier=self._tier(req),
            system=self._system,
            system_dynamic=trailer,
            messages=messages,
            max_tokens=self.s.max_output_tokens,
            effort=self._effort(),
            tools=self.gateway.registry.specs() if (with_tools and self.gateway) else None,
        )

    async def _run_loop(
        self, session: Session, messages: list[ChatMessage], trailer: str, req: ChatRequest
    ) -> tuple[Completion, list[PendingApproval]]:
        """model → tool calls → gateway → results → model, until text or the round cap."""
        pending: list[PendingApproval] = []
        if not self._tools_on:
            return await self._complete(messages, trailer, req, with_tools=False), pending
        assert self.gateway is not None
        rounds = 0
        msgs = list(messages)
        while True:
            completion = await self._complete(msgs, trailer, req, with_tools=True)
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
                    pending.append(
                        PendingApproval(
                            id=gr.pending.id,
                            tool=gr.pending.tool,
                            summary=gr.pending.summary,
                            arguments=gr.pending.arguments,
                            risk=gr.pending.risk.value,
                            expires_at=gr.pending.expires_at,
                        )
                    )
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
                completion = await self._complete(msgs, trailer, req, with_tools=False)
                break
        session.metadata["_rounds"] = rounds
        return completion, pending

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
        """Owner decision on a pending R3 action.

        The irreversible step is executed and persisted as a tool exchange BEFORE any model
        call, so a provider outage can never lose the record of what was done; and the
        result reaches the model as a tool_result block, never as an owner instruction."""
        if self.gateway is None:
            raise SessionNotFound(session_id)
        scope = f"{user_id}:{session_id}"
        action = next(
            (a for a in self.gateway.pending() if a.id == approval_id and a.scope == scope), None
        )
        if action is None:
            raise LookupError(f"no pending approval {approval_id} in this session")
        session = await self._load_or_create(
            ChatRequest(message="-", session_id=session_id, user_id=user_id)
        )
        from jarvis.llm.base import ToolCall

        call = ToolCall(id=f"approve_{approval_id}", name=action.tool, arguments=action.arguments)
        if approved:
            gr = await self.gateway.execute(call, confirmation_id=approval_id, scope=scope)
            done = gr.outcome is GatewayOutcome.EXECUTED
            fallback = (
                f"Done, Sir: {action.summary}."
                if done
                else f"That did not go through: {gr.error or gr.outcome.value}."
            )
            instruction = "Owner approved this action; report the outcome in one sentence."
        else:
            self.gateway.gate.cancel(approval_id)
            tool = self.gateway.registry.get(action.tool)
            self.gateway.audit.append(
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
        await self.store.save(session)

        req = ChatRequest(message="-", session_id=session_id, user_id=user_id)
        messages = build_window(
            session.turns, max_turns=self.s.session_max_turns, max_chars=self.s.session_max_chars
        )
        trailer = build_trailer(
            tz=self.s.user_timezone, session_id=session.id, turn_index=len(session.turns)
        )
        try:
            completion = await self._complete(messages, trailer, req, with_tools=False)
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
        await self.store.save(session)
        from jarvis.llm.base import Usage

        return ChatResponse(
            session_id=session.id,
            reply=reply,
            trace_id=trace_id,
            model=model,
            usage=usage or Usage(),
            cost_usd=cost,
            latency_ms=0,
            turn_count=len(session.turns),
            tool_calls=1 if approved else 0,
            pending_approvals=[],
        )

    async def chat_stream(self, req: ChatRequest) -> AsyncIterator[str]:
        """Streaming variant for the CLI (and Phase 1 TTS). Persists the full reply at the end."""
        trace_id = get_trace_id()
        session = await self._load_or_create(req)
        text = guard_input(req.message, max_chars=self.s.max_input_chars)
        session.append(Turn(role=Role.USER, content=text, trace_id=trace_id))
        await self.store.save(session)

        messages = build_window(
            session.turns, max_turns=self.s.session_max_turns, max_chars=self.s.session_max_chars
        )
        trailer = build_trailer(
            tz=self.s.user_timezone, session_id=session.id, turn_index=len(session.turns)
        )
        chunks: list[str] = []
        async for delta in self.router.stream(
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
                model=self.router.resolve(self._tier(req)),
            )
        )
        await self.store.save(session)
