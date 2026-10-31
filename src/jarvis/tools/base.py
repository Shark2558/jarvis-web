# src/jarvis/tools/base.py
"""Tool contract (Layer 6). A Tool is anything the model may invoke through the Gateway."""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from jarvis.core.guardrails import ActionRisk
from jarvis.llm.base import ToolCall, ToolSpec

ToolFn = Callable[[dict[str, Any]], Awaitable[Any] | Any]


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    input_schema: dict[str, Any]
    risk: ActionRisk
    run: ToolFn
    agent: str = "core"
    # how the owner sees a pending action: "Send a message to {to}"
    summary_template: str = "{name}"
    required: tuple[str, ...] = field(default=())

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

    def summary(self, args: dict[str, Any]) -> str:
        try:
            return self.summary_template.format(name=self.name, **args)
        except (KeyError, IndexError):
            # never show the owner a bare verb for something irreversible
            return f"{self.name} {json.dumps(args, default=str)[:200]}"


__all__ = ["Tool", "ToolCall", "ToolFn"]
