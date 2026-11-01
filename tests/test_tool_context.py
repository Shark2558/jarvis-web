# tests/test_tool_context.py — slice 6: per-argument risk hook and the ToolContext contextvar
from __future__ import annotations

from typing import Any

import pytest

from jarvis.core.guardrails import ActionRisk, ConfirmationGate
from jarvis.llm.base import ToolCall
from jarvis.tools.audit import AuditLog
from jarvis.tools.base import Tool
from jarvis.tools.context import ToolContext, current_tool_context, tool_context
from jarvis.tools.gateway import Gateway, GatewayOutcome
from jarvis.tools.policy import Effect, Policy
from jarvis.tools.registry import ToolRegistry

SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
        "attendees": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["summary"],
}


def _create_event_tool(seen: list[Any]) -> Tool:
    def run(args: dict[str, Any]) -> dict[str, Any]:
        seen.append(current_tool_context())
        return {"created": True}

    return Tool(
        "calendar_create_event",
        "create an event",
        SCHEMA,
        ActionRisk.REVERSIBLE,
        run,
        risk_for=lambda a: ActionRisk.IRREVERSIBLE if a.get("attendees") else ActionRisk.REVERSIBLE,
        summary_template="Create event {summary}",
    )


@pytest.fixture
def gw() -> tuple[Gateway, list[Any]]:
    seen: list[Any] = []
    reg = ToolRegistry()
    reg.register(_create_event_tool(seen))
    return (
        Gateway(registry=reg, policy=Policy(), gate=ConfirmationGate(), audit=AuditLog()),
        seen,
    )


# ---- risk_for -------------------------------------------------------------------------------


def test_effective_risk_defaults_to_declared_risk() -> None:
    t = Tool("x", "d", {"type": "object", "properties": {}}, ActionRisk.READ_ONLY, lambda a: None)
    assert t.effective_risk({}) is ActionRisk.READ_ONLY


def test_policy_sees_effective_risk() -> None:
    t = _create_event_tool([])
    p = Policy()
    assert p.decide(t.name, t.effective_risk({"summary": "x"}), {"summary": "x"}) is Effect.ALLOW
    args = {"summary": "x", "attendees": ["a@b.c"]}
    assert p.decide(t.name, t.effective_risk(args), args) is Effect.ASK


async def test_create_event_without_attendees_is_allowed(gw: tuple[Gateway, list[Any]]) -> None:
    gateway, _ = gw
    out = await gateway.execute(
        ToolCall(id="c1", name="calendar_create_event", arguments={"summary": "Focus"})
    )
    assert out.outcome is GatewayOutcome.EXECUTED
    assert (await gateway.audit.tail(1)).entries[-1].risk is ActionRisk.REVERSIBLE


async def test_create_event_with_attendees_asks_and_runs_only_with_token(
    gw: tuple[Gateway, list[Any]],
) -> None:
    gateway, seen = gw
    call = ToolCall(
        id="c2",
        name="calendar_create_event",
        arguments={"summary": "Sync", "attendees": ["priya@example.com"]},
    )
    out = await gateway.execute(call, scope="u1:s1")
    assert out.outcome is GatewayOutcome.AWAITING_CONFIRMATION
    assert out.pending is not None and out.pending.risk is ActionRisk.IRREVERSIBLE
    assert seen == []
    e = (await gateway.audit.tail(1)).entries[-1]
    assert e.outcome == "awaiting_confirmation" and e.risk is ActionRisk.IRREVERSIBLE

    out2 = await gateway.execute(call, confirmation_id=out.pending.id, scope="u1:s1")
    assert out2.outcome is GatewayOutcome.EXECUTED and len(seen) == 1


async def test_empty_attendee_list_is_not_an_invite(gw: tuple[Gateway, list[Any]]) -> None:
    gateway, _ = gw
    out = await gateway.execute(
        ToolCall(
            id="c3", name="calendar_create_event", arguments={"summary": "Solo", "attendees": []}
        )
    )
    assert out.outcome is GatewayOutcome.EXECUTED


# ---- ToolContext ----------------------------------------------------------------------------


def test_context_is_unset_outside_the_gateway() -> None:
    assert current_tool_context() is None


async def test_tool_sees_user_and_session_from_scope(gw: tuple[Gateway, list[Any]]) -> None:
    gateway, seen = gw
    await gateway.execute(
        ToolCall(id="c4", name="calendar_create_event", arguments={"summary": "x"}),
        scope="u_abc:sess_1",
    )
    assert seen == [ToolContext(user_id="u_abc", session_id="sess_1", scope="u_abc:sess_1")]
    assert current_tool_context() is None  # reset after the run


async def test_context_is_set_on_the_approved_path_and_cleared_after(
    gw: tuple[Gateway, list[Any]],
) -> None:
    gateway, seen = gw
    call = ToolCall(
        id="c5",
        name="calendar_create_event",
        arguments={"summary": "Sync", "attendees": ["p@example.com"]},
    )
    out = await gateway.execute(call, scope="u_abc:sess_2")
    await gateway.execute(call, confirmation_id=out.pending.id, scope="u_abc:sess_2")
    assert seen[-1].user_id == "u_abc" and seen[-1].session_id == "sess_2"
    assert current_tool_context() is None


async def test_context_is_cleared_even_when_the_tool_raises() -> None:
    def boom(_: dict[str, Any]) -> None:
        raise RuntimeError("nope")

    reg = ToolRegistry()
    reg.register(
        Tool("boom", "d", {"type": "object", "properties": {}}, ActionRisk.READ_ONLY, boom)
    )
    gateway = Gateway(registry=reg, policy=Policy(), gate=ConfirmationGate(), audit=AuditLog())
    out = await gateway.execute(ToolCall(id="c6", name="boom", arguments={}), scope="u:s")
    assert out.outcome is GatewayOutcome.ERROR
    assert current_tool_context() is None


def test_scope_without_session_part() -> None:
    with tool_context("owner") as ctx:
        assert ctx.user_id == "owner" and ctx.session_id is None
        assert current_tool_context() is ctx
    assert current_tool_context() is None


def test_no_scope_means_no_context() -> None:
    with tool_context(None) as ctx:
        assert ctx is None and current_tool_context() is None


# ---- Tool.check -----------------------------------------------------------------------------


async def test_check_hook_rejects_before_policy_so_nothing_is_proposed() -> None:
    def check(a: dict[str, Any]) -> None:
        if a.get("to") == "bad":
            raise ValueError("bad recipient")

    reg = ToolRegistry()
    reg.register(
        Tool(
            "send_thing",
            "d",
            {"type": "object", "properties": {"to": {"type": "string"}}, "required": ["to"]},
            ActionRisk.IRREVERSIBLE,
            lambda a: {"sent": True},
            check=check,
        )
    )
    gateway = Gateway(registry=reg, policy=Policy(), gate=ConfirmationGate(), audit=AuditLog())
    out = await gateway.execute(ToolCall(id="k1", name="send_thing", arguments={"to": "bad"}))
    assert out.outcome is GatewayOutcome.ERROR and "bad recipient" in (out.error or "")
    assert await gateway.pending() == []
    ok = await gateway.execute(ToolCall(id="k2", name="send_thing", arguments={"to": "fine"}))
    assert ok.outcome is GatewayOutcome.AWAITING_CONFIRMATION
