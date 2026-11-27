# tests/test_r18_i0_tools.py -- R18 I0: the gateway tools. `calls_place` is R3 (irreversible: an
# approval card every time, never a standing Allow, never Approve all); `calls_answer_mode` is a
# settings change whose switch ON is always its own card. Both are filed in the skill register.
from __future__ import annotations

from typing import Any

import pytest

from jarvis.calls import tools as ct
from jarvis.core.guardrails import ActionRisk, ConfirmationGate
from jarvis.llm.base import ToolCall
from jarvis.skills.registry import SkillRegister, load_catalogue
from jarvis.tools import AuditLog, Gateway, Policy, ToolRegistry
from jarvis.tools.base import Preview
from jarvis.tools.gateway import GatewayOutcome
from jarvis.tools.policy import Effect, PolicyRule

ARGS = {"number": "+919000000001", "purpose": "Book a laundry pickup tomorrow"}


class _Calls:
    def __init__(self) -> None:
        self.placed: list[dict[str, Any]] = []
        self.modes: list[dict[str, Any]] = []

    async def place(self, args: dict[str, Any]) -> dict[str, Any]:
        self.placed.append(args)
        return {"placed": True}

    async def preview(self, args: dict[str, Any]) -> Preview:
        return Preview(ct.place_summary(args) + " · about ₹2")

    async def answer_mode(self, args: dict[str, Any]) -> dict[str, Any]:
        self.modes.append(args)
        return {"answering_on": args["on"]}


def _gateway(calls: _Calls, policy: Policy | None = None) -> Gateway:
    reg = ToolRegistry()
    for t in ct.calls_tools(calls):
        reg.register(t)
    return Gateway(
        registry=reg, policy=policy or Policy(), gate=ConfirmationGate(), audit=AuditLog()
    )


def test_the_tools_and_their_risks() -> None:
    place, mode = ct.calls_tools(_Calls())
    assert (
        (place.name, mode.name)
        == (ct.PLACE, ct.ANSWER_MODE)
        == ("calls_place", "calls_answer_mode")
    )
    assert place.risk is ActionRisk.IRREVERSIBLE and place.risk_for is None
    assert mode.risk is ActionRisk.REVERSIBLE and not mode.spoken_ok
    assert mode.asks({"on": True}) and not mode.asks({"on": False})
    assert place.activity_words and mode.activity_words  # no number or purpose in Activity


async def test_placing_a_call_always_becomes_a_card_and_runs_only_once_approved() -> None:
    calls = _Calls()
    gw = _gateway(calls)
    asked = await gw.execute(ToolCall(id="t1", name=ct.PLACE, arguments=ARGS), scope="u_1")
    assert asked.outcome is GatewayOutcome.AWAITING_CONFIRMATION and calls.placed == []
    assert asked.pending is not None and asked.pending.irreversible
    assert "0001" in asked.pending.summary and "9000000001" not in asked.pending.summary
    assert not asked.pending.bulk_ok  # never "Approve all"
    ran = await gw.execute(
        ToolCall(id="t2", name=ct.PLACE, arguments=ARGS),
        confirmation_id=asked.pending.id,
        scope="u_1",
    )
    assert ran.outcome is GatewayOutcome.EXECUTED and calls.placed == [ARGS]


def test_no_standing_allow_for_calls() -> None:
    with pytest.raises(ValueError, match="standing ALLOW"):
        Policy(
            [PolicyRule(tool_pattern="calls_*", effect=Effect.ALLOW, risk=ActionRisk.IRREVERSIBLE)]
        )


async def test_an_owner_never_rule_refuses_calls() -> None:
    calls = _Calls()
    gw = _gateway(calls, Policy([PolicyRule(tool_pattern="calls_place", effect=Effect.DENY)]))
    got = await gw.execute(ToolCall(id="t1", name=ct.PLACE, arguments=ARGS), scope="u_1")
    assert got.outcome is GatewayOutcome.DENIED and calls.placed == []


@pytest.mark.parametrize(
    "bad",
    [
        {"purpose": "x"},  # neither a number nor a contact
        {"number": "9000000001", "purpose": "x"},
        {"number": "+919000000001", "purpose": ""},
        {"number": "+919000000001", "purpose": "x", "languages": ["xx-IN"]},
        {"number": "+919000000001", "purpose": "x", "max_minutes": 99},
        {"number": "+919000000001", "purpose": "x", "unknown": 1},
    ],
)
async def test_bad_arguments_fail_before_any_card(bad: dict[str, Any]) -> None:
    calls = _Calls()
    got = await _gateway(calls).execute(ToolCall(id="t", name=ct.PLACE, arguments=bad))
    assert got.outcome is GatewayOutcome.ERROR and got.pending is None and calls.placed == []


async def test_answer_mode_off_runs_and_on_asks_first() -> None:
    calls = _Calls()
    gw = _gateway(calls)
    off = await gw.execute(ToolCall(id="a", name=ct.ANSWER_MODE, arguments={"on": False}))
    assert off.outcome is GatewayOutcome.EXECUTED and calls.modes == [{"on": False}]
    on = await gw.execute(
        ToolCall(id="b", name=ct.ANSWER_MODE, arguments={"on": True, "after_rings": 4})
    )
    assert on.outcome is GatewayOutcome.AWAITING_CONFIRMATION and len(calls.modes) == 1
    assert on.pending is not None and not on.pending.irreversible  # R2: no passkey
    bad = await gw.execute(
        ToolCall(id="c", name=ct.ANSWER_MODE, arguments={"on": True, "policy": "nobody"})
    )
    assert bad.outcome is GatewayOutcome.ERROR


def test_the_card_text_masks_the_number() -> None:
    assert ct.place_summary(ARGS) == "Call the number ending 0001: Book a laundry pickup tomorrow"
    assert ct.place_summary({"contact": "Laundry", "purpose": "Pickup"}) == "Call Laundry: Pickup"
    assert ct.answer_summary({"on": False}) == "Stop answering calls you miss"
    words = ct.answer_summary({"on": True, "after_rings": 4, "policy": "contacts"})
    assert words == "Answer calls you miss after 4 rings (saved contacts only), taking messages"


def test_the_tools_are_filed_under_communication_and_planned_until_i1() -> None:
    register = SkillRegister(load_catalogue())
    for name in (ct.PLACE, ct.ANSWER_MODE):
        assert register.skill_of(name) == "communication"
        group = register.group_of(name)
        assert group is not None and group.id == "calls"
    assert {ct.PLACE, ct.ANSWER_MODE} <= register.catalogue.planned
    reg = ToolRegistry()
    assert not [p for p in register.problems(reg) if "calls" in p]


def test_build_gateway_registers_the_r18_tools(settings: Any) -> None:
    from jarvis.tools.setup import build_gateway

    gw = build_gateway(settings, r18=ct.calls_tools(_Calls()))
    place = gw.registry.get(ct.PLACE)
    assert place is not None and place.risk is ActionRisk.IRREVERSIBLE
    assert gw.registry.get(ct.ANSWER_MODE) is not None
    assert build_gateway(settings).registry.get(ct.PLACE) is None  # nothing until I1 wires it
