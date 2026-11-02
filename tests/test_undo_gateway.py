# tests/test_undo_gateway.py — slice 11 D3 + the gateway hooks undo-able deletes need: at most 10
# undo-able deletes run without a card per owner message (then each is an R2 card, which the
# 5-new-cards budget bounds), and a tool can tell whether the owner approved the call it runs.
from __future__ import annotations

import json
from typing import Any

from jarvis.config import Settings
from jarvis.core.guardrails import ActionRisk, ConfirmationGate
from jarvis.llm.base import ToolCall
from jarvis.storage.docs import MemoryDocs
from jarvis.tools.audit import AuditLog
from jarvis.tools.base import Tool
from jarvis.tools.budget import MAX_FREE_DELETES, MAX_NEW_CARDS, turn_budget
from jarvis.tools.context import current_tool_context
from jarvis.tools.gateway import Gateway, GatewayOutcome
from jarvis.tools.policy import Policy
from jarvis.tools.registry import ToolRegistry
from jarvis.tools.setup import build_gateway
from jarvis.undo.service import UndoBin
from jarvis.undo.store import DeletedStore

SCOPE = "u1:sess_1"


class Ran:
    def __init__(self) -> None:
        self.calls: list[tuple[dict[str, Any], bool]] = []

    def __call__(self, args: dict[str, Any]) -> dict[str, Any]:
        ctx = current_tool_context()
        self.calls.append((args, bool(ctx and ctx.confirmed)))
        return {"ok": True}


def _gw(*tools: Tool) -> Gateway:
    reg = ToolRegistry()
    for t in tools:
        reg.register(t)
    return Gateway(registry=reg, policy=Policy(), gate=ConfirmationGate(), audit=AuditLog())


def _tool(name: str, ran: Ran, *, undoable: bool, risk: ActionRisk = ActionRisk.REVERSIBLE) -> Tool:
    return Tool(
        name,
        "test",
        {"type": "object", "properties": {"n": {"type": "integer"}}},
        risk,
        ran,
        undoable=undoable,
        summary_template="Delete item {n}",
    )


async def _call(gw: Gateway, name: str, n: int, **kw: Any) -> Any:
    return await gw.execute(ToolCall(id=f"c{n}", name=name, arguments={"n": n}), scope=SCOPE, **kw)


def test_the_cap_is_ten() -> None:
    assert MAX_FREE_DELETES == 10 and MAX_NEW_CARDS == 5


async def test_eleventh_undoable_delete_in_one_message_becomes_an_r2_card() -> None:
    ran = Ran()
    gw = _gw(_tool("thing_delete", ran, undoable=True))
    with turn_budget():
        outs = [await _call(gw, "thing_delete", n) for n in range(12)]
    assert [o.outcome for o in outs[:10]] == [GatewayOutcome.EXECUTED] * 10
    assert [o.outcome for o in outs[10:]] == [GatewayOutcome.AWAITING_CONFIRMATION] * 2
    assert len(ran.calls) == 10
    card = outs[10].pending
    assert card is not None and card.tool_risk is ActionRisk.REVERSIBLE  # no passkey
    said = json.loads(outs[10].for_model())
    assert said["status"] == "awaiting_owner_approval"
    assert "10" in said["why"] and "approval" in said["why"]


async def test_past_the_card_budget_the_rest_are_refused_in_plain_words() -> None:
    ran = Ran()
    gw = _gw(_tool("thing_delete", ran, undoable=True))
    with turn_budget():
        outs = [await _call(gw, "thing_delete", n) for n in range(17)]
    kinds = [o.outcome for o in outs]
    assert kinds.count(GatewayOutcome.EXECUTED) == 10
    assert kinds.count(GatewayOutcome.AWAITING_CONFIRMATION) == 5
    assert kinds[15:] == [GatewayOutcome.DENIED] * 2
    assert "Too many approvals" in (outs[16].error or "")


async def test_a_new_message_gets_a_fresh_allowance_and_outside_a_turn_there_is_no_cap() -> None:
    ran = Ran()
    gw = _gw(_tool("thing_delete", ran, undoable=True))
    with turn_budget():
        for n in range(10):
            await _call(gw, "thing_delete", n)
    with turn_budget():
        assert (await _call(gw, "thing_delete", 99)).outcome is GatewayOutcome.EXECUTED
    for n in range(12):  # no turn: e.g. a script
        assert (await _call(gw, "thing_delete", n)).outcome is GatewayOutcome.EXECUTED


