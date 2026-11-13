# tests/test_r11_1_i1_telegram.py -- R11.1 I1 (INTEGRATION-A 3.10, plan D4): on Telegram a batch,
# undo or re-plan card (several lines) still gets NO button, but it now shows its first line,
# which code alone writes (how many, the dates), and points to the console for the list. Any other
# card too long for a phone keeps the plain "Approve in the console" with its tool's label.
from __future__ import annotations

from typing import Any

from telegram_fakes import build_world, message

from jarvis.core.guardrails import ActionRisk
from jarvis.llm.base import ToolCall
from jarvis.telegram.service import CONSOLE_FIRST, OPEN_TO_APPROVE
from jarvis.tools import Effect, Policy, PolicyRule, Tool

HEAD = "Add 60 events to your calendar: Mon 16 Nov 2026 - Sat 13 Feb 2027."
CARD = f"{HEAD}\nTitles start with “CCA - ”.\nOpen JARVIS to see the whole list."


def _tool(name: str, summary: str) -> Tool:
    async def run(_a: dict[str, Any]) -> dict[str, Any]:
        return {"message": "done"}

    return Tool(
        name,
        "test",
        {"type": "object", "properties": {}},
        ActionRisk.REVERSIBLE,
        run,
        summarize=lambda _a: summary,
    )


async def _card_on_telegram(name: str, summary: str) -> list[dict[str, Any]]:
    ask = Policy([PolicyRule(tool_pattern=name, effect=Effect.ASK, source="owner")])
    w = build_world(policy=ask, extra_tools=[_tool(name, summary)])
    await w.pair()
    w.provider.script_tool_calls([ToolCall(id="c1", name=name, arguments={})], "A card, Sir.")
    await w.send(message(1, "add my plan"))
    assert len(await w.gateway.pending()) == 1
    return w.bot.of("sendMessage")


async def test_a_batch_card_shows_its_code_written_first_line_and_no_button() -> None:
    sent = await _card_on_telegram("calendar_create_events", CARD)
    shown = [p for p in sent if HEAD in p["text"]]
    assert len(shown) == 1 and shown[0]["text"] == f"{HEAD} {OPEN_TO_APPROVE}"
    assert "reply_markup" not in shown[0]  # judged in the console, where the whole list shows
    assert not any("Titles start with" in p["text"] for p in sent)


async def test_another_long_card_keeps_the_plain_console_line() -> None:
    sent = await _card_on_telegram("create_note_batch", CARD)
    assert any(p["text"] == CONSOLE_FIRST + "create note batch" for p in sent)
    assert not any(HEAD in p["text"] for p in sent)


async def test_a_batch_card_whose_first_line_is_too_long_falls_back_to_the_label() -> None:
    long_head = "Add 60 events to your calendar: " + "x" * 400
    sent = await _card_on_telegram("calendar_create_events", f"{long_head}\nmore")
    assert any(p["text"] == CONSOLE_FIRST + "calendar create events" for p in sent)
