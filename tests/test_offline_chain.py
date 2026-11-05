# tests/test_offline_chain.py -- security review fix 3: wiring. `wrap_offline` must be the OUTERMOST
# rules wrapper (around telegram's `wrap_rules(...)`). A channel wrapper keeps only the rule
# sources it knows, so an offline rule placed inside it is silently dropped and an offline
# calendar add would run without a card.
from __future__ import annotations

from typing import Any

import pytest

from jarvis.core import channel
from jarvis.core.guardrails import ActionRisk, ConfirmationGate
from jarvis.llm.base import ToolCall
from jarvis.offline.rules import OfflineRules, wrap_offline
from jarvis.tools import AuditLog, Effect, Gateway, GatewayOutcome, Policy, PolicyRule, Tool
from jarvis.tools.registry import ToolRegistry


class Owner:
    """The owner's permissions: calendar adds are always allowed."""

    async def rules_for(self, user_id: str) -> list[PolicyRule]:
        return [PolicyRule(tool_pattern="calendar_*", effect=Effect.ALLOW, source="permissions")]


class StrictChannel:
    """Stand-in for telegram's `wrap_rules`: keeps only rules from sources it knows."""

    KNOWN = {"permissions", "channel"}

    def __init__(self, inner: Any) -> None:
        self._inner = inner

    async def rules_for(self, user_id: str) -> list[PolicyRule]:
        return [r for r in await self._inner.rules_for(user_id) if r.source in self.KNOWN]


def _gateway(rules: Any) -> Gateway:
    async def run(args: dict[str, Any]) -> dict[str, Any]:
        return {"ok": True}

    reg = ToolRegistry()
    reg.register(
        Tool(
            "calendar_add_event",
            "d",
            {"type": "object", "properties": {}},
            ActionRisk.REVERSIBLE,
            run,
            summarize=lambda a: "Add an event",
        )
    )
    return Gateway(
        registry=reg, policy=Policy(), gate=ConfirmationGate(), audit=AuditLog(), rules=rules
    )


async def _add(gw: Gateway) -> GatewayOutcome:
    call = ToolCall(id="1", name="calendar_add_event", arguments={})
    return (await gw.execute(call, scope="u1:sess")).outcome


@pytest.fixture(autouse=True)
def _fresh() -> None:
    channel.reset_offline()


def test_wrap_offline_returns_the_offline_rules() -> None:
    assert isinstance(wrap_offline(Owner()), OfflineRules)


async def test_outermost_an_offline_calendar_add_comes_back_as_a_card() -> None:
    gw = _gateway(wrap_offline(StrictChannel(Owner())))
    channel.mark_offline()
    assert await _add(gw) is GatewayOutcome.AWAITING_CONFIRMATION


async def test_outermost_a_cloud_calendar_add_still_runs() -> None:
    gw = _gateway(wrap_offline(StrictChannel(Owner())))
    assert await _add(gw) is GatewayOutcome.EXECUTED


async def test_inner_the_offline_rule_is_dropped_and_the_write_runs() -> None:
    """Why the order matters: this is the wiring mistake the helper exists to prevent."""
    gw = _gateway(StrictChannel(wrap_offline(Owner())))
    channel.mark_offline()
    assert await _add(gw) is GatewayOutcome.EXECUTED


def test_the_docstring_says_outermost_and_names_the_telegram_wrapper() -> None:
    doc = wrap_offline.__doc__ or ""
    assert "OUTERMOST" in doc and "wrap_rules" in doc
