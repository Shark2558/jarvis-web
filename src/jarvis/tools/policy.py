# src/jarvis/tools/policy.py
"""Deterministic deny → ask → allow policy (Layer 4, Safety & Guardrails).

Default effect comes from the tool's risk class. Explicit rules refine it, and DENY always
wins. A standing ALLOW for an IRREVERSIBLE tool is refused at construction: there is no
"don't ask again" for sending, paying or deleting.
"""

from __future__ import annotations

import fnmatch
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

from jarvis.core.guardrails import ActionRisk


class Effect(StrEnum):
    ALLOW = "allow"
    ASK = "ask"
    DENY = "deny"


_RANK = {Effect.ALLOW: 0, Effect.ASK: 1, Effect.DENY: 2}

_DEFAULT: dict[ActionRisk, Effect] = {
    ActionRisk.READ_ONLY: Effect.ALLOW,
    ActionRisk.REVERSIBLE: Effect.ALLOW,
    ActionRisk.IRREVERSIBLE: Effect.ASK,
}


class PolicyRule(BaseModel):
    tool_pattern: str = Field(description="fnmatch pattern on the tool name, e.g. send_*")
    effect: Effect
    risk: ActionRisk | None = Field(default=None, description="Declared only to validate the rule")
    # Supported constraints: {"<arg>_not_in": [...]} → rule matches when args[arg] not in list;
    #                        {"<arg>_in": [...]}     → rule matches when args[arg] in list
    when: dict[str, list[Any]] = Field(default_factory=dict)
    source: str = "config"

    def matches(self, tool: str, args: dict[str, Any]) -> bool:
        if not fnmatch.fnmatchcase(tool, self.tool_pattern):
            return False
        for key, values in self.when.items():
            if key.endswith("_not_in"):
                if args.get(key[: -len("_not_in")]) in values:
                    return False
            elif key.endswith("_in"):
                if args.get(key[: -len("_in")]) not in values:
                    return False
            else:
                raise ValueError(f"unsupported constraint: {key}")
        return True


class Policy:
    def __init__(self, rules: list[PolicyRule] | None = None) -> None:
        self.rules = list(rules or [])
        for r in self.rules:
            if r.effect is Effect.ALLOW and r.risk is ActionRisk.IRREVERSIBLE:
                raise ValueError(f"standing ALLOW for irreversible tool refused: {r.tool_pattern}")

    def decide(self, tool: str, risk: ActionRisk, args: dict[str, Any]) -> Effect:
        matched = [r.effect for r in self.rules if r.matches(tool, args)]
        if Effect.DENY in matched:
            return Effect.DENY
        default = _DEFAULT[risk]
        if risk is ActionRisk.IRREVERSIBLE:
            return Effect.ASK  # rules can only tighten R3, never relax it
        if Effect.ASK in matched:
            return Effect.ASK
        return Effect.ALLOW if Effect.ALLOW in matched else default
