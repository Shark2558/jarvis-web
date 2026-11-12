# src/jarvis/offline/no_ai.py
"""Run a no-AI command (R4 D7): the tool calls `offline.rules.route_no_ai` chose go through the
gateway like any other call (policy, audit, cards, R3 tokens all apply), and the reply is built
from fixed templates, never by a model. Results are shown to the owner as data; nothing here
interprets them as instructions.
"""

from __future__ import annotations

import json
import time
import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from jarvis.config import Settings
from jarvis.core.models import ChatRequest, ChatResponse, PendingApproval, Session, Turn
from jarvis.core.rounds import Rounds
from jarvis.documents.service import DocumentService, save_owner_turn
from jarvis.llm.base import Role, ToolCall, Usage
from jarvis.llm.brains import BrainSpec
from jarvis.logging import get_trace_id
from jarvis.memory.base import SessionStore
from jarvis.offline.mode import BrainMode
from jarvis.offline.rules import NoAIRoute, NoAIRouter, route_no_ai
from jarvis.people.guard import REFUSAL_LINES
from jarvis.tools.budget import turn_budget
from jarvis.tools.gateway import Gateway, GatewayOutcome, GatewayResult
from jarvis.tools.reply_cards import AnyCard, collecting_cards
from jarvis.tools.taint import context_trust

UNAVAILABLE = "That isn't available right now, Sir."
NEEDS_OK = "That needs your OK, Sir. The approval is waiting on your screen."
DENIED = "That isn't allowed right now, Sir."
DONE = "Done, Sir."
SUMMARY_KEYS = ("spoken", "summary", "message", "reply")
RENDER_LIMIT = 800
OPEN_KEY = "open"


@dataclass(frozen=True)
class NoAIResult:
    reply: str
    tool_calls: int = 0
    pending: list[PendingApproval] = field(default_factory=list)
    cards: list[AnyCard] = field(default_factory=list)
    calls: tuple[ToolCall, ...] = ()
    results: tuple[GatewayResult, ...] = ()


def _compact(value: Any) -> str:
    text = json.dumps(value, ensure_ascii=False, default=str)
    return text if len(text) <= RENDER_LIMIT else text[:RENDER_LIMIT] + "…"


def _render(result: Any) -> str:
    """A fixed-template line for one tool result."""
    if isinstance(result, dict):
        if isinstance(result.get(OPEN_KEY), list) and result[OPEN_KEY]:
            return "\n".join([str(result.get("message", DONE)), *map(str, result[OPEN_KEY])])
        for key in SUMMARY_KEYS:
            value = result.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        return _compact(result) if result else DONE
    if result in (None, "", [], {}):
        return DONE
    return _compact(result)


def _line(res: GatewayResult) -> str:
    """One fixed line per outcome. Gateway error text is never repeated, except our own fixed
    refusal lines (the scope guard's words), which are matched exactly."""
    if res.outcome is GatewayOutcome.EXECUTED:
        return _render(res.result)
    if res.outcome is GatewayOutcome.AWAITING_CONFIRMATION:
        return NEEDS_OK
    if res.error in REFUSAL_LINES:
        return str(res.error)
    if res.outcome is GatewayOutcome.DENIED:
        return DENIED
    return UNAVAILABLE


def _stopped(result: Any) -> bool:
    """A tool that ran but declined (`refused`) or could not (`unavailable`): nothing follows."""
    return isinstance(result, dict) and bool(result.get("refused") or result.get("unavailable"))


def _unavailable(res: GatewayResult) -> bool:
    return res.outcome is GatewayOutcome.ERROR and (res.error or "").startswith("unknown tool")