async def test_other_writes_do_not_count_against_the_delete_allowance() -> None:
    ran = Ran()
    gw = _gw(_tool("thing_add", ran, undoable=False), _tool("thing_delete", ran, undoable=True))
    with turn_budget():
        for n in range(15):
            assert (await _call(gw, "thing_add", n)).outcome is GatewayOutcome.EXECUTED
        assert (await _call(gw, "thing_delete", 1)).outcome is GatewayOutcome.EXECUTED


async def test_an_approved_card_runs_and_the_tool_knows_it_was_approved() -> None:
    ran = Ran()
    gw = _gw(_tool("thing_delete", ran, undoable=True))
    with turn_budget():
        for n in range(10):
            await _call(gw, "thing_delete", n)
        card = (await _call(gw, "thing_delete", 10)).pending
    assert card is not None
    ok = await _call(gw, "thing_delete", 10, confirmation_id=card.id)  # the owner's approve
    assert ok.outcome is GatewayOutcome.EXECUTED
    assert [c for _, c in ran.calls] == [False] * 10 + [True]


async def test_the_tool_knows_the_risk_it_was_approved_at() -> None:
    """Slice 11 fix (LOW): the tool sees the risk the gateway decided on (the card's risk for
    an approved call), so a tool that finds more at run time (an event that gained guests) can
    refuse instead of doing more than the owner approved."""
    seen: list[tuple[ActionRisk | None, bool]] = []

    def run(args: dict[str, Any]) -> dict[str, Any]:
        ctx = current_tool_context()
        assert ctx is not None
        seen.append((ctx.approved_risk, ctx.confirmed))
        return {"ok": True}

    r2 = Tool("thing_delete", "t", {"type": "object"}, ActionRisk.REVERSIBLE, run, undoable=True)
    r3 = Tool("thing_send", "t", {"type": "object"}, ActionRisk.IRREVERSIBLE, run)
    gw = _gw(r2, r3)
    await gw.execute(ToolCall(id="a", name="thing_delete", arguments={}), scope=SCOPE)
    card = (
        await gw.execute(ToolCall(id="b", name="thing_send", arguments={}), scope=SCOPE)
    ).pending
    assert card is not None
    await gw.execute(
        ToolCall(id="b", name="thing_send", arguments={}), scope=SCOPE, confirmation_id=card.id
    )
    assert seen == [(ActionRisk.REVERSIBLE, False), (ActionRisk.IRREVERSIBLE, True)]


async def test_the_undo_tools_join_only_with_the_google_tools(settings: Settings) -> None:
    """Restore needs the Google tools' restorers: without a Google link there is nothing the
    model could restore, so deleted_list / deleted_restore aren't offered."""
    from tasks_fakes import FakeTasks, tasks_connector

    undo = UndoBin(DeletedStore(MemoryDocs()))
    alone = build_gateway(settings, undo=undo)
    assert (
        alone.registry.get("deleted_restore") is None and alone.registry.get("deleted_list") is None
    )
    linked = build_gateway(settings, undo=undo, google=await tasks_connector(FakeTasks()))
    assert linked.registry.get("deleted_restore") is not None


async def test_undo_chips_come_only_from_tools_marked_undoable() -> None:
    """A result that merely LOOKS like a delete's (a page, a mail, a tool echoing text) never
    puts an Undo chip under the reply."""
    from jarvis.core.rounds import undo_refs

    fake = {"deleted": True, "undo_id": "del_0123456789abcdef0123", "kind": "event"}
    echo = Tool("web_read", "t", {"type": "object"}, ActionRisk.READ_ONLY, lambda a: fake)
    real = Tool("thing_delete", "t", {"type": "object"}, ActionRisk.REVERSIBLE, lambda a: fake,
                undoable=True)  # fmt: skip
    gw = _gw(echo, real)
    calls = [ToolCall(id=n, name=n, arguments={}) for n in ("web_read", "thing_delete")]
    results = [await gw.execute(c, scope=SCOPE) for c in calls]
    refs = undo_refs(gw.registry, calls, results)
    assert [r.undo_id for r in refs] == ["del_0123456789abcdef0123"]  # the delete's only
    assert undo_refs(gw.registry, calls[:1], results[:1]) == []


async def test_an_argument_check_that_overflows_is_an_error_not_a_crash() -> None:
    def check(args: dict[str, Any]) -> None:
        raise OverflowError("date value out of range")

    tool = Tool("thing_add", "t", {"type": "object"}, ActionRisk.REVERSIBLE, Ran(), check=check)
    out = await _gw(tool).execute(ToolCall(id="o", name="thing_add", arguments={}), scope=SCOPE)
    assert out.outcome is GatewayOutcome.ERROR
