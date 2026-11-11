# tests/test_tool_context.py — slice 6: per-argument risk hook and the ToolContext contextvar
from __future__ import annotations

from typing import Any

import pytest

from jarvis.core.guardrails import ActionRisk, ConfirmationGate
from jarvis.llm.base import ToolCall
from jarvis.tools.audit import AuditLog
from jarvis.tools.base import Preview, Tool
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
    # slice 11 fix: the tool also learns the risk the call was decided at (R2: no guests)
    want = ToolContext(
        user_id="u_abc",
        session_id="sess_1",
        scope="u_abc:sess_1",
        approved_risk=ActionRisk.REVERSIBLE,
        tool="calendar_create_event",  # R11: the tool the gateway decided (background reads)
    )
    assert seen == [want]
    assert current_tool_context() is None  # reset after the run


def test_a_context_allows_no_more_than_was_approved() -> None:
    r1, r2, r3 = ActionRisk.READ_ONLY, ActionRisk.REVERSIBLE, ActionRisk.IRREVERSIBLE
    at_r2 = ToolContext("u", "s", "u:s", confirmed=True, approved_risk=r2)
    assert at_r2.allows(r1) and at_r2.allows(r2) and not at_r2.allows(r3)
    assert ToolContext("u", "s", "u:s", confirmed=True, approved_risk=r3).allows(r3)
    outside = ToolContext("u", "s", "u:s")  # no gateway decision: R3 only when approved
    assert outside.allows(r2) and not outside.allows(r3)
    assert ToolContext("u", "s", "u:s", confirmed=True).allows(r3)


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


# ---- Tool.preview (security review H1/M2): look the item up before deciding ------------------

ITEM_SCHEMA = {
    "type": "object",
    "properties": {"item": {"type": "string"}, "title": {"type": "string"}},
    "required": ["item"],
}


def _preview_tool(
    looked: list[Any],
    ran: list[Any],
    *,
    risk: ActionRisk = ActionRisk.REVERSIBLE,
    fail: bool = False,
) -> Tool:
    async def preview(a: dict[str, Any]) -> Preview:
        looked.append((dict(a), current_tool_context()))
        if fail:
            raise LookupError("Google could not find that item (not found).")
        shared = a["item"].startswith("shared")
        return Preview(
            summary=f"Change the item called {a['item'].upper()}",
            risk=ActionRisk.IRREVERSIBLE if shared else None,
        )

    def run(a: dict[str, Any]) -> dict[str, Any]:
        ran.append(dict(a))
        return {"ok": True}

    return Tool(
        "change_item",
        "d",
        ITEM_SCHEMA,
        risk,
        run,
        summary_template="template {item}",
        preview=preview,
    )


def _gateway_with(tool: Tool, policy: Policy | None = None) -> Gateway:
    reg = ToolRegistry()
    reg.register(tool)
    return Gateway(
        registry=reg, policy=policy or Policy(), gate=ConfirmationGate(), audit=AuditLog()
    )


async def test_preview_runs_in_the_tool_context_and_its_text_is_the_card() -> None:
    looked: list[Any] = []
    ran: list[Any] = []
    gateway = _gateway_with(_preview_tool(looked, ran, risk=ActionRisk.IRREVERSIBLE))
    args = {"item": "board"}
    out = await gateway.execute(ToolCall(id="p1", name="change_item", arguments=args), scope="u:s")
    assert out.outcome is GatewayOutcome.AWAITING_CONFIRMATION and out.pending is not None
    assert out.pending.summary == "Change the item called BOARD"
    assert out.pending.arguments == args  # stored arguments are exactly the call's
    assert looked[0][1] is not None and looked[0][1].user_id == "u" and ran == []
    ok = await gateway.execute(
        ToolCall(id="p1", name="change_item", arguments=args),
        confirmation_id=out.pending.id,
        scope="u:s",
    )
    assert ok.outcome is GatewayOutcome.EXECUTED and ran == [args]


async def test_preview_can_raise_a_reversible_call_to_ask() -> None:
    looked: list[Any] = []
    ran: list[Any] = []
    gateway = _gateway_with(_preview_tool(looked, ran))
    solo = await gateway.execute(
        ToolCall(id="p2", name="change_item", arguments={"item": "mine"}), scope="u:s"
    )
    assert solo.outcome is GatewayOutcome.EXECUTED and len(ran) == 1
    shared = await gateway.execute(
        ToolCall(id="p3", name="change_item", arguments={"item": "shared-doc"}), scope="u:s"
    )
    assert shared.outcome is GatewayOutcome.AWAITING_CONFIRMATION and len(ran) == 1
    entry = (await gateway.audit.tail(1)).entries[-1]
    assert entry.outcome == "awaiting_confirmation" and entry.risk is ActionRisk.IRREVERSIBLE


async def test_failed_preview_fails_closed_with_no_card_and_no_run() -> None:
    looked: list[Any] = []
    ran: list[Any] = []
    gateway = _gateway_with(_preview_tool(looked, ran, risk=ActionRisk.IRREVERSIBLE, fail=True))
    out = await gateway.execute(
        ToolCall(id="p4", name="change_item", arguments={"item": "gone"}), scope="u:s"
    )
    assert out.outcome is GatewayOutcome.ERROR and "not found" in (out.error or "")
    assert await gateway.pending() == [] and ran == []
    entry = (await gateway.audit.tail(1)).entries[-1]
    assert entry.outcome == "error" and "preview" in entry.detail


async def test_denied_tool_is_never_looked_up() -> None:
    from jarvis.tools.policy import PolicyRule

    looked: list[Any] = []
    gateway = _gateway_with(
        _preview_tool(looked, []),
        Policy([PolicyRule(tool_pattern="change_*", effect=Effect.DENY)]),
    )
    out = await gateway.execute(
        ToolCall(id="p5", name="change_item", arguments={"item": "x"}), scope="u:s"
    )
    assert out.outcome is GatewayOutcome.DENIED and looked == []


def test_template_summaries_are_flattened_to_one_safe_line() -> None:
    t = Tool(
        "x",
        "d",
        ITEM_SCHEMA,
        ActionRisk.IRREVERSIBLE,
        lambda a: None,
        summary_template="Do {item}",
    )
    assert t.summary({"item": "a\r\nb\u202ec"}) == "Do a bc"


def test_a_failing_summarize_falls_back_to_name_and_arguments_not_a_bare_verb() -> None:
    def broken(_: dict[str, Any]) -> str:
        raise ValueError("bad")

    t = Tool("send_x", "d", ITEM_SCHEMA, ActionRisk.IRREVERSIBLE, lambda a: None, summarize=broken)
    card = t.summary({"item": "to\nboss"})
    assert card.startswith("send_x ") and "boss" in card and "\n" not in card
