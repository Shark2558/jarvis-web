# tests/test_tools.py — registry, policy, audit, gateway (written before implementation)
from __future__ import annotations

import pytest

from jarvis.core.guardrails import ActionRisk, ConfirmationGate
from jarvis.tools.audit import AuditLog
from jarvis.tools.base import ToolCall
from jarvis.tools.builtin import InMemoryWorld, builtin_tools
from jarvis.tools.gateway import Gateway, GatewayOutcome
from jarvis.tools.policy import Effect, Policy, PolicyRule
from jarvis.tools.registry import ToolRegistry


@pytest.fixture
def registry(gateway: Gateway) -> ToolRegistry:
    return gateway.registry


# ---------------------------------------------------------------- registry
def test_registry_specs_are_vendor_neutral(registry: ToolRegistry) -> None:
    specs = registry.specs()
    names = {s.name for s in specs}
    assert {"get_calendar", "list_tasks", "create_reminder", "send_message"} <= names
    cal = next(s for s in specs if s.name == "get_calendar")
    assert cal.input_schema["type"] == "object"
    assert cal.description


def test_registry_rejects_duplicates(registry: ToolRegistry, world: InMemoryWorld) -> None:
    with pytest.raises(ValueError):
        registry.register(builtin_tools(world)[0])


# ---------------------------------------------------------------- policy
def test_policy_defaults_follow_risk() -> None:
    p = Policy()
    assert p.decide("get_calendar", ActionRisk.READ_ONLY, {}) is Effect.ALLOW
    assert p.decide("create_reminder", ActionRisk.REVERSIBLE, {}) is Effect.ALLOW
    assert p.decide("send_message", ActionRisk.IRREVERSIBLE, {}) is Effect.ASK


def test_policy_deny_rule_beats_default_and_matches_pattern() -> None:
    p = Policy(rules=[PolicyRule(tool_pattern="send_*", effect=Effect.DENY)])
    assert p.decide("send_message", ActionRisk.IRREVERSIBLE, {}) is Effect.DENY
    assert p.decide("get_calendar", ActionRisk.READ_ONLY, {}) is Effect.ALLOW


def test_policy_arg_constraint() -> None:
    p = Policy(
        rules=[
            PolicyRule(
                tool_pattern="send_message",
                effect=Effect.DENY,
                when={"to_not_in": ["priya@example.com"]},
            )
        ]
    )
    assert (
        p.decide("send_message", ActionRisk.IRREVERSIBLE, {"to": "x@evil.example"}) is Effect.DENY
    )
    assert (
        p.decide("send_message", ActionRisk.IRREVERSIBLE, {"to": "priya@example.com"}) is Effect.ASK
    )


def test_policy_refuses_standing_allow_for_irreversible() -> None:
    with pytest.raises(ValueError):
        Policy(
            rules=[
                PolicyRule(
                    tool_pattern="send_message", effect=Effect.ALLOW, risk=ActionRisk.IRREVERSIBLE
                )
            ]
        )


# ---------------------------------------------------------------- audit
def test_audit_chain_verifies_and_detects_tampering() -> None:
    log = AuditLog()
    log.append(agent="t", tool="a", risk=ActionRisk.READ_ONLY, outcome="done", args={"x": 1})
    log.append(agent="t", tool="b", risk=ActionRisk.REVERSIBLE, outcome="done", args={})
    assert log.verify() is True
    assert len(log.entries()) == 2
    assert log.entries()[1].prev_hash == log.entries()[0].hash
    log._entries[0] = log._entries[0].model_copy(update={"outcome": "denied"})  # tamper
    assert log.verify() is False


# ---------------------------------------------------------------- gateway
async def test_gateway_allow_runs_tool_and_audits(gateway: Gateway, world: InMemoryWorld) -> None:
    out = await gateway.execute(
        ToolCall(id="c1", name="create_reminder", arguments={"text": "call bank", "when": "17:00"})
    )
    assert out.outcome is GatewayOutcome.EXECUTED
    assert out.result["created"] is True
    assert world.reminders[0]["text"] == "call bank"
    e = gateway.audit.entries()[-1]
    assert (e.tool, e.outcome) == ("create_reminder", "executed")


async def test_gateway_asks_for_irreversible_and_runs_only_with_token(
    gateway: Gateway, world: InMemoryWorld
) -> None:
    call = ToolCall(
        id="c2", name="send_message", arguments={"to": "priya@example.com", "body": "hi"}
    )
    out = await gateway.execute(call)
    assert out.outcome is GatewayOutcome.AWAITING_CONFIRMATION
    assert out.pending is not None and world.sent == []
    assert gateway.audit.entries()[-1].outcome == "awaiting_confirmation"

    out2 = await gateway.execute(call, confirmation_id=out.pending.id)
    assert out2.outcome is GatewayOutcome.EXECUTED
    assert world.sent == [{"to": "priya@example.com", "body": "hi"}]


async def test_gateway_rejects_argument_drift(gateway: Gateway, world: InMemoryWorld) -> None:
    call = ToolCall(
        id="c3", name="send_message", arguments={"to": "priya@example.com", "body": "v1"}
    )
    out = await gateway.execute(call)
    drifted = ToolCall(
        id="c3", name="send_message", arguments={"to": "priya@example.com", "body": "v2"}
    )
    out2 = await gateway.execute(drifted, confirmation_id=out.pending.id)
    assert out2.outcome is GatewayOutcome.AWAITING_CONFIRMATION
    assert world.sent == []


async def test_gateway_deny_never_runs_tool(registry: ToolRegistry, world: InMemoryWorld) -> None:
    gw = Gateway(
        registry=registry,
        policy=Policy(rules=[PolicyRule(tool_pattern="send_*", effect=Effect.DENY)]),
        gate=ConfirmationGate(),
        audit=AuditLog(),
    )
    out = await gw.execute(
        ToolCall(id="c4", name="send_message", arguments={"to": "a@b", "body": "x"})
    )
    assert out.outcome is GatewayOutcome.DENIED and world.sent == []
    assert gw.audit.entries()[-1].outcome == "denied"


async def test_gateway_unknown_tool_and_bad_args(gateway: Gateway) -> None:
    out = await gateway.execute(ToolCall(id="c5", name="nope", arguments={}))
    assert out.outcome is GatewayOutcome.ERROR and "unknown tool" in out.error.lower()
    out = await gateway.execute(
        ToolCall(id="c6", name="create_reminder", arguments={"text": "x"})
    )  # missing when
    assert out.outcome is GatewayOutcome.ERROR
