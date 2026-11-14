# tests/test_r14_i1_telegram_drill.py -- R14 I1 follow-up (integrated security review M4; the
# Workshop's decision: console only). The restore-drill card (`vitals_drill_start`, R2, always a
# card) is short enough for Telegram's one-tap Approve, so a forwarded message or a mail the model
# read could have him start a drill with one tap on a phone. It is never offered with buttons on
# Telegram: Telegram says plainly that it is approved in the console (Approvals), raises the
# usual "approval waiting" alert, and refuses an Approve or Decline button sent for it anyway.
from __future__ import annotations

from typing import Any

from telegram_fakes import World, build_world, callback, dev_settings, message

from jarvis.backup import part as backup_part
from jarvis.backup.names import START
from jarvis.backup.tools import NO_FIRESTORE_LINE, card_text
from jarvis.core.guardrails import CONSOLE_ONLY_TOOLS, NO_BULK_TOOLS
from jarvis.hardening.ports import HardeningContext
from jarvis.llm.base import ToolCall
from jarvis.storage.docs import MemoryDocs
from jarvis.telegram import service as tg
from jarvis.tools import Effect, Policy, PolicyRule


def _drill_tools() -> list[Any]:
    """The real drill tool (Part A's, off Firestore: approving it would only say so)."""
    ctx = HardeningContext(s=dev_settings(), docs=MemoryDocs(), audit=None, state=lambda _: None)
    return [t for t in backup_part.build(ctx).tools if t.name == START]


async def _drill_world() -> tuple[World, str]:
    w = build_world(extra_tools=_drill_tools())
    await w.pair()
    w.provider.script_tool_calls(
        [ToolCall(id="c1", name=START, arguments={})], "A drill needs your OK, Sir."
    )
    await w.send(message(1, "test my backup"))
    [card] = await w.gateway.pending()
    assert card.tool == START
    return w, card.id


def _buttons(w: World) -> list[dict[str, Any]]:
    return [p for p in w.bot.of("sendMessage") if "reply_markup" in p]


async def test_the_drill_card_is_short_enough_for_a_button_so_the_rule_matters() -> None:
    assert tg._fits(card_text(dev_settings()))  # without the rule it would get one tap


async def test_the_drill_card_never_gets_buttons_and_points_to_the_console() -> None:
    w, _ = await _drill_world()
    assert _buttons(w) == []
    joined = "\n".join(w.bot.texts)
    assert f"{tg.CONSOLE_APPROVES}vitals drill start" in joined
    assert "under Approvals" in tg.CONSOLE_APPROVES and "never approved from Telegram" in joined
    assert "Approve or decline?" not in joined
    assert len(w.audited("telegram_alert")) == 1  # the usual "approval waiting" alert
    assert len(await w.gateway.pending()) == 1  # still waiting, nothing asked for


async def test_an_approve_button_for_the_drill_is_refused_and_runs_nothing() -> None:
    w, cid = await _drill_world()
    w.provider.script("Done.")
    await w.send(callback(2, f"a:{cid}"))
    assert len(await w.gateway.pending()) == 1
    assert tg.CONSOLE_APPROVES in w.bot.texts[-1]
    assert all(NO_FIRESTORE_LINE not in t for t in w.bot.texts)  # the tool never ran
    await w.send(callback(3, f"d:{cid}"))  # nor declined away from a phone
    assert len(await w.gateway.pending()) == 1


async def test_other_r2_cards_keep_their_buttons() -> None:
    policy = Policy([PolicyRule(tool_pattern="create_reminder", effect=Effect.ASK, source="owner")])
    w = build_world(policy=policy)
    await w.pair()
    w.provider.script_tool_calls(
        [ToolCall(id="c1", name="create_reminder", arguments={"text": "tea", "when": "17:00"})],
        "In a card, Sir.",
    )
    await w.send(message(1, "remind me about tea at 5"))
    assert len(_buttons(w)) == 1


def test_the_console_only_set_is_the_drill_and_is_never_bulk() -> None:
    assert frozenset({START}) == CONSOLE_ONLY_TOOLS
    assert CONSOLE_ONLY_TOOLS <= NO_BULK_TOOLS
