# src/jarvis/calls/tools.py
"""R18's gateway tools (Communication skill, group `calls`; skills/catalogue.json).

- `calls_place` (R3, IRREVERSIBLE): a phone call from the owner's own number. Always an approval
  card (the gateway's R3 rule: no standing Allow, never Approve all); A1's approval binds the token
  to the number and the card's digest (10 minutes, one use) and asks his passkey for a number never
  called before. The card text shows the number's last four digits only (cards, the audit and
  Activity are not the place for a full number); the Calls panel shows the whole card.
- `calls_answer_mode` (R2, a settings change): answering missed calls (row 104, off by default).
  Switching it ON is always its own card (`ask_when`); switching it off runs at once.

`calls_tools(calls)` builds both over a `CallTools` (A1's service, joined by I1 and registered with
`tools.setup.build_gateway(r18=...)`). The argument checks here are pure (no I/O).
"""

from __future__ import annotations

from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from jarvis.calls.models import (
    CALL_MAX_MINUTES_CEILING,
    E164,
    LINE_MAX,
    LINES_MAX,
    NAME_MAX,
    PURPOSE_MAX,
    AnswerPolicy,
    Booking,
    check_languages,
)
from jarvis.core.guardrails import ActionRisk
from jarvis.tools.base import Preview, Tool

PLACE = "calls_place"
ANSWER_MODE = "calls_answer_mode"
TOOL_NAMES = (PLACE, ANSWER_MODE)
_POLICY_WORDS = {
    AnswerPolicy.ALL: "everyone",
    AnswerPolicy.CONTACTS: "saved contacts only",
    AnswerPolicy.NOT_CONTACTS: "everyone except saved contacts",
}


class CallTools(Protocol):
    async def place(self, args: dict[str, Any]) -> dict[str, Any]: ...

    async def preview(self, args: dict[str, Any]) -> Preview: ...

    async def answer_mode(self, args: dict[str, Any]) -> dict[str, Any]: ...


