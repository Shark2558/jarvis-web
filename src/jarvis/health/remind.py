# src/jarvis/health/remind.py
"""A reminder for one systems-check concern (R5.1 D8), from the pop-up's "Set a reminder".

No model call: the text is the concern's FIXED label and consequence ("Fix Telegram: alerts and
Telegram chat won't reach you"), the time is one of three fixed choices in the owner's zone, and
`reminder_add` runs through `Gateway.execute` like any other call (policy, audit, approval cards
all apply), owner-trusted: the owner pressed the button, and every word is JARVIS's own.

Scope: `<uid>:<session_id>` when the console sends its open conversation, so a card the owner's
"Ask first" setting raises can be approved in Approvals; with no conversation the scope is
`<uid>:console`, where no card could ever be approved, so such a card is withdrawn at once and
the owner is told to ask in the chat instead. Google not connected -> refused, no call. Gateway
and tool errors are never repeated: every answer line is fixed text.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Literal, Protocol
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import FastAPI
from pydantic import BaseModel, ConfigDict, Field

from jarvis.health.briefing import Concern
from jarvis.llm.base import ToolCall
from jarvis.logging import get_logger
from jarvis.tools.budget import turn_budget
from jarvis.tools.gateway import GatewayOutcome, GatewayResult
from jarvis.tools.taint import context_trust

log = get_logger(__name__)

When = Literal["1h", "evening", "tomorrow"]
Outcome = Literal["executed", "awaiting_confirmation", "refused"]
TOOL = "reminder_add"
CONSOLE_SESSION = "console"
DEFAULT_TZ = "Asia/Kolkata"
TEXT_MAX = 200  # reminder_add's own limit
EVENING_HOUR, TOMORROW_HOUR = 18, 10
KEY_PATTERN = r"^[a-z0-9][a-z0-9._-]{0,63}$"
SESSION_PATTERN = r"^[A-Za-z0-9_-]{1,64}$"

CONNECT_GOOGLE = "Connect Google first, Sir."
GOOGLE_UNREADABLE = "Google can't be checked just now, Sir. Try again in a moment."
UNAVAILABLE = "Reminders aren't available right now, Sir."
NEEDS_OK = "Approve it in Approvals, Sir."
ASK_IN_CHAT = "Reminders ask first in your settings, Sir. Ask me in the chat and I'll set it."
DENIED = "That isn't allowed right now, Sir."
FAILED = "That reminder couldn't be set, Sir."


class RemindBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str = Field(min_length=1, max_length=64, pattern=KEY_PATTERN)
    when: When
    session_id: str | None = Field(default=None, pattern=SESSION_PATTERN)


class GatewayLike(Protocol):
    async def execute(self, call: ToolCall, *, scope: str | None = None) -> GatewayResult: ...

    @property
    def gate(self) -> Any: ...  # `.cancel(approval_id)`


class GoogleStatus(Protocol):
    async def status(self, uid: str) -> Mapping[str, Any]: ...


@dataclass(frozen=True)
class RemindDeps:
    gateway: GatewayLike | None
    google: GoogleStatus | None
    tz: str = DEFAULT_TZ
    now: Callable[[], datetime] | None = field(default=None)


@dataclass(frozen=True)
class Answer:
    outcome: Outcome
    line: str

    def to_json(self) -> dict[str, str]:
        return {"outcome": self.outcome, "line": self.line}


def deps_from_app(app: FastAPI) -> RemindDeps:
    """The live gateway, Google connector and owner zone on `app.state` (None when absent)."""
    st = app.state
    settings = getattr(st, "settings", None)
    tz = getattr(settings, "user_timezone", DEFAULT_TZ) or DEFAULT_TZ
    return RemindDeps(
        gateway=getattr(st, "gateway", None), google=getattr(st, "google", None), tz=str(tz)
    )


def _zone(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        return ZoneInfo(DEFAULT_TZ)


def when_at(choice: When, now: datetime) -> tuple[datetime, str]:
    """The reminder's time (in `now`'s zone, to the minute) and how the owner is told it."""
    today = now.date()
    if choice == "1h":
        at = (now + timedelta(hours=1)).replace(second=0, microsecond=0)
    elif choice == "evening":
        at = now.replace(hour=EVENING_HOUR, minute=0, second=0, microsecond=0)
        if at <= now:
            at += timedelta(days=1)
    else:
        at = (now + timedelta(days=1)).replace(
            hour=TOMORROW_HOUR, minute=0, second=0, microsecond=0
        )
    later = at.date() != today
    if choice == "evening":
        day = "tomorrow evening" if later else "this evening"
    else:
        day = "tomorrow" if later else "today"
    return at, f"{day}, {at:%H:%M}"


def reminder_text(concern: Concern) -> str:
    return f"Fix {concern.label}: {concern.impact}"[:TEXT_MAX]


async def _google_ready(google: GoogleStatus | None, uid: str) -> Answer | None:
    """None when Google is connected; else the refusal to answer with."""
    if google is None:
        return Answer("refused", CONNECT_GOOGLE)
    try:
        st = await google.status(uid)
    except Exception as exc:  # noqa: BLE001 - unreadable: say so, never the reason
        log.warning("health remind: google status unreadable", extra={"error": type(exc).__name__})
        return Answer("refused", GOOGLE_UNREADABLE)
    return None if st.get("connected") else Answer("refused", CONNECT_GOOGLE)


def _stopped(result: Any) -> bool:
    return isinstance(result, dict) and bool(result.get("refused") or result.get("unavailable"))


async def set_reminder(
    deps: RemindDeps, uid: str, concern: Concern, choice: When, *, session_id: str | None
) -> Answer:
    if (refused := await _google_ready(deps.google, uid)) is not None:
        return refused
    gateway = deps.gateway
    if gateway is None:
        return Answer("refused", UNAVAILABLE)
    tz = _zone(deps.tz)
    now = deps.now() if deps.now is not None else datetime.now(tz)
    at, said = when_at(choice, now.astimezone(tz))
    call = ToolCall(
        id=f"health-{uuid.uuid4().hex[:8]}",
        name=TOOL,
        arguments={"text": reminder_text(concern), "when": at.isoformat()},
    )
    scope = f"{uid}:{session_id or CONSOLE_SESSION}"
    with turn_budget(), context_trust(untrusted=False, spoken=False, owner_text=None):
        res = await gateway.execute(call, scope=scope)
    return await _answer(gateway, res, said, conversation=session_id is not None)


async def _answer(
    gateway: GatewayLike, res: GatewayResult, said: str, *, conversation: bool
) -> Answer:
    if res.outcome is GatewayOutcome.EXECUTED:
        if _stopped(res.result):
            return Answer("refused", FAILED)
        return Answer("executed", f"Reminder set for {said}.")
    if res.outcome is GatewayOutcome.AWAITING_CONFIRMATION:
        if conversation:
            return Answer("awaiting_confirmation", NEEDS_OK)
        if res.pending is not None:  # no conversation to approve it in: withdraw the card
            try:
                await gateway.gate.cancel(res.pending.id)
            except Exception as exc:  # noqa: BLE001 - it expires on its own
                log.warning(
                    "health remind: card not withdrawn", extra={"error": type(exc).__name__}
                )
        return Answer("refused", ASK_IN_CHAT)
    if res.outcome is GatewayOutcome.DENIED:
        return Answer("refused", DENIED)
    log.warning("health remind: reminder not set", extra={"outcome": res.outcome.value})
    return Answer("refused", FAILED)


__all__ = [
    "CONSOLE_SESSION",
    "Answer",
    "RemindBody",
    "RemindDeps",
    "deps_from_app",
    "reminder_text",
    "set_reminder",
    "when_at",
]
