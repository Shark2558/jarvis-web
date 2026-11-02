# tests/test_permissions_policy.py — owner permission groups → policy rules → gateway (slice 10 D).
# Written before the implementation: the group catalogue, the R3 "never Allow" invariant, deny
# results the model can read, the rule source in the audit, fail-closed rule reads, and that rules
# never relax the spoken-turn or tainted-round protections.
from __future__ import annotations

from typing import Any

import pytest

from jarvis.core.guardrails import ActionRisk, ConfirmationGate
from jarvis.permissions.groups import GROUPS, PermissionRejected, group_ids, groups_for, rules_for
from jarvis.permissions.groups import validate_choices as validate
from jarvis.tools.audit import AuditLog
from jarvis.tools.base import Tool, ToolCall
from jarvis.tools.builtin import InMemoryWorld, builtin_tools
from jarvis.tools.gateway import Gateway, GatewayOutcome
from jarvis.tools.policy import Effect, Policy, PolicyRule
from jarvis.tools.registry import ToolRegistry
from jarvis.tools.taint import context_trust

R1, R2, R3 = ActionRisk.READ_ONLY, ActionRisk.REVERSIBLE, ActionRisk.IRREVERSIBLE

# Every tool in the registry today and the ones the parallel builders add (B web, C tasks, E docs):
# (tool, effective risk) → the groups it must fall into.
EXPECTED: list[tuple[str, ActionRisk, set[str]]] = [
    ("calendar_list_events", R1, {"calendar_read"}),
    ("calendar_free_slots", R1, {"calendar_read"}),
    ("get_calendar", R1, {"calendar_read"}),
    ("calendar_create_event", R2, {"calendar_change"}),
    ("calendar_create_event", R3, {"calendar_change", "calendar_delete"}),  # with attendees
    ("calendar_update_event", R2, {"calendar_change"}),
    ("calendar_update_event", R3, {"calendar_change", "calendar_delete"}),
    ("calendar_delete_event", R3, {"calendar_delete"}),
    ("gmail_search", R1, {"email_read"}),
    ("gmail_read", R1, {"email_read"}),
    ("gmail_create_draft", R2, {"email_draft"}),
    ("gmail_send", R3, {"email_send"}),
    ("send_message", R3, {"email_send"}),
    ("tasks_list", R1, {"todo_change"}),
    ("list_tasks", R1, {"todo_change"}),
    ("task_add", R2, {"todo_change"}),
    ("task_update", R2, {"todo_change"}),
    ("task_complete", R2, {"todo_change"}),
    ("create_reminder", R2, {"todo_change"}),
    ("task_delete", R3, {"todo_change", "todo_delete"}),
    ("memory_save", R2, {"memory_save"}),
    ("memory_save", R3, {"memory_save"}),  # tainted round
    ("memory_forget", R3, {"memory_forget"}),
    ("web_search", R1, {"web"}),
    ("web_read", R1, {"web"}),
    ("doc_read", R1, {"documents"}),
    ("doc_search", R1, {"documents"}),
    ("memory_search", R1, set()),  # unknown to every group: the risk default applies
    ("brand_new_tool", R3, set()),
]


@pytest.mark.parametrize(("tool", "risk", "want"), EXPECTED)
def test_every_known_tool_falls_into_the_right_groups(
    tool: str, risk: ActionRisk, want: set[str]
) -> None:
    assert {g.id for g in groups_for(tool, risk)} == want


def test_catalogue_has_the_planned_groups_and_irreversible_ones_offer_no_allow() -> None:
    ids = group_ids()
    assert len(ids) == len(set(ids)) == len(GROUPS) >= 9
    for g in GROUPS:
        assert g.label and g.hint and g.section
        if g.irreversible:
            assert g.choices == (Effect.ASK, Effect.DENY) and g.default is Effect.ASK
        else:
            assert g.choices == (Effect.ALLOW, Effect.ASK, Effect.DENY)
            assert g.default is Effect.ALLOW
    irreversible = {g.id for g in GROUPS if g.irreversible}
    assert {"calendar_delete", "email_send", "todo_delete", "memory_forget"} <= irreversible


def test_validate_refuses_allow_for_irreversible_groups_unknown_groups_and_effects() -> None:
    assert validate({"web": "deny", "email_send": "ask"}) == {
        "web": Effect.DENY,
        "email_send": Effect.ASK,
    }
    with pytest.raises(PermissionRejected, match="always asks first"):
        validate({"email_send": "allow"})
    with pytest.raises(PermissionRejected):
        validate({"no_such_group": "deny"})
    with pytest.raises(PermissionRejected):
        validate({"web": "sometimes"})
    with pytest.raises(PermissionRejected):
        validate({"web": None})  # type: ignore[dict-item]


