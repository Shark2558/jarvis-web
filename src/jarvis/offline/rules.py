# src/jarvis/offline/rules.py
"""Writes made in an offline turn always ask (R1 D11 b).

A small model on the laptop picks arguments less reliably and is easier to steer with injected
text, so while `core.channel.answered_offline()` every reversible (R2) call becomes a one-tap card,
whatever the owner's Allow says. Reads are untouched, and R3 already asks and can never be relaxed.
Wraps the gateway's `OwnerRules` source (I1 builds the chain
`wrap_offline(wrap_rules(permissions, ...))`; OfflineRules goes OUTERMOST); no gateway change.

`WRITES_ASK` exists only so the offline eval can show its negative control.

R4 D7 (no-AI mode, pass 1): `route_no_ai` below maps a command to tool calls by fixed patterns, with
no model anywhere. Skills that must generate text (and anything it does not recognise) get the
fixed line `NO_AI_LINE`. `core.brain` runs the calls through the gateway (`offline.no_ai`).
"""

from __future__ import annotations

import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta

from jarvis.core.channel import answered_offline
from jarvis.core.guardrails import ActionRisk
from jarvis.tools.policy import Effect, OwnerRules, PolicyRule

WRITES_ASK = True

OFFLINE_ASK = PolicyRule(
    tool_pattern="*",
    effect=Effect.ASK,
    risks=[ActionRisk.REVERSIBLE],
    source="offline",
    reason="Offline mode: JARVIS is running on your laptop, so every change waits for you.",
)


class OfflineRules:
    """An `OwnerRules` that adds the offline ASK rule to the wrapped source's rules."""

    def __init__(self, inner: OwnerRules) -> None:
        self._inner = inner

    async def rules_for(self, user_id: str) -> list[PolicyRule]:
        rules = await self._inner.rules_for(user_id)  # may raise: the gateway fails closed
        if WRITES_ASK and answered_offline():
            return [*rules, OFFLINE_ASK.model_copy()]
        return rules


def wrap_offline(inner: OwnerRules) -> OfflineRules:
    """Wrap the finished rules chain so offline turns ask on every write.

    It must be the OUTERMOST wrapper, around telegram's `wrap_rules(...)`:
    `rules = wrap_offline(wrap_rules(permission_rules, ...))`. A channel wrapper keeps only the
    rule sources it knows, so an offline rule placed inside it is dropped and an offline calendar
    add would run without a card (tests/test_offline_chain.py).
    """
    return OfflineRules(inner)


# ---- R4 D7: no-AI routing ---------------------------------------------------------------------

NO_AI_LINE = "That needs the AI switched on, Sir."
NEEDS_TIME_LINE = "When should I remind you, Sir? Say it with a time, such as 'in 30 minutes'."
NEEDS_QUERY_LINE = "What should I look for in your notes, Sir? Try 'search my notes for plumber'."
TIMER_TEXT = "Timer"
WEEK_DAYS = 7
_SECONDS = {"s": 1, "m": 60, "h": 3600}


@dataclass(frozen=True)
class NoAICall:
    tool: str
    arguments: dict[str, str]


@dataclass(frozen=True)
class NoAIRoute:
    """Tool calls to run, in order; or, when there are none, the fixed line to answer with."""

    calls: tuple[NoAICall, ...] = ()
    reply: str = NO_AI_LINE


def _one(tool: str, **args: str) -> NoAIRoute:
    return NoAIRoute((NoAICall(tool, dict(args)),))


