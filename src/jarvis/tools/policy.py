# src/jarvis/tools/policy.py
"""Deterministic deny → ask → allow policy (Layer 4, Safety & Guardrails).

Default effect comes from the tool's risk class. Explicit rules refine it, and DENY always
wins. A standing ALLOW for an IRREVERSIBLE tool is refused at construction: there is no
"don't ask again" for sending, paying or deleting.

Slice 10 D: the owner's own rules (Approvals → Permissions, `jarvis.permissions`) arrive per call
through an `OwnerRules` source and are appended to the configured ones. A rule may be scoped to
calls at certain effective risks (`risks`), carries where it came from (`source`, recorded in the
audit) and the plain words a refusal shows (`reason`).
"""

from __future__ import annotations

import fnmatch
from enum import StrEnum
from typing import Any, Protocol

from pydantic import BaseModel, Field

from jarvis.core.guardrails import ActionRisk


class Effect(StrEnum):
    ALLOW = "allow"
    ASK = "ask"
    DENY = "deny"


_RANK = {Effect.ALLOW: 0, Effect.ASK: 1, Effect.DENY: 2}

# Slice 10 D review M2: in a tainted round (the model has seen other people's text this turn) every
# REVERSIBLE write becomes an approval card — an R2 card, so no passkey. Read at call time by the
# gateway, so evals can switch it off for a negative control. Never relaxed by an owner's Allow.
TAINTED_WRITES_ASK = True

_DEFAULT: dict[ActionRisk, Effect] = {
    ActionRisk.READ_ONLY: Effect.ALLOW,
    ActionRisk.REVERSIBLE: Effect.ALLOW,
    ActionRisk.IRREVERSIBLE: Effect.ASK,
}


def default_effect(risk: ActionRisk) -> Effect:
    """Today's behaviour for a call at `risk` when no rule matches."""
    return _DEFAULT[risk]


class PolicyRule(BaseModel):
    tool_pattern: str = Field(description="fnmatch pattern on the tool name, e.g. send_*")
    effect: Effect
    risk: ActionRisk | None = Field(default=None, description="Declared only to validate the rule")
    risks: list[ActionRisk] | None = Field(
        default=None, description="Matches only calls at one of these effective risks"
    )
    # Supported constraints: {"<arg>_not_in": [...]} → rule matches when args[arg] not in list;
    #                        {"<arg>_in": [...]}     → rule matches when args[arg] in list
    when: dict[str, list[Any]] = Field(default_factory=dict)
    source: str = "config"
    reason: str = Field(default="", description="Plain words shown when this rule blocks a call")

    def matches(self, tool: str, args: dict[str, Any], risk: ActionRisk | None = None) -> bool:
        if not fnmatch.fnmatchcase(tool, self.tool_pattern):
            return False
        if self.risks is not None and (risk is None or risk not in self.risks):
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


class OwnerRules(Protocol):
    """Where the owner's own rules come from (implemented by `jarvis.permissions`). May raise:
    the gateway then fails closed — nothing runs."""

    async def rules_for(self, user_id: str) -> list[PolicyRule]: ...


class Policy:
    def __init__(self, rules: list[PolicyRule] | None = None) -> None:
        self.rules = list(rules or [])
        for r in self.rules:
            irreversible = r.risk is ActionRisk.IRREVERSIBLE or (
                r.risks is not None and ActionRisk.IRREVERSIBLE in r.risks
            )
            if r.effect is Effect.ALLOW and irreversible:
                raise ValueError(f"standing ALLOW for irreversible tool refused: {r.tool_pattern}")

    def decide(self, tool: str, risk: ActionRisk, args: dict[str, Any]) -> Effect:
        matched = [r.effect for r in self.rules if r.matches(tool, args, risk)]
        if Effect.DENY in matched:
            return Effect.DENY
        default = _DEFAULT[risk]
        if risk is ActionRisk.IRREVERSIBLE:
            return Effect.ASK  # rules can only tighten R3, never relax it
        if Effect.ASK in matched:
            return Effect.ASK
        return Effect.ALLOW if Effect.ALLOW in matched else default

    def denied_by(self, tool: str, risk: ActionRisk, args: dict[str, Any]) -> PolicyRule | None:
        """The first DENY rule that matches this call (its source goes to the audit)."""
        return next(
            (r for r in self.rules if r.effect is Effect.DENY and r.matches(tool, args, risk)),
            None,
        )

    def with_rules(self, extra: list[PolicyRule]) -> Policy:
        """A new policy: these rules after this one's (validated again; never mutates)."""
        return Policy(self.rules + list(extra)) if extra else self