def test_rules_for_never_carries_an_allow_for_an_irreversible_group() -> None:
    # a hand-edited stored "allow" for an R3 group is dropped, never turned into a rule
    rules = rules_for({"email_send": Effect.ALLOW, "web": Effect.DENY})
    assert all(r.source == "owner:web" for r in rules)
    assert all(r.effect is Effect.DENY for r in rules)
    Policy(rules)  # constructs: no standing allow for an irreversible call


def test_policy_refuses_an_allow_rule_scoped_to_irreversible_calls() -> None:
    with pytest.raises(ValueError):
        Policy([PolicyRule(tool_pattern="x_*", effect=Effect.ALLOW, risks=[R2, R3])])


# ---- the full matrix: every group × every effect × every risk its tools can have ---------------

RISK_OF = {
    "calendar_read": [R1],
    "calendar_change": [R2, R3],
    "calendar_delete": [R3],
    "email_read": [R1],
    "email_draft": [R2],
    "email_send": [R3],
    "todo_change": [R1, R2],
    "todo_delete": [R3],
    "memory_save": [R2, R3],
    "memory_forget": [R3],
    "web": [R1],
    "documents": [R1],
}
TOOL_OF = {
    "calendar_read": "calendar_list_events",
    "calendar_change": "calendar_create_event",
    "calendar_delete": "calendar_delete_event",
    "email_read": "gmail_read",
    "email_draft": "gmail_create_draft",
    "email_send": "gmail_send",
    "todo_change": "task_add",
    "todo_delete": "task_delete",
    "memory_save": "memory_save",
    "memory_forget": "memory_forget",
    "web": "web_search",
    "documents": "doc_read",
}


def _expected(effect: Effect, risk: ActionRisk) -> Effect:
    if effect is Effect.DENY:
        return Effect.DENY
    if risk is R3:
        return Effect.ASK  # never relaxed
    return effect


MATRIX = [
    (gid, effect, risk)
    for gid in sorted(RISK_OF)
    for effect in (Effect.ALLOW, Effect.ASK, Effect.DENY)
    for risk in RISK_OF[gid]
]


@pytest.mark.parametrize(("gid", "effect", "risk"), MATRIX)
def test_policy_matrix(gid: str, effect: Effect, risk: ActionRisk) -> None:
    group = next(g for g in GROUPS if g.id == gid)
    if group.irreversible and effect is Effect.ALLOW:
        with pytest.raises(PermissionRejected):
            validate({gid: effect.value})
        return
    policy = Policy(rules_for(validate({gid: effect.value})))
    assert policy.decide(TOOL_OF[gid], risk, {}) is _expected(effect, risk)
    # nothing else changes
    assert Policy(rules_for({})).decide(TOOL_OF[gid], risk, {}) is _expected(group.default, risk)


def test_matrix_covers_every_group() -> None:
    assert set(RISK_OF) == set(group_ids()) == set(TOOL_OF)


# ---- the gateway applies the owner's rules per call ---------------------------------------------


class FakeRules:
    def __init__(self, by_user: dict[str, dict[str, Effect]] | None = None) -> None:
        self.by_user = by_user or {}
        self.calls: list[str] = []
        self.fail = False

    async def rules_for(self, user_id: str) -> list[PolicyRule]:
        self.calls.append(user_id)
        if self.fail:
            raise RuntimeError("firestore down")
        return rules_for(self.by_user.get(user_id, {}))


def _gw(world: InMemoryWorld, rules: Any) -> Gateway:
    reg = ToolRegistry()
    for t in builtin_tools(world):
        reg.register(t)
    return Gateway(
        registry=reg, policy=Policy(), gate=ConfirmationGate(), audit=AuditLog(), rules=rules
    )


REMIND = ToolCall(id="r1", name="create_reminder", arguments={"text": "call", "when": "17:00"})
SEND = ToolCall(id="s1", name="send_message", arguments={"to": "a@x.com", "body": "hi"})


async def test_owner_never_returns_a_plain_result_and_audits_the_rule_source() -> None:
    world = InMemoryWorld()
    gw = _gw(world, FakeRules({"u1": {"todo_change": Effect.DENY}}))
    out = await gw.execute(REMIND, scope="u1:s1")
    assert out.outcome is GatewayOutcome.DENIED and world.reminders == []
    assert "switched off by the owner in Permissions" in (out.error or "")
    assert "to-do" in (out.error or "").lower()
    body = out.for_model()
    assert "switched off by the owner in Permissions" in body
    entry = (await gw.audit.tail(1)).entries[-1]
    assert entry.outcome == "denied" and entry.detail == "policy:owner:todo_change"


async def test_rules_are_per_owner_from_the_tool_context() -> None:
    world = InMemoryWorld()
    rules = FakeRules({"u1": {"todo_change": Effect.DENY}})
    gw = _gw(world, rules)
    assert (await gw.execute(REMIND, scope="u2:s9")).outcome is GatewayOutcome.EXECUTED
    assert (await gw.execute(REMIND, scope="u1:s1")).outcome is GatewayOutcome.DENIED
    assert rules.calls == ["u2", "u1"]


