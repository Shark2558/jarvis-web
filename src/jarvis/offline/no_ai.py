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
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from jarvis.config import Settings
from jarvis.core.models import ChatRequest, ChatResponse, PendingApproval, Session, Turn
from jarvis.llm.base import Role, ToolCall, Usage
from jarvis.memory.base import SessionStore
from jarvis.offline.rules import NoAIRoute, route_no_ai
from jarvis.tools.budget import turn_budget
from jarvis.tools.gateway import Gateway, GatewayOutcome, GatewayResult
from jarvis.tools.reply_cards import AnyCard, collecting_cards
from jarvis.tools.taint import context_trust

UNAVAILABLE = "That isn't available right now, Sir."
NEEDS_OK = "That needs your OK, Sir. The card is waiting."
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
    if res.outcome is GatewayOutcome.EXECUTED:
        return _render(res.result)
    if res.outcome is GatewayOutcome.AWAITING_CONFIRMATION:
        return NEEDS_OK
    return (res.error or UNAVAILABLE).replace("unknown tool:", "").strip() or UNAVAILABLE


def _unavailable(res: GatewayResult) -> bool:
    return res.outcome is GatewayOutcome.ERROR and (res.error or "").startswith("unknown tool")


async def run_no_ai(
    gateway: Gateway | None,
    text: str,
    now: datetime,
    *,
    scope: str,
    spoken: bool = False,
) -> NoAIResult:
    """Answer `text` with no model: route by pattern, run the calls, join the lines."""
    route: NoAIRoute = route_no_ai(text, now)
    if not route.calls:
        return NoAIResult(route.reply)
    if gateway is None:
        return NoAIResult(UNAVAILABLE)
    cards: list[AnyCard] = []
    lines: list[str] = []
    pending: list[PendingApproval] = []
    ran = 0
    with turn_budget(), collecting_cards(cards):
        for call in route.calls:
            with context_trust(untrusted=False, spoken=spoken, owner_text=text):
                res = await gateway.execute(
                    ToolCall(
                        id=f"noai-{uuid.uuid4().hex[:8]}", name=call.tool, arguments=call.arguments
                    ),
                    scope=scope,
                )
            ran += 1
            lines.append(UNAVAILABLE if _unavailable(res) else _line(res))
            if res.outcome is GatewayOutcome.AWAITING_CONFIRMATION and res.pending:
                pending.append(PendingApproval.from_action(res.pending))
            if res.outcome is not GatewayOutcome.EXECUTED:
                break  # a refused or waiting step ends the chain (no URLs after a refusal)
    return NoAIResult("\n".join(lines), ran, pending, cards)


NO_AI_MODEL = "no-ai"


def _owner_now(s: Settings) -> datetime:
    try:
        tz = ZoneInfo(s.user_timezone)
    except (ZoneInfoNotFoundError, ValueError):
        tz = ZoneInfo("UTC")
    return datetime.now(tz)


async def no_ai_turn(
    *,
    store: SessionStore,
    settings: Settings,
    gateway: Gateway | None,
    session: Session,
    req: ChatRequest,
    text: str,
    brain_id: str,
    trace_id: str,
    started: float,
) -> ChatResponse:
    """One whole owner turn with no model: store the message, run the routed tools, store and
    return the fixed-template reply. No billing, no memory recall, no provider."""
    session.append(Turn(role=Role.USER, content=text, trace_id=trace_id, channel=req.channel))
    await store.save(session)
    out = await run_no_ai(
        gateway,
        text,
        _owner_now(settings),
        scope=f"{req.user_id}:{session.id}",
        spoken=req.channel == "voice",
    )
    session.append(
        Turn(
            role=Role.ASSISTANT,
            content=out.reply,
            trace_id=trace_id,
            model=NO_AI_MODEL,
            usage=Usage(),
            tool_derived=out.tool_calls > 0,
        )
    )
    await store.save(session)
    return ChatResponse(
        session_id=session.id,
        reply=out.reply,
        trace_id=trace_id,
        model=NO_AI_MODEL,
        brain=brain_id,
        usage=Usage(),
        cost_usd=0.0,
        latency_ms=int((time.perf_counter() - started) * 1000),
        turn_count=len(session.turns),
        tool_calls=out.tool_calls,
        pending_approvals=out.pending,
        cards=out.cards,
    )


__all__ = ["NEEDS_OK", "NO_AI_MODEL", "UNAVAILABLE", "NoAIResult", "no_ai_turn", "run_no_ai"]
