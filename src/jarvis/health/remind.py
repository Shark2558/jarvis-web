# src/jarvis/health/remind.py
"""A reminder for one systems-check concern (R5.1 D8), from the pop-up's "Set a reminder".

No model call: the text is the concern's FIXED label and consequence ("Fix Telegram: alerts and
Telegram chat won't reach you"), the time is one of three fixed choices in the owner's zone, and
`reminder_add` runs through `Gateway.execute` like any other call (policy, audit, approval cards
all apply), owner-trusted: the owner pressed the button, and every word is JARVIS's own.

Trust (R5.1 review M2): the words are JARVIS's own only where the code fixed them: the seven probe
keys, and the automatic Vitals items listed in `VITALS_WORDS` (by id; a quota or allowance by its
prefix). A Vitals item the owner typed (or a model typed for them) carries a free-text label, so
its call runs in an UNTRUSTED context and the gateway asks for approval; it is never stored as the
owner's own words.

Scope: `<uid>:<session_id>` when the console sends a conversation the owner really has (looked up
in the session store), so a card the owner's "Ask first" setting raises can be approved in
Approvals; with no conversation, the literal `console`, someone else's id or no way to look it
up, the scope is `<uid>:console`, where no card could ever be approved, so such a card is
withdrawn at once and the owner is told to ask in the chat instead. The same reminder (owner, key,
time choice) asked again inside ten minutes answers "Already set" with no second call. Google not
connected -> refused, no call. Gateway and tool errors are never repeated: every answer line is
fixed text.
"""

from __future__ import annotations

import time
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
ALREADY = "Already set, Sir."
DEDUP_S = 600.0
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


class SessionLookup(Protocol):
    """The session store's `get`: the stored conversation (with `.user_id`) or None."""

    async def get(self, session_id: str) -> Any: ...


class GoogleStatus(Protocol):
    async def status(self, uid: str) -> Mapping[str, Any]: ...


@dataclass(frozen=True)
class RemindDeps:
    gateway: GatewayLike | None
    google: GoogleStatus | None
    tz: str = DEFAULT_TZ
    now: Callable[[], datetime] | None = field(default=None)
    sessions: SessionLookup | None = None


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
        gateway=getattr(st, "gateway", None),
        google=getattr(st, "google", None),
        tz=str(tz),
        sessions=getattr(st, "store", None),
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


# The automatic Vitals items, by id: (what the reminder calls it, what stops). Code-side words.
VITALS_WORDS: Mapping[str, tuple[str, str]] = {
    "brain_claude": ("the paid AI brain", "paid AI replies stop"),
    "brain_gemini": ("the free AI brain", "the free AI brain stops answering"),
    "google_link": ("the Google link", "Gmail, Calendar, Drive and Photos stop working"),
    "telegram_bot": ("the Telegram bot", "alerts and Telegram chat won't reach you"),
    "web_credits": ("the web search credits", "web search stops until they reset"),
    "github_token": ("the GitHub token", "JARVIS can't read your GitHub"),
    "home_link": ("the home link", "the home camera, devices and alarm can't reach JARVIS"),
    "ai_spend": ("the AI spend limit", "paid replies pause"),
}
VITALS_PREFIXES: Mapping[str, tuple[str, str]] = {
    "quota_": ("a Vitals quota", "that feature stops until it resets"),
    "allowance_": ("a free allowance", "voice costs rupees once it runs out"),
}
VITALS_KEY = "vitals."


def _fixed_vitals(pid: str) -> tuple[str, str] | None:
    if pid in VITALS_WORDS:
        return VITALS_WORDS[pid]
    return next((w for p, w in VITALS_PREFIXES.items() if pid.startswith(p)), None)


def reminder_text(concern: Concern) -> str:
    """The reminder's words: fixed ones for an automatic Vitals item (never its label)."""
    if concern.key.startswith(VITALS_KEY):
        fixed = _fixed_vitals(concern.key[len(VITALS_KEY) :])
        if fixed is not None:
            return f"Fix {fixed[0]}: {fixed[1]}"[:TEXT_MAX]
    return f"Fix {concern.label}: {concern.impact}"[:TEXT_MAX]


def is_fixed_words(concern: Concern) -> bool:
    """True when every word of the reminder is JARVIS's own (a probe, or an automatic item)."""
    if not concern.key.startswith(VITALS_KEY):
        return True
    return _fixed_vitals(concern.key[len(VITALS_KEY) :]) is not None


class RemindMemo:
    """Which (owner, key, time choice) reminders were set in the last ten minutes. In memory:
    a repeat click or request never makes a second reminder."""

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._at: dict[tuple[str, str, str], float] = {}

    def claim(self, uid: str, key: str, when: str) -> bool:
        """True when this is new (now taken); False when claimed under ten minutes ago."""
        now = self._clock()
        self._at = {k: t for k, t in self._at.items() if now - t < DEDUP_S}
        if (uid, key, when) in self._at:
            return False
        self._at[(uid, key, when)] = now
        return True

    def release(self, uid: str, key: str, when: str) -> None:
        self._at.pop((uid, key, when), None)


async def _own_session(deps: RemindDeps, uid: str, session_id: str | None) -> str | None:
    """The id when it is one of this owner's conversations; else None (no conversation)."""
    if session_id is None or session_id == CONSOLE_SESSION or deps.sessions is None:
        return None
    try:
        found = await deps.sessions.get(session_id)
    except Exception as exc:  # noqa: BLE001 - unreadable: treat as no conversation
        log.warning("health remind: session unreadable", extra={"error": type(exc).__name__})
        return None
    return session_id if found is not None and getattr(found, "user_id", None) == uid else None


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
    deps: RemindDeps,
    uid: str,
    concern: Concern,
    choice: When,
    *,
    session_id: str | None,
    memo: RemindMemo | None = None,
) -> Answer:
    if memo is not None and not memo.claim(uid, concern.key, choice):
        return Answer("executed", ALREADY)
    answer = await _set(deps, uid, concern, choice, session_id=session_id)
    if memo is not None and answer.outcome == "refused":
        memo.release(uid, concern.key, choice)  # nothing was set: it may be tried again
    return answer


async def _set(
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
    session = await _own_session(deps, uid, session_id)
    scope = f"{uid}:{session or CONSOLE_SESSION}"
    untrusted = not is_fixed_words(concern)  # free text in the label: the gateway must ask
    with turn_budget(), context_trust(untrusted=untrusted, spoken=False, owner_text=None):
        res = await gateway.execute(call, scope=scope)
    return await _answer(gateway, res, said, conversation=session is not None)


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
    "RemindMemo",
    "deps_from_app",
    "reminder_text",
    "set_reminder",
    "when_at",
]
