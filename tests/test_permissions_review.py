# tests/test_permissions_review.py — the slice 10 D security review fixes at the gateway:
# H1 a card that became riskier (or reads differently) since it was proposed is re-proposed, never
#    run, and the passkey guard runs on the approve path inside the gateway with the card's
#    current risk; M2 every reversible write in a tainted round asks (R2 card, no passkey), never
#    outside a turn; LOW an owner-rules gateway without a scope fails closed.
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest

import jarvis.tools.policy as policy_mod
from jarvis.core.guardrails import ActionRisk, ConfirmationGate, PendingAction
from jarvis.permissions.groups import rules_for
from jarvis.tools.audit import AuditLog
from jarvis.tools.base import Preview, Tool, ToolCall
from jarvis.tools.builtin import InMemoryWorld, builtin_tools
from jarvis.tools.gateway import Gateway, GatewayOutcome
from jarvis.tools.policy import Effect, Policy, PolicyRule
from jarvis.tools.registry import ToolRegistry
from jarvis.tools.taint import context_trust

R1, R2, R3 = ActionRisk.READ_ONLY, ActionRisk.REVERSIBLE, ActionRisk.IRREVERSIBLE
SCOPE = "u1:s1"


class NeedsPasskey(PermissionError):
    pass


@dataclass
class FakeGuard:
    """Stands in for PermissionsService.check_approval: irreversible cards need a proof."""

    seen: list[tuple[str, str, ActionRisk | None]] = field(default_factory=list)

    async def check_approval(
        self, user_id: str, action: PendingAction, proof: object | None
    ) -> str | None:
        self.seen.append((user_id, action.id, action.tool_risk))
        if action.irreversible and proof is None:
            raise NeedsPasskey("needs your passkey")
        return "passkey 0123abcd" if action.irreversible else None


class Rules:
    def __init__(self, choices: dict[str, Effect]) -> None:
        self.choices = choices

    async def rules_for(self, user_id: str) -> list[PolicyRule]:
        return rules_for(self.choices)


@dataclass
class Event:
    guests: bool = False
    title: str = "Dentist"
    ran: list[dict[str, Any]] = field(default_factory=list)


def _update_tool(ev: Event) -> Tool:
    async def preview(a: dict[str, Any]) -> Preview:
        who = "and email the guests" if ev.guests else "only you"
        return Preview(f"Move “{ev.title}” to {a['when']} ({who})", R3 if ev.guests else None)

    return Tool(
        "calendar_update_event",
        "update",
        {"type": "object", "properties": {"when": {"type": "string"}}},
        R2,
        ev.ran.append,
        preview=preview,
    )


def _gw(*tools: Tool, choices: dict[str, Effect] | None = None, guard: Any = None) -> Gateway:
    reg = ToolRegistry()
    for t in tools:
        reg.register(t)
    return Gateway(
        registry=reg,
        policy=Policy(),
        gate=ConfirmationGate(),
        audit=AuditLog(),
        rules=Rules(choices or {}),
        approval_guard=guard,
    )


MOVE = ToolCall(id="m", name="calendar_update_event", arguments={"when": "15:00"})


# ---- H1 ------------------------------------------------------------------------------------------


async def test_a_card_that_became_irreversible_is_re_proposed_not_run() -> None:
    ev, guard = Event(), FakeGuard()
    gw = _gw(_update_tool(ev), choices={"calendar_change": Effect.ASK}, guard=guard)
    first = await gw.execute(MOVE, scope=SCOPE)
    assert first.outcome is GatewayOutcome.AWAITING_CONFIRMATION and first.pending is not None
    old = first.pending
    assert old.tool_risk is R2 and "only you" in old.summary
    ev.guests = True  # someone adds guests before the owner approves
    out = await gw.execute(MOVE, scope=SCOPE, confirmation_id=old.id)
    assert out.outcome is GatewayOutcome.AWAITING_CONFIRMATION and ev.ran == []
    new = out.pending
    assert new is not None and new.id != old.id
    assert new.tool_risk is R3 and "email the guests" in new.summary
    assert await gw.gate.get(old.id) is None  # the old card is gone
    assert guard.seen == []  # nothing was about to run, so no passkey was asked for
    entry = (await gw.audit.tail(1)).entries[-1]
    assert entry.outcome == "awaiting_confirmation" and "changed since" in entry.detail
    # the new card is irreversible: approving it goes through the passkey guard
    with pytest.raises(NeedsPasskey):
        await gw.execute(MOVE, scope=SCOPE, confirmation_id=new.id)
    assert ev.ran == [] and await gw.gate.get(new.id) is not None  # not consumed
    ok = await gw.execute(MOVE, scope=SCOPE, confirmation_id=new.id, proof={"p": 1})
    assert ok.outcome is GatewayOutcome.EXECUTED and len(ev.ran) == 1
    executing = [e for e in (await gw.audit.tail(5)).entries if e.outcome == "executing"]
    assert executing[-1].detail == "confirmed; passkey 0123abcd"


async def test_a_card_whose_text_changed_is_re_proposed() -> None:
    ev = Event()
    gw = _gw(_update_tool(ev), choices={"calendar_change": Effect.ASK}, guard=FakeGuard())
    old = (await gw.execute(MOVE, scope=SCOPE)).pending
    assert old is not None
    ev.title = "Board meeting"  # the event behind the card is another one now
    out = await gw.execute(MOVE, scope=SCOPE, confirmation_id=old.id)
    assert out.outcome is GatewayOutcome.AWAITING_CONFIRMATION and ev.ran == []
    assert out.pending is not None and "Board meeting" in out.pending.summary


