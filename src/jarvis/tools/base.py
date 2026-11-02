# src/jarvis/tools/base.py
"""Tool contract (Layer 6). A Tool is anything the model may invoke through the Gateway."""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from jarvis.core.guardrails import ActionRisk
from jarvis.llm.base import ToolCall, ToolSpec
from jarvis.tools.card import one_line

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
    # R2 call needs no passkey). Pure, no I/O; may read `jarvis.tools.taint`. Never asked for a
    # read-only call. An error counts as True (fail closed).
    ask_when: AskFn | None = None

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
            self.check(args)

    def summary(self, args: dict[str, Any]) -> str:
        # never show the owner a bare verb for something irreversible: the fallback is the
        # tool name with its (sanitised) arguments
        generic = f"{self.name} {json.dumps(args, default=str, ensure_ascii=False)}"
        if self.summarize is not None:
            try:
                return self.summarize(args)
            except (KeyError, TypeError, ValueError):
                return one_line(generic, SUMMARY_FALLBACK_LIMIT)
        try:
            text = self.summary_template.format(name=self.name, **args)
        except (KeyError, IndexError, ValueError):
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
