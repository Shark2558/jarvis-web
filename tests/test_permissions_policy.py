# tests/test_permissions_policy.py — owner permission groups → policy rules → gateway (slice 10 D).
# Written before the implementation: the group catalogue, the R3 "never Allow" invariant, deny
# results the model can read, the rule source in the audit, fail-closed rule reads, and that rules
# never relax the spoken-turn or tainted-round protections.
from __future__ import annotations

from typing import Any

import pytest

from jarvis.core.guardrails import ActionRisk, ConfirmationGate
from jarvis.permissions.groups import (
    GROUPS,
    PermissionRejected,
    group_ids,
    groups_for,
    inherited_ids,
    pinned,
    rules_for,
    stored_choices,
)
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
    # slice 11 fix HIGH-1: the owner's own event's delete is undo-able (R2) and has its own row
    # ("Delete your own events"), so a Never on it keeps blocking; a shared / repeating one (R3)
    # is only in the ask-first row. "Add and change" never matches a delete.
    ("calendar_delete_event", R2, {"calendar_remove"}),
    ("calendar_delete_event", R3, {"calendar_delete"}),
    # a restore brings back an event or a to-do: both "change" rows (strictest wins)
    ("deleted_restore", R2, {"calendar_change", "todo_change"}),
    ("deleted_list", R1, {"calendar_read"}),
    ("reminder_add", R2, {"reminders"}),  # slice 11 B: its own row, after the Calendar rows
    ("reminder_update", R2, {"reminders"}),
    ("reminders_list", R1, {"reminders"}),
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
    ("task_delete", R2, {"todo_remove"}),  # slice 11: undo-able, its own row
    ("task_delete", R3, {"todo_delete"}),  # assigned from Docs / Chat
    ("memory_save", R2, {"memory_save"}),
    ("memory_save", R3, {"memory_save"}),  # tainted round
    ("memory_forget", R3, {"memory_forget"}),
    ("web_search", R1, {"web"}),
    ("web_read", R1, {"web"}),
    ("doc_read", R1, {"documents"}),
    ("doc_search", R1, {"documents"}),
    # slice 12 D8: one R1 row per integration (Drive, Maps, YouTube built in parallel)
    ("drive_folders", R1, {"drive"}),
    ("drive_list", R1, {"drive"}),
    ("drive_search", R1, {"drive"}),
    ("drive_read", R1, {"drive"}),
    ("maps_search", R1, {"maps"}),
    ("maps_route", R1, {"maps"}),
    ("youtube_search", R1, {"youtube"}),
    ("youtube_my_playlists", R1, {"youtube"}),
    ("youtube_playlist", R1, {"youtube"}),
    ("contacts_search", R1, {"contacts"}),
    ("whatsapp_draft", R1, {"whatsapp"}),
    ("whatsapp_draft", R2, {"whatsapp"}),  # a future write in the family is covered too
    # R3 I0: the home and camera rows (tools under their planned names)
    ("home_status", R1, {"home_read"}),
    ("home_devices", R1, {"home_read"}),
    ("home_control", R2, {"home_control"}),
    ("home_control", R3, {"home_secure"}),  # a lock, gate, alarm or heater
    ("home_arm", R2, {"home_arm"}),
    ("home_disarm", R3, {"home_secure"}),
    ("camera_history", R1, {"camera"}),
    ("faces_list", R1, {"camera"}),
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


def test_irreversible_groups_match_only_irreversible_calls() -> None:
    """Slice 11 D5: an R2 (undo-able) delete never lands in an Ask-first R3 group."""
    for g in GROUPS:
        if g.irreversible:
            assert g.matchers and all(m.risks == frozenset({R3}) for m in g.matchers), g.id
            assert not g.matches("calendar_delete_event", R2)
            assert not g.matches("task_delete", R2)


def test_slice_11_rows_read_as_planned() -> None:
    by_id = {g.id: g for g in GROUPS}
    cal, remove = by_id["calendar_change"], by_id["calendar_remove"]
    shared = by_id["calendar_delete"]
    assert cal.label == "Add and change your events" and cal.risk is R2
    assert remove.label == "Delete your own events — kept 30 days in Recently deleted"
    assert remove.risk is R2 and "undo" in remove.hint.lower()
    assert shared.irreversible and "Invite people" in shared.label
    assert "delete" in shared.label.lower() and "can't be undone" in shared.label
    todo, todo_rm, assigned = by_id["todo_change"], by_id["todo_remove"], by_id["todo_delete"]
    assert todo.label == "Read and change your to-dos" and todo.risk is R2
    assert todo_rm.label == "Delete your own to-dos — kept 30 days" and todo_rm.risk is R2
    assert assigned.irreversible and "can't be undone" in assigned.label
    assert "Docs or Chat" in assigned.hint
    for g in (cal, remove, todo, todo_rm):  # R2 defaults stay Allow: the owner's "all rights"
        assert g.default is Effect.ALLOW
    order = group_ids()
    assert order.index("calendar_change") < order.index("calendar_remove")
    assert order.index("calendar_remove") < order.index("calendar_delete")
    assert order.index("todo_change") < order.index("todo_remove") < order.index("todo_delete")


