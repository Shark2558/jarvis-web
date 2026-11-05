# tests/test_offline_rules.py -- R1 C (D11 b): every R2 write in a turn answered by the laptop brain
# becomes a one-tap card (OfflineRules asks on R2 while core.channel.answered_offline()). Reads and
# the owner's own rules are untouched; R3 still asks (a rule can never relax it).
from __future__ import annotations

from typing import Any

import pytest

from jarvis.core import channel
from jarvis.core.guardrails import ActionRisk, ConfirmationGate
from jarvis.llm.base import ToolCall
from jarvis.offline import rules as rules_mod
from jarvis.offline.rules import OfflineRules
from jarvis.tools import AuditLog, Effect, Gateway, GatewayOutcome, Policy, PolicyRule, Tool
from jarvis.tools.registry import ToolRegistry

R1, R2, R3 = ActionRisk.READ_ONLY, ActionRisk.REVERSIBLE, ActionRisk.IRREVERSIBLE
SCOPE = "u1:sess"


class Inner:
    def __init__(self, rules: list[PolicyRule] | None = None, boom: bool = False) -> None:
        self.rules = rules or []
        self.boom = boom
        self.asked: list[str] = []

    async def rules_for(self, user_id: str) -> list[PolicyRule]:
        self.asked.append(user_id)
        if self.boom:
            raise RuntimeError("rules store down")
        return list(self.rules)


def _tool(name: str, risk: ActionRisk) -> Tool:
    async def run(args: dict[str, Any]) -> dict[str, Any]:
        return {"ok": True}

    return Tool(
        name, "d", {"type": "object", "properties": {}}, risk, run, summarize=lambda a: f"Do {name}"
    )


def _gw(rules: OfflineRules) -> Gateway:
    reg = ToolRegistry()
    for n, r in [("reminder_add", R2), ("calendar_list_events", R1), ("send_message", R3)]:
        reg.register(_tool(n, r))
    return Gateway(
        registry=reg, policy=Policy(), gate=ConfirmationGate(), audit=AuditLog(), rules=rules
    )


async def _run(gw: Gateway, name: str) -> GatewayOutcome:
    res = await gw.execute(ToolCall(id="1", name=name, arguments={}), scope=SCOPE)
    return res.outcome


@pytest.fixture(autouse=True)
def _fresh() -> None:
    channel.reset_offline()


async def test_no_extra_rules_while_the_cloud_answered() -> None:
    assert await OfflineRules(Inner()).rules_for("u1") == []


async def test_offline_adds_one_ask_rule_on_r2_only() -> None:
    channel.mark_offline()
    got = await OfflineRules(Inner()).rules_for("u1")
    assert len(got) == 1
    r = got[0]
    assert r.effect is Effect.ASK and r.risks == [R2] and r.source == "offline"
    assert r.tool_pattern == "*" and r.reason


async def test_the_owners_own_rules_come_first_and_unchanged() -> None:
    mine = PolicyRule(tool_pattern="reminder_*", effect=Effect.ALLOW, source="permissions")
    channel.mark_offline()
    got = await OfflineRules(Inner([mine])).rules_for("u1")
    assert got[0] == mine and got[-1].source == "offline"


async def test_the_inner_source_is_asked_for_the_same_owner() -> None:
    inner = Inner()
    await OfflineRules(inner).rules_for("u9")
    assert inner.asked == ["u9"]


async def test_an_unreadable_inner_source_fails_closed() -> None:
    with pytest.raises(RuntimeError):
        await OfflineRules(Inner(boom=True)).rules_for("u1")


async def test_a_write_runs_when_the_cloud_answered() -> None:
    gw = _gw(OfflineRules(Inner()))
    assert await _run(gw, "reminder_add") is GatewayOutcome.EXECUTED


async def test_a_write_becomes_a_card_in_an_offline_turn_even_with_allow() -> None:
    allow = PolicyRule(tool_pattern="reminder_*", effect=Effect.ALLOW, source="permissions")
    gw = _gw(OfflineRules(Inner([allow])))
    channel.mark_offline()
    assert await _run(gw, "reminder_add") is GatewayOutcome.AWAITING_CONFIRMATION


async def test_reads_still_run_in_an_offline_turn() -> None:
    gw = _gw(OfflineRules(Inner()))
    channel.mark_offline()
    assert await _run(gw, "calendar_list_events") is GatewayOutcome.EXECUTED


async def test_r3_still_asks_and_is_never_relaxed() -> None:
    gw = _gw(OfflineRules(Inner()))
    channel.mark_offline()
    assert await _run(gw, "send_message") is GatewayOutcome.AWAITING_CONFIRMATION


async def test_the_marker_resets_with_the_next_turn() -> None:
    gw = _gw(OfflineRules(Inner()))
    channel.mark_offline()
    assert await _run(gw, "reminder_add") is GatewayOutcome.AWAITING_CONFIRMATION
    channel.reset_offline()
    assert await _run(gw, "reminder_add") is GatewayOutcome.EXECUTED


async def test_the_negative_control_switch_turns_the_ask_off(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(rules_mod, "WRITES_ASK", False)
    channel.mark_offline()
    assert await OfflineRules(Inner()).rules_for("u1") == []
