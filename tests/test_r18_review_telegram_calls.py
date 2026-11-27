# tests/test_r18_review_telegram_calls.py -- R18 combined review: Telegram never approves a call.
# `calls_place` is R3 (Telegram already never approves R3), and the review puts it among the
# console-only tools as well, so a forged or old Approve button can't place a call even if the R3
# rule were switched off (its eval's negative control does that): the card waits in the console
# (Calls or Approvals), where his passkey can be asked.
from __future__ import annotations

import pytest
from calls_a1_fakes import NUMBER, known, rig
from telegram_fakes import UID, build_world, callback, message

from jarvis.calls.tools import PLACE, calls_tools
from jarvis.core.guardrails import CONSOLE_ONLY_TOOLS, NO_BULK_TOOLS
from jarvis.llm.base import ToolCall
from jarvis.telegram import service as tg

ARGS = {"number": NUMBER, "purpose": "Book a laundry pickup", "languages": ["en-IN"]}


async def _world() -> tuple[object, object, str]:
    r = await rig(uid=UID)
    await known(r.store, uid=UID)
    w = build_world(extra_tools=list(calls_tools(r.service)))
    await w.pair()
    w.provider.script_tool_calls(
        [ToolCall(id="c1", name=PLACE, arguments=ARGS)], "A call card is waiting, Sir."
    )
    await w.send(message(1, "call the laundry for a pickup"))
    [card] = await w.gateway.pending()
    assert card.tool == PLACE
    return w, r, card.id


def test_review_calls_place_is_console_only_and_never_bulk() -> None:
    assert PLACE in CONSOLE_ONLY_TOOLS and PLACE in NO_BULK_TOOLS


async def test_review_a_call_card_gets_no_buttons_on_telegram() -> None:
    w, _, _ = await _world()
    assert [p for p in w.bot.of("sendMessage") if "reply_markup" in p] == []
    joined = "\n".join(w.bot.texts)
    assert f"{tg.CONSOLE_APPROVES}calls place" in joined
    assert NUMBER not in joined and NUMBER[-4:] not in joined  # not even the card's words


@pytest.mark.parametrize("r3_rule_on", [True, False])
async def test_review_an_approve_button_for_a_call_places_nothing(
    monkeypatch: pytest.MonkeyPatch, r3_rule_on: bool
) -> None:
    monkeypatch.setattr(tg, "R3_REFUSAL", r3_rule_on)  # the console-only rule holds either way
    w, r, cid = await _world()
    w.provider.script("Placing it.")
    await w.send(callback(2, f"a:{cid}"))
    assert len(await w.gateway.pending()) == 1  # still waiting in the console
    assert r.starter.started == []  # nothing dialled, no grant
    assert r.service.grants._grants == {}  # no dial grant was issued


def test_review_the_guardrails_name_is_the_calls_tool() -> None:
    from jarvis.core.guardrails import CALLS_PLACE

    assert CALLS_PLACE == PLACE  # the literal in core follows the tool's own name