async def test_owner_ask_first_turns_a_reversible_tool_into_a_card() -> None:
    world = InMemoryWorld()
    gw = _gw(world, FakeRules({"u1": {"todo_change": Effect.ASK}}))
    out = await gw.execute(REMIND, scope="u1:s1")
    assert out.outcome is GatewayOutcome.AWAITING_CONFIRMATION and world.reminders == []
    assert out.pending is not None and out.pending.tool_risk is R2
    ok = await gw.execute(REMIND, scope="u1:s1", confirmation_id=out.pending.id)
    assert ok.outcome is GatewayOutcome.EXECUTED and len(world.reminders) == 1


async def test_pending_action_records_the_true_risk_of_the_call() -> None:
    world = InMemoryWorld()
    gw = _gw(world, FakeRules())
    out = await gw.execute(SEND, scope="u1:s1")
    assert out.pending is not None and out.pending.tool_risk is R3


async def test_an_allow_never_relaxes_a_spoken_turn() -> None:
    world = InMemoryWorld()
    gw = _gw(world, FakeRules({"u1": {"todo_change": Effect.ALLOW}}))
    with context_trust(untrusted=False, spoken=True):
        out = await gw.execute(REMIND, scope="u1:s1")
    assert out.outcome is GatewayOutcome.AWAITING_CONFIRMATION and world.reminders == []


async def test_an_allow_never_relaxes_a_tainted_memory_save() -> None:
    ran: list[dict[str, Any]] = []

    def _risk(a: dict[str, Any]) -> ActionRisk:
        from jarvis.tools.taint import untrusted_in_context

        return R3 if untrusted_in_context() else R2

    reg = ToolRegistry()
    reg.register(
        Tool(
            "memory_save",
            "save",
            {"type": "object", "properties": {"text": {"type": "string"}}},
            R2,
            ran.append,
            risk_for=_risk,
        )
    )
    gw = Gateway(
        registry=reg,
        policy=Policy(),
        gate=ConfirmationGate(),
        audit=AuditLog(),
        rules=FakeRules({"u1": {"memory_save": Effect.ALLOW}}),
    )
    call = ToolCall(id="m1", name="memory_save", arguments={"text": "x"})
    with context_trust(untrusted=True):
        out = await gw.execute(call, scope="u1:s1")
    assert out.outcome is GatewayOutcome.AWAITING_CONFIRMATION and ran == []
    with context_trust(untrusted=False):
        assert (await gw.execute(call, scope="u1:s1")).outcome is GatewayOutcome.EXECUTED


async def test_never_applies_to_an_approved_card_when_the_owner_switches_it_off_meanwhile() -> None:
    world = InMemoryWorld()
    rules = FakeRules()
    gw = _gw(world, rules)
    out = await gw.execute(SEND, scope="u1:s1")
    assert out.pending is not None
    rules.by_user["u1"] = {"email_send": Effect.DENY}
    again = await gw.execute(SEND, scope="u1:s1", confirmation_id=out.pending.id)
    assert again.outcome is GatewayOutcome.DENIED and world.sent == []


async def test_unreadable_rules_fail_closed() -> None:
    world = InMemoryWorld()
    rules = FakeRules()
    rules.fail = True
    gw = _gw(world, rules)
    out = await gw.execute(REMIND, scope="u1:s1")
    assert out.outcome is GatewayOutcome.ERROR and world.reminders == []
    assert "permission" in (out.error or "").lower()
    entry = (await gw.audit.tail(1)).entries[-1]
    assert entry.outcome == "error" and "permissions" in entry.detail


async def test_without_a_rule_source_the_base_policy_applies_but_no_owner_fails_closed() -> None:
    plain = _gw(InMemoryWorld(), None)
    assert (await plain.execute(REMIND, scope="u1:s1")).outcome is GatewayOutcome.EXECUTED
    assert (await plain.execute(REMIND)).outcome is GatewayOutcome.EXECUTED
    # with owner rules, a call that names no owner can't be checked against them: nothing runs
    world = InMemoryWorld()
    rules = FakeRules({"u1": {"todo_change": Effect.DENY}})
    out = await _gw(world, rules).execute(REMIND)
    assert out.outcome is GatewayOutcome.ERROR and world.reminders == [] and rules.calls == []


async def test_a_config_deny_still_says_blocked_by_policy() -> None:
    world = InMemoryWorld()
    reg = ToolRegistry()
    for t in builtin_tools(world):
        reg.register(t)
    gw = Gateway(
        registry=reg,
        policy=Policy([PolicyRule(tool_pattern="send_*", effect=Effect.DENY)]),
        gate=ConfirmationGate(),
        audit=AuditLog(),
        rules=FakeRules(),
    )
    out = await gw.execute(SEND, scope="u1:s1")
    assert out.outcome is GatewayOutcome.DENIED and out.error == "blocked by policy"
    assert (await gw.audit.tail(1)).entries[-1].detail == "policy:config"