async def run_no_ai(
    gateway: Gateway | None,
    text: str,
    now: datetime,
    *,
    scope: str,
    spoken: bool = False,
    extra: Sequence[NoAIRouter] = (),
) -> NoAIResult:
    """Answer `text` with no model: route by pattern (R11: the helpers' phrases first), run the
    calls, join the lines."""
    route: NoAIRoute = route_no_ai(text, now, extra)
    if not route.calls:
        return NoAIResult(route.reply)
    if gateway is None:
        return NoAIResult(UNAVAILABLE)
    cards: list[AnyCard] = []
    lines: list[str] = []
    pending: list[PendingApproval] = []
    ran: list[ToolCall] = []
    results: list[GatewayResult] = []
    with turn_budget(), collecting_cards(cards):
        for call in route.calls:
            tool_call = ToolCall(
                id=f"noai-{uuid.uuid4().hex[:8]}", name=call.tool, arguments=call.arguments
            )
            with context_trust(untrusted=False, spoken=spoken, owner_text=text):
                res = await gateway.execute(tool_call, scope=scope)
            ran.append(tool_call)
            results.append(res)
            lines.append(UNAVAILABLE if _unavailable(res) else _line(res))
            if res.outcome is GatewayOutcome.AWAITING_CONFIRMATION and res.pending:
                pending.append(PendingApproval.from_action(res.pending))
            if res.outcome is not GatewayOutcome.EXECUTED or _stopped(res.result):
                break  # a refused or waiting step ends the chain (no URLs after a refusal)
    return NoAIResult("\n".join(lines), len(ran), pending, cards, tuple(ran), tuple(results))


NO_AI_MODEL = "no-ai"


def _owner_now(s: Settings) -> datetime:
    try:
        tz = ZoneInfo(s.user_timezone)
    except (ZoneInfoNotFoundError, ValueError):
        tz = ZoneInfo("UTC")
    return datetime.now(tz)


class NoAIRunner:
    """No-AI mode for `Brain` (R4 D7): whether it is on, and one whole owner turn without a model.
    No billing, no memory recall, no provider call; the owner's message and the reply are stored
    like any turn (documents bound, conflict-safe once a write has run)."""

    def __init__(
        self,
        *,
        store: SessionStore,
        settings: Settings,
        gateway: Gateway | None,
        mode: BrainMode,
        documents: DocumentService | None = None,
    ) -> None:
        self._store, self._s, self._gw = store, settings, gateway
        self.mode, self._documents = mode, documents

    @property
    def active(self) -> bool:
        return self.mode.current == "none"

    async def refresh(self, user_id: str) -> bool:
        """Re-read the persisted switch (cached a few seconds), then say whether no-AI is on."""
        await self.mode.load(user_id)
        return self.active

    async def reply(
        self, session: Session, req: ChatRequest, text: str, spec: BrainSpec, started: float
    ) -> ChatResponse:
        trace_id = get_trace_id() or ""
        turn = Turn(role=Role.USER, content=text, trace_id=trace_id, channel=req.channel)
        await save_owner_turn(self._documents, self._store, session, turn, req, spec)
        out = await run_no_ai(
            self._gw if self._s.tools_enabled else None,
            text,
            _owner_now(self._s),
            scope=f"{req.user_id}:{session.id}",
            spoken=req.channel == "voice",
            extra=self.mode.phrases,  # R11 D18
        )
        rounds = Rounds(session=session, cards=list(out.cards))
        if self._gw is not None:
            rounds.note(self._gw.registry, out.calls, out.results)
        answer = Turn(
            role=Role.ASSISTANT, content=out.reply, trace_id=trace_id, model=NO_AI_MODEL,
            usage=Usage(), tool_derived=out.tool_calls > 0,
        )  # fmt: skip
        rounds.session.append(answer)
        stored = await rounds.store(self._store, [answer])
        session = rounds.session
        return ChatResponse(
            session_id=session.id,
            reply=out.reply + rounds.reply_note(stored),
            trace_id=trace_id,
            model=NO_AI_MODEL,
            brain=spec.id,
            usage=Usage(),
            cost_usd=0.0,
            latency_ms=int((time.perf_counter() - started) * 1000),
            turn_count=len(session.turns),
            tool_calls=out.tool_calls,
            pending_approvals=out.pending,
            undo=rounds.undo,
            cards=out.cards,
        )


__all__ = [
    "NEEDS_OK",
    "NO_AI_MODEL",
    "UNAVAILABLE",
    "NoAIResult",
    "NoAIRunner",
    "run_no_ai",
]