_I = re.IGNORECASE
_NOTE_ADD = re.compile(
    r"\b(?:take|add|make|save|jot(?:\s+down)?|note\s+down)\s+(?:a\s+)?note\b\s*[:,-]?\s*(.*)$",
    _I | re.S,
)
_NOTE_SEARCH = re.compile(
    r"\b(?:search|find|look\s+up|show|read)\s+(?:in\s+)?(?:my\s+)?notes?\b(?:\s+(?:for|about|on))?\s*(.*)$",
    _I,
)
_UNIT = r"(sec(?:ond)?|min(?:ute)?|h(?:ou)?r)s?"
_TIMER = re.compile(rf"\btimer\b.*?(\d+)\s*{_UNIT}\b", _I)
_ANY_DURATION = re.compile(rf"\d+\s*{_UNIT}\b", _I)
_REMIND = re.compile(r"\bremind\s+me\b\s*(?:to\s+)?(.*)$", _I | re.S)
_IN = re.compile(rf"\s*\bin\s+(\d+)\s*{_UNIT}\b\s*", _I)
_AT = re.compile(r"\s*\bat\s+(\d{1,2})(?::(\d{2}))?\s*(am|pm)?\b\s*", _I)
# A command starts the sentence: "show my X", "what's my X", or just "X" (no embedded mentions).
_VERB = r"(?:show|list|read|check|open|get|what(?:'s|\s+is|\s+are))"
_LEAD = (
    r"^\s*(?:jarvis[,\s]+)?(?:please\s+)?"
    rf"(?:{_VERB}\s+(?:me\s+)?(?:all\s+)?(?:my\s+|the\s+)?)?"
)
_DAY = r"(?:\s+(?:for\s+)?(?:today|tomorrow|this\s+week|the\s+week))?\s*[?.!]*$"
_NAME = r"([A-Z][A-Za-z.'\-]+(?:\s+[A-Z][A-Za-z.'\-]+){1,3})"  # 2-4 capitalised words
_REST = r"(?:\s+(?:(?:at|of|from)\s+)?(.+))?\s*$"
_RESEARCH = re.compile(
    r"^\s*(?:jarvis[,\s]+)?(?:please\s+)?(?i:research|look\s+up|find\s+out\s+about|"
    r"due\s+diligence\s+on|profiles?\s+(?:of|for|on)|(?:open|show)\s+(?:the\s+)?(?:\w+\s+)?"
    r"profiles?\s+(?:of|for|on))\s+" + _NAME + _REST
)
_OPEN_ONLY = re.compile(r"^\s*(?:jarvis[,\s]+)?(?:please\s+)?(?:open|show)\b.*\bprofiles?\b", _I)
_GENERATIVE = re.compile(
    r"\b(?:draft|compose|summari[sz]e|explain|teach|translate|brainstorm|poem|essay|story|quiz|"
    r"write\s+(?:me|a|an|the))\b",
    _I,
)
_SYSTEMS = re.compile(r"\bsystems?\s+check\b|\bhealth\s+check\b|\bdiagnostics?\b", _I)
_VITALS = re.compile(r"\bvitals?\b|\bapi\s+keys?\b", _I)
_QUOTA = re.compile(_LEAD + r"quotas?\s*[?.!]*$", _I)
_REMINDERS = re.compile(r"\breminders?\b", _I)
_TASKS = re.compile(_LEAD + r"(?:to-?\s?do\s+list|to-?\s?dos?|tasks?)\s*[?.!]*$", _I)
_SCHEDULE = re.compile(_LEAD + r"schedule" + _DAY, _I)
_CALENDAR = re.compile(
    r"\bcalendar\b|\bagenda\b|\bmeetings?\b|\bappointments?\b|what'?s\s+on\b", _I
)
_LEADING_TO = re.compile(r"^(?:to\s+)+", _I)
MAX_AMOUNT = 10_000


def _seconds(amount: str, unit: str) -> int | None:
    """Whole seconds for `amount unit`, or None when the amount is outside 1..MAX_AMOUNT."""
    n = int(amount) if len(amount) <= len(str(MAX_AMOUNT)) else 0
    if not 1 <= n <= MAX_AMOUNT:
        return None
    return n * _SECONDS[unit[0].lower()]


def _later(now: datetime, seconds: int) -> str | None:
    """`seconds` from now, rounded UP to the next whole minute (a reminder never fires early)."""
    try:
        target = now + timedelta(seconds=seconds)
    except OverflowError:
        return None
    if target.second or target.microsecond:
        target = target.replace(second=0, microsecond=0) + timedelta(minutes=1)
    return target.isoformat()


def _clock_time(now: datetime, hour: str, minute: str | None, meridiem: str | None) -> str | None:
    if not meridiem and minute is None:
        return None  # "at 5": morning or evening? ask
    h, m = int(hour), int(minute or 0)
    if meridiem:
        if not 1 <= h <= 12:
            return None
        h = h % 12 + (12 if meridiem.lower() == "pm" else 0)
    if h > 23 or m > 59:
        return None
    when = now.replace(hour=h, minute=m, second=0, microsecond=0)
    return (when if when > now else when + timedelta(days=1)).isoformat()


def _after(now: datetime, amount: str, unit: str) -> str | None:
    seconds = _seconds(amount, unit)
    return None if seconds is None else _later(now, seconds)


def _timer(text: str, now: datetime) -> NoAIRoute | None:
    m = _TIMER.search(text)
    if m is None:
        return None
    when = None if len(_ANY_DURATION.findall(text)) > 1 else _after(now, m[1], m[2])
    if when is None:
        return NoAIRoute(reply=NEEDS_TIME_LINE)
    return _one("reminder_add", text=TIMER_TEXT, when=when)