def test_the_change_rows_never_match_a_delete() -> None:
    """Slice 11 fix HIGH-1: Allow on "Add and change" must not let through a delete the owner
    switched off, and Never on it must not block deletes the owner allowed."""
    by_id = {g.id: g for g in GROUPS}
    for risk in (R2, R3):
        assert not by_id["calendar_change"].matches("calendar_delete_event", risk)
        assert not by_id["todo_change"].matches("task_delete", risk)
    assert by_id["calendar_change"].matches("calendar_some_new_tool", R2)  # catch-all kept
    assert by_id["todo_change"].matches("task_some_new_tool", R2)


@pytest.mark.parametrize(
    ("old", "new"), [("calendar_delete", "calendar_remove"), ("todo_delete", "todo_remove")]
)
def test_an_earlier_never_on_deletes_carries_over_to_the_new_delete_row(old: str, new: str) -> None:
    """Before slice 11 every delete was in the R3 row: an owner who set it to Never meant "never
    delete". Until they set the new R2 row themselves it reads as Never too."""
    assert stored_choices({old: "deny"})[new] is Effect.DENY
    assert new not in stored_choices({old: "ask"})
    assert stored_choices({old: "deny", new: "allow"})[new] is Effect.ALLOW  # their own choice
    assert stored_choices({old: "deny", new: "ask"})[new] is Effect.ASK
    tool = TOOL_OF[new]
    assert Policy(rules_for({old: Effect.DENY})).decide(tool, R2, {}) is Effect.DENY
    assert Policy(rules_for({old: Effect.ASK})).decide(tool, R2, {}) is Effect.ALLOW


def test_a_write_pins_the_new_delete_rows_so_a_later_never_does_not_spread() -> None:
    """Once the owner's choices are written after the split, the new rows are stored explicitly:
    a Never set on the R3 row afterwards means only what that row says."""
    written = pinned({"web": Effect.DENY})
    assert written["calendar_remove"] is Effect.ALLOW and written["todo_remove"] is Effect.ALLOW
    raw = {k: v.value for k, v in {**written, "calendar_delete": Effect.DENY}.items()}
    assert stored_choices(raw)["calendar_remove"] is Effect.ALLOW
    kept = pinned(stored_choices({"calendar_delete": "deny"}))  # an inherited Never is kept
    assert kept["calendar_remove"] is Effect.DENY
    assert inherited_ids({"calendar_delete": "deny"}) == {"calendar_remove"}
    assert inherited_ids({"calendar_delete": "deny", "calendar_remove": "allow"}) == set()


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
    "calendar_remove": [R2],
    "calendar_delete": [R3],
    "reminders": [R1, R2],
    "email_read": [R1],
    "email_draft": [R2],
    "email_send": [R3],
    "todo_change": [R1, R2],
    "todo_remove": [R2],
    "todo_delete": [R3],
    "memory_save": [R2, R3],
    "memory_forget": [R3],
    "web": [R1],
    "documents": [R1],
    "drive": [R1],  # slice 12 D8
    "maps": [R1],
    "youtube": [R1],
    "contacts": [R1],
    "whatsapp": [R1],
    "groceries": [R1, R2],  # R1 I0
    "family_read": [R1],
    "family_change": [R3],
    "vault_read": [R1],  # R2 I0
    "vault_change": [R2],
    "notes_read": [R1],
    "notes_change": [R2],
    "belongings": [R1, R2],
    "home_read": [R1],  # R3 I0
    "home_control": [R2],
    "home_arm": [R2],
    "home_secure": [R3],
    "camera": [R1],
    # R4 I0
    "vitals": [R1],
    "vitals_change": [R2],
    "systems": [R1],
    "people": [R1],
    "connectors": [R1],
}
TOOL_OF = {
    "calendar_read": "calendar_list_events",
    "calendar_change": "calendar_create_event",
    "calendar_remove": "calendar_delete_event",
    "calendar_delete": "calendar_delete_event",
    "reminders": "reminder_add",
    "email_read": "gmail_read",
    "email_draft": "gmail_create_draft",
    "email_send": "gmail_send",
    "todo_change": "task_add",
    "todo_remove": "task_delete",
    "todo_delete": "task_delete",
    "memory_save": "memory_save",
    "memory_forget": "memory_forget",
    "web": "web_search",
    "documents": "doc_read",
    "drive": "drive_read",
    "maps": "maps_route",
    "youtube": "youtube_search",
    "contacts": "contacts_search",
    "whatsapp": "whatsapp_draft",
    "groceries": "grocery_add",
    "family_read": "family_free_slots",
    "family_change": "family_event_add",
    "vault_read": "vault_list",
    "vault_change": "vault_set_dates",
    "notes_read": "kb_search",
    "notes_change": "kb_update",
    "belongings": "belongings_put",
    "home_read": "home_status",  # R3 I0
    "home_control": "home_control",
    "home_arm": "home_arm",
    "home_secure": "home_disarm",
    "camera": "camera_history",
    # R4 I0 (stub tools under the planned names)
    "vitals": "vitals_show",
    "vitals_change": "vitals_set_key",
    "systems": "systems_check",
    "people": "research_person",
    "connectors": "connect_github",
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
