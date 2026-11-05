# src/jarvis/tools/base.py
"""Tool contract (Layer 6). A Tool is anything the model may invoke through the Gateway."""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from jarvis.core.guardrails import ActionRisk
from jarvis.llm.base import ToolCall, ToolSpec
from jarvis.logging import get_logger
from jarvis.tools.card import one_line

log = get_logger(__name__)
ToolFn = Callable[[dict[str, Any]], Awaitable[Any] | Any]
RiskFn = Callable[[dict[str, Any]], ActionRisk]
CheckFn = Callable[[dict[str, Any]], None]
SummaryFn = Callable[[dict[str, Any]], str]
AskFn = Callable[[dict[str, Any]], bool]
SUMMARY_FALLBACK_LIMIT = 300


@dataclass(frozen=True)
class Preview:
    """What a read-only look-up made before the decision found: the text of the owner's
    approval card, and — when the item turns out to involve other people — a raised risk.
    A preview can only raise the risk the arguments imply, never lower it."""

    summary: str
    risk: ActionRisk | None = None
    # Another tool's name whose permission rule also governs this call, with its whole decision: a
    # calendar tool that finds it is about to touch a reminder names the Reminders row, so "Never"
    # there refuses and "Ask first" there makes this call a card (slice 12 review S1).
    also: str | None = None


PreviewFn = Callable[[dict[str, Any]], Awaitable[Preview]]


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    input_schema: dict[str, Any]
    risk: ActionRisk
    run: ToolFn
    agent: str = "core"
    # how the owner sees a pending action: "Send a message to {to}" (flattened to one line)
    summary_template: str = "{name}"
    required: tuple[str, ...] = field(default=())
    # Optional per-call risk: e.g. creating a calendar event is reversible alone but sends mail
    # (irreversible) once attendees are invited. Default: the declared `risk`.
    risk_for: RiskFn | None = None
    # Optional pure argument check (no I/O), run by the gateway BEFORE the policy decision, so a
    # malformed request fails fast instead of reaching an approval card or a URL.
    check: CheckFn | None = None
    # Optional card text built from the arguments (the tool sanitises every field); wins over
    # summary_template. Pure, no I/O.
    summarize: SummaryFn | None = None
    # Optional async READ-ONLY look-up the gateway awaits inside the tool context after the
    # argument check and before the policy decision (e.g. fetch the event about to be deleted):
    # the card shows the real item and the risk can rise. A failure is fail-closed: no card,
    # nothing runs. The stored PendingAction arguments stay exactly the call's arguments.
    preview: PreviewFn | None = None
    # True only for tools whose output is the owner's own data (the memory tools): their results
    # do not make the context "untrusted" (jarvis.tools.taint). Default: other people's words.
    trusted_output: bool = False
    # Slice 11: a delete that keeps a copy in Recently deleted (jarvis.undo), so it may run as R2.
    # One owner message runs at most `budget.MAX_FREE_DELETES` of them without a card.
    undoable: bool = False
    # Optional (slice 11 D7 a): True → this call becomes an approval card even where the policy
    # would allow it (an owner's Allow never relaxes it; the card keeps the call's own risk, so an
    # R2 call needs no passkey). Pure, no I/O; may read `jarvis.tools.taint`. Slice 12: honoured
    # for a read-only call too (maps_route sending Home / Work from a tainted round). An error
    # counts as True (fail closed).
    ask_when: AskFn | None = None
    # Slice 11 D8: True for tools that decide PER RESULT whether every item in it is the owner's
    # own (`jarvis.tools.provenance.vouch`): the owner's calendar, reminders and to-dos. The
    # gateway honours a vouched result only from such a tool. Never set it for mail, web,
    # documents or anything that can carry other people's words.
    may_vouch: bool = False
    # R1 D14: a write this tool makes on a SPOKEN turn runs without a card unless the round read
    # other people's content (`taint.content_tainted`). Only for writes that are visible and easy
    # to undo (groceries); the owner's Ask first / Never and R3 still apply. Default: False.
    spoken_ok: bool = False
    # R2 D13: fixed words the Activity recorder shows instead of `summary(args)` (Activity is kept
    # in clear for 7 days; a note's text or a place must never land there). Plain, no arguments.
    activity_words: str | None = None

    def effective_risk(self, args: dict[str, Any]) -> ActionRisk:
        return self.risk_for(args) if self.risk_for is not None else self.risk

    def asks(self, args: dict[str, Any]) -> bool:
        if self.ask_when is None:
            return False
        try:
            return bool(self.ask_when(args))
        except Exception:  # noqa: BLE001 — can't tell: ask
            return True

    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.name, description=self.description, input_schema=self.input_schema
        )

    def validate(self, args: dict[str, Any]) -> None:
        req = self.required or tuple(self.input_schema.get("required", ()))
        missing = [k for k in req if k not in args]
        if missing:
            raise ValueError(f"missing arguments: {', '.join(missing)}")
        props = self.input_schema.get("properties", {})
        unknown = [k for k in args if props and k not in props]
        if unknown:
            raise ValueError(f"unknown arguments: {', '.join(unknown)}")
        if self.check is not None:
            try:
                self.check(args)
            except OverflowError:  # a date far outside the calendar's range: plain words
                raise ValueError("a date or number in the request is out of range") from None

    def summary(self, args: dict[str, Any]) -> str:
        """The card text. Never raises: a card that can't be written would fail the whole reply
        (review S2: a tool argument called `name` met the template's own `name`). The fallback
        is the tool name with its (sanitised) arguments — never a bare verb for something
        irreversible — and the failure is logged (tool and error class only, no argument)."""
        generic = f"{self.name} {json.dumps(args, default=str, ensure_ascii=False)}"
        try:
            if self.summarize is not None:
                return self.summarize(args)
            text = self.summary_template.format(name=self.name, **args)
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            log.warning(
                "card text could not be made; generic card shown",
                extra={"tool": self.name, "error": type(exc).__name__},
            )
            text = generic
        return one_line(text, SUMMARY_FALLBACK_LIMIT)


__all__ = [
    "AskFn",
    "CheckFn",
    "Preview",
    "PreviewFn",
    "RiskFn",
    "SummaryFn",
    "Tool",
    "ToolCall",
    "ToolFn",
]