def _remind(text: str, now: datetime) -> NoAIRoute | None:
    m = _REMIND.search(text)
    if m is None:
        return None
    body = _LEADING_TO.sub("", m[1])
    when: str | None
    if (rel := _IN.search(body)) is not None:
        when, what = _after(now, rel[1], rel[2]), _IN.sub(" ", body, count=1)
    elif (at := _AT.search(body)) is not None:
        when, what = _clock_time(now, at[1], at[2], at[3]), _AT.sub(" ", body, count=1)
    else:
        return NoAIRoute(reply=NEEDS_TIME_LINE)
    what = " ".join(what.split()).strip(" .,")
    if when is None or not what or len(_ANY_DURATION.findall(body)) > 1:
        return NoAIRoute(reply=NEEDS_TIME_LINE)
    return _one("reminder_add", text=what, when=when)


def _notes(text: str) -> NoAIRoute | None:
    if (add := _NOTE_ADD.search(text)) is not None:
        body = add[1].strip()
        return _one("kb_add_note", text=body) if body else NoAIRoute(reply=NEEDS_QUERY_LINE)
    if (find := _NOTE_SEARCH.search(text)) is not None:
        query = find[1].strip(" .?")
        return _one("kb_search", query=query) if query else NoAIRoute(reply=NEEDS_QUERY_LINE)
    return None


def _people(text: str) -> NoAIRoute | None:
    """Only a command that starts with research/profiles AND a proper name (2-4 capitalised
    words). Anything else is left alone: with no model to arbitrate, a paid search is never a
    guess."""
    m = _RESEARCH.match(text)
    if m is None:
        return _one("people_open_profiles") if _OPEN_ONLY.match(text) else None
    rest = (m[2] or "").strip(" .?!")
    args = {"name": m[1].strip(), "context": rest} if rest else {"name": m[1].strip()}
    return NoAIRoute((NoAICall("research_person", args), NoAICall("people_open_profiles", {})))


def _calendar(text: str, now: datetime) -> NoAIRoute | None:
    if not (_CALENDAR.search(text) or _SCHEDULE.match(text)):
        return None
    day = now.replace(hour=0, minute=0, second=0, microsecond=0)
    lower = text.lower()
    if "tomorrow" in lower:
        start, days = day + timedelta(days=1), 1
    elif "week" in lower:
        start, days = day, WEEK_DAYS
    else:
        start, days = day, 1
    return _one(
        "calendar_list_events",
        start=start.isoformat(),
        end=(start + timedelta(days=days)).isoformat(),
    )


NoAIRouter = Callable[[str, datetime], "NoAIRoute | None"]


def _extra(routers: Sequence[NoAIRouter], text: str, now: datetime) -> NoAIRoute | None:
    """R11 D18: the helpers' phrase routers, first match wins; one that fails is skipped."""
    for router in routers:
        try:
            route = router(text, now)
        except Exception:  # noqa: BLE001 - a broken phrasebook never breaks No-AI mode
            continue
        if isinstance(route, NoAIRoute):
            return route
    return None


def route_no_ai(text: str, now: datetime, extra: Sequence[NoAIRouter] = ()) -> NoAIRoute:
    """The tool calls for `text` with no model, or the fixed line when it needs the AI.
    `now` is timezone-aware (the owner's zone). `extra` (R11 D18) are tried first."""
    text = text.strip()
    if extra and (route := _extra(extra, text, now)) is not None:
        return route
    for step in (_notes, lambda t: _timer(t, now), lambda t: _remind(t, now)):
        if (route := step(text)) is not None:
            return route
    if _GENERATIVE.search(text):
        return NoAIRoute()
    simple = (
        (_SYSTEMS, "systems_check"),
        (_VITALS, "vitals_show"),
    )
    if (route := _people(text)) is not None:
        return route
    for pattern, tool in simple:
        if pattern.search(text):
            return _one(tool)
    if _QUOTA.match(text):
        return _one("vitals_show")
    if _REMINDERS.search(text):
        return _one("reminders_list")
    if _TASKS.match(text):
        return _one("tasks_list")
    return _calendar(text, now) or NoAIRoute()


__all__ = [
    "NO_AI_LINE",
    "OFFLINE_ASK",
    "NoAICall",
    "NoAIRoute",
    "NoAIRouter",
    "OfflineRules",
    "route_no_ai",
    "wrap_offline",
]