class PlaceArgs(BaseModel):
    """`calls_place`'s arguments (the call card's draft; A1 writes the card from it)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    number: str | None = Field(default=None, pattern=E164)
    contact: str | None = Field(default=None, min_length=1, max_length=NAME_MAX)
    purpose: str = Field(min_length=1, max_length=PURPOSE_MAX)
    may_say: tuple[str, ...] = Field(default=(), max_length=LINES_MAX)
    may_agree: tuple[str, ...] = Field(default=(), max_length=LINES_MAX)
    languages: tuple[str, ...] | None = None  # None: his default languages
    template: str | None = Field(default=None, pattern=r"^[a-z][a-z0-9_]{1,39}$")
    booking: Booking | None = None
    max_minutes: int | None = Field(default=None, ge=1, le=CALL_MAX_MINUTES_CEILING)

    @model_validator(mode="after")
    def _check(self) -> PlaceArgs:
        if not self.number and not self.contact:
            raise ValueError("give the number (+91...) or a saved contact's name")
        if self.languages is not None:
            check_languages(self.languages)
        if any(not x.strip() or len(x) > LINE_MAX for x in (*self.may_say, *self.may_agree)):
            raise ValueError(f"each line needs 1 to {LINE_MAX} characters")
        return self


class AnswerArgs(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    on: bool
    after_rings: int | None = Field(default=None, ge=2, le=15)
    policy: AnswerPolicy | None = None


def _plain(exc: ValidationError) -> ValueError:
    fields = sorted({".".join(str(x) for x in e["loc"]) for e in exc.errors() if e["loc"]})
    custom = [str(e.get("ctx", {}).get("error", "")) for e in exc.errors() if not e["loc"]]
    words = "; ".join(w for w in custom if w) or f"check {', '.join(fields) or 'the request'}"
    return ValueError(words[:200])


def check_place(args: dict[str, Any]) -> None:
    try:
        PlaceArgs.model_validate(args)
    except ValidationError as exc:
        raise _plain(exc) from None


def check_answer(args: dict[str, Any]) -> None:
    try:
        AnswerArgs.model_validate(args)
    except ValidationError as exc:
        raise _plain(exc) from None


def place_summary(args: dict[str, Any]) -> str:
    who = str(args.get("contact") or "").strip()
    number = str(args.get("number") or "")
    target = who or (f"the number ending {number[-4:]}" if number else "a number")
    return f"Call {target}: {' '.join(str(args.get('purpose', '')).split())}"


def answer_summary(args: dict[str, Any]) -> str:
    if not args.get("on"):
        return "Stop answering calls you miss"
    rings = args.get("after_rings")
    policy = args.get("policy")
    words = "Answer calls you miss"
    if rings:
        words += f" after {int(rings)} rings"
    if policy in _POLICY_WORDS:
        words += f" ({_POLICY_WORDS[AnswerPolicy(policy)]})"
    return words + ", taking messages"


_LINES = {
    "type": "array",
    "items": {"type": "string", "maxLength": LINE_MAX},
    "maxItems": LINES_MAX,
}
PLACE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "number": {"type": "string", "description": "E.164, e.g. +91 then 10 digits, no spaces"},
        "contact": {"type": "string", "description": "A saved contact's name, if no number"},
        "purpose": {"type": "string", "description": "Why JARVIS calls, in a sentence"},
        "may_say": {**_LINES, "description": "What JARVIS may tell them"},
        "may_agree": {**_LINES, "description": "What JARVIS may agree to; nothing else"},
        "languages": {
            "type": "array",
            "items": {"type": "string"},
            "description": "BCP-47, e.g. en-IN, ml-IN: English + up to 3 Indian languages",
        },
        "template": {"type": "string", "description": "A call template, e.g. laundry_pickup"},
        "booking": {
            "type": "object",
            "description": "For an appointment: windows [{day, start, end}], give_name, "
            "give_number, reason; JARVIS never agrees to pay",
        },
        "max_minutes": {"type": "integer", "minimum": 1, "maximum": CALL_MAX_MINUTES_CEILING},
    },
    "required": ["purpose"],
}
ANSWER_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "on": {"type": "boolean"},
        "after_rings": {"type": "integer", "minimum": 2, "maximum": 15},
        "policy": {"type": "string", "enum": [p.value for p in AnswerPolicy]},
    },
    "required": ["on"],
}


def calls_tools(calls: CallTools) -> list[Tool]:
    place = Tool(
        PLACE,
        "Place a phone call for the owner from his own number (through his laptop and phone), "
        "only after he approves the call card. JARVIS says first that it is an AI assistant "
        "calling for him and that the call is recorded, stays within what the card allows and "
        "never agrees to pay. Never for emergency, premium-rate or international numbers.",
        PLACE_SCHEMA,
        ActionRisk.IRREVERSIBLE,
        calls.place,
        agent="communication",
        check=check_place,
        summarize=place_summary,
        preview=calls.preview,
        activity_words="Asked to place a phone call",
    )
    answer = Tool(
        ANSWER_MODE,
        "Switch answering the owner's missed calls on or off (off by default). When on, JARVIS "
        "answers after a number of rings, says it is his AI assistant and only takes a message.",
        ANSWER_SCHEMA,
        ActionRisk.REVERSIBLE,
        calls.answer_mode,
        agent="communication",
        check=check_answer,
        summarize=answer_summary,
        ask_when=lambda a: a.get("on") is True,
        activity_words="Changed answering missed calls",
    )
    return [place, answer]


__all__ = [
    "ANSWER_MODE",
    "ANSWER_SCHEMA",
    "PLACE",
    "PLACE_SCHEMA",
    "TOOL_NAMES",
    "AnswerArgs",
    "CallTools",
    "PlaceArgs",
    "answer_summary",
    "calls_tools",
    "check_answer",
    "check_place",
    "place_summary",
]