async def test_an_unchanged_card_runs_once_through_the_guard() -> None:
    ev, guard = Event(), FakeGuard()
    gw = _gw(_update_tool(ev), choices={"calendar_change": Effect.ASK}, guard=guard)
    old = (await gw.execute(MOVE, scope=SCOPE)).pending
    assert old is not None
    out = await gw.execute(MOVE, scope=SCOPE, confirmation_id=old.id)
    assert out.outcome is GatewayOutcome.EXECUTED and len(ev.ran) == 1
    assert guard.seen == [("u1", old.id, R2)]
    again = await gw.execute(MOVE, scope=SCOPE, confirmation_id=old.id)
    assert again.outcome is GatewayOutcome.CONFIRMATION_INVALID and len(ev.ran) == 1


async def test_a_new_riskier_proposal_does_not_reuse_the_old_card() -> None:
    ev = Event()
    gw = _gw(_update_tool(ev), choices={"calendar_change": Effect.ASK})
    old = (await gw.execute(MOVE, scope=SCOPE)).pending
    ev.guests = True
    new = (await gw.execute(MOVE, scope=SCOPE)).pending
    assert old is not None and new is not None and new.id != old.id
    assert new.tool_risk is R3
    same = (await gw.execute(MOVE, scope=SCOPE)).pending
    assert same is not None and same.id == new.id  # an identical proposal still dedupes


async def test_a_legacy_card_without_tool_risk_still_consumes() -> None:
    gate = ConfirmationGate()
    card = PendingAction(tool="t", arguments={}, risk=R3, summary="s", scope=SCOPE)
    await gate.store.put(card)
    await gate.check(card.model_copy(update={"tool_risk": R2}), confirmation_id=card.id)
    assert await gate.get(card.id) is None


async def test_the_guard_runs_on_every_irreversible_approval() -> None:
    world, guard = InMemoryWorld(), FakeGuard()
    gw = _gw(*builtin_tools(world), guard=guard)
    send = ToolCall(id="s", name="send_message", arguments={"to": "a@x.com", "body": "b"})
    card = (await gw.execute(send, scope=SCOPE)).pending
    assert card is not None and card.tool_risk is R3
    with pytest.raises(NeedsPasskey):
        await gw.execute(send, scope=SCOPE, confirmation_id=card.id)
    assert world.sent == []
    ok = await gw.execute(send, scope=SCOPE, confirmation_id=card.id, proof=object())
    assert ok.outcome is GatewayOutcome.EXECUTED and len(world.sent) == 1


# ---- M2 ------------------------------------------------------------------------------------------

REMIND = ToolCall(id="r", name="create_reminder", arguments={"text": "x", "when": "17:00"})
LIST = ToolCall(id="l", name="list_tasks", arguments={})


async def test_every_reversible_write_in_a_tainted_round_asks_with_an_r2_card() -> None:
    assert policy_mod.TAINTED_WRITES_ASK is True
    world = InMemoryWorld()
    gw = _gw(*builtin_tools(world), guard=FakeGuard())
    with context_trust(untrusted=True):
        out = await gw.execute(REMIND, scope=SCOPE)
        read = await gw.execute(LIST, scope=SCOPE)
    assert out.outcome is GatewayOutcome.AWAITING_CONFIRMATION and world.reminders == []
    assert out.pending is not None and out.pending.tool_risk is R2
    assert read.outcome is GatewayOutcome.EXECUTED  # reading is not a write
    ok = await gw.execute(REMIND, scope=SCOPE, confirmation_id=out.pending.id)  # no passkey
    assert ok.outcome is GatewayOutcome.EXECUTED and len(world.reminders) == 1


async def test_a_clean_round_and_no_turn_at_all_do_not_ask() -> None:
    world = InMemoryWorld()
    gw = _gw(*builtin_tools(world))
    with context_trust(untrusted=False):
        assert (await gw.execute(REMIND, scope=SCOPE)).outcome is GatewayOutcome.EXECUTED
    assert (await gw.execute(REMIND, scope=SCOPE)).outcome is GatewayOutcome.EXECUTED


async def test_the_rule_can_be_switched_off_for_negative_controls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(policy_mod, "TAINTED_WRITES_ASK", False)
    world = InMemoryWorld()
    gw = _gw(*builtin_tools(world))
    with context_trust(untrusted=True):
        assert (await gw.execute(REMIND, scope=SCOPE)).outcome is GatewayOutcome.EXECUTED


def test_memory_save_no_longer_raises_itself_to_irreversible() -> None:
    from jarvis.recall.tools import memory_tools

    class _Svc:
        pass

    save = next(t for t in memory_tools(_Svc()) if t.name == "memory_save")  # type: ignore[arg-type]
    args = {"text": "x", "category": "other"}
    with context_trust(untrusted=True):
        assert save.effective_risk(args) is R2
    assert save.effective_risk(args) is R2


# ---- LOW: no scope, no owner → fail closed --------------------------------------------------


@pytest.mark.parametrize("scope", [None, "", ":s1"])
async def test_an_owner_rules_gateway_without_an_owner_fails_closed(scope: str | None) -> None:
    world = InMemoryWorld()
    gw = _gw(*builtin_tools(world))
    out = await gw.execute(REMIND, scope=scope)
    assert out.outcome is GatewayOutcome.ERROR and world.reminders == []
    assert "permission" in (out.error or "")
