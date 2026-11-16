# tests/test_r13_i1_noai.py -- R13 I1 (INTEGRATION-D 6.7, D6, D10): No-AI's runner fills a
# `TakeCall` from the step before: "I put my watch in the travel bag" is `wardrobe_find`, then
# `wardrobe_edit` BY ID (the `best` the find named); when the find names no single piece nothing
# moves and the find's own words are the reply. No `query` ever reaches `wardrobe_edit`.
from __future__ import annotations

from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from jarvis.core.guardrails import ActionRisk, ConfirmationGate
from jarvis.offline import phrases_r13 as p13
from jarvis.offline.no_ai import run_no_ai
from jarvis.tools import AuditLog, Gateway, Policy, ToolRegistry
from jarvis.tools.base import Tool

NOW = datetime(2026, 11, 16, 23, 30, tzinfo=ZoneInfo("Asia/Kolkata"))
WATCH = "wi_" + "c" * 12


def _gateway(found: dict[str, Any]) -> tuple[Gateway, list[tuple[str, dict[str, Any]]]]:
    ran: list[tuple[str, dict[str, Any]]] = []
    reg = ToolRegistry()

    def tool(name: str, risk: ActionRisk) -> Tool:
        async def run(a: dict[str, Any]) -> dict[str, Any]:
            ran.append((name, dict(a)))
            return found if name == "wardrobe_find" else {"message": "Moved."}

        return Tool(
            name=name, description=name, input_schema={"type": "object"}, risk=risk, run=run
        )

    reg.register(tool("wardrobe_find", ActionRisk.READ_ONLY))
    reg.register(tool("wardrobe_edit", ActionRisk.REVERSIBLE))
    return Gateway(registry=reg, policy=Policy(), gate=ConfirmationGate(), audit=AuditLog()), ran


async def _run(found: dict[str, Any]) -> tuple[Any, list[tuple[str, dict[str, Any]]]]:
    gw, ran = _gateway(found)
    out = await run_no_ai(
        gw, "I put my watch in the travel bag", NOW, scope="u:s", extra=p13.ROUTERS
    )
    return out, ran


async def test_the_edit_takes_the_id_the_find_named_and_never_a_query() -> None:
    out, ran = await _run({"found": True, "best": WATCH, "message": "Found it."})
    assert [n for n, _ in ran] == ["wardrobe_find", "wardrobe_edit"]
    assert ran[1][1] == {"place": "travel bag", "piece": WATCH}
    assert "query" not in ran[1][1] and out.tool_calls == 2


async def test_when_the_find_names_no_single_piece_nothing_moves_and_its_words_are_the_reply() -> (
    None
):
    for found in (
        {"found": False, "candidates": [WATCH, "wi_" + "d" * 12], "message": "Which one: a or b?"},
        {"found": True, "best": None, "message": "Which one?"},
        {"found": True, "best": "", "message": "Which one?"},
    ):
        out, ran = await _run(found)
        assert [n for n, _ in ran] == ["wardrobe_find"], found  # the edit never ran
        assert out.tool_calls == 1 and out.reply  # the find's own words
