# tests/test_telegram_approvals.py -- R1 D3: R2 cards proposed in the owner's Telegram conversation
# get Approve / Decline buttons; R3 is never approvable from Telegram.
from __future__ import annotations

from telegram_fakes import OWNER_CHAT, OWNER_TG, STRANGER_TG, World, build_world, callback, message

from jarvis.llm.base import ToolCall
from jarvis.tools import Effect, Policy, PolicyRule


def _ask_reminders() -> Policy:
    return Policy([PolicyRule(tool_pattern="create_reminder", effect=Effect.ASK, source="owner")])


async def _card_world() -> tuple[World, str]:
    w = build_world(policy=_ask_reminders())
    await w.pair()
    w.provider.script_tool_calls(
        [
            ToolCall(
                id="c1", name="create_reminder", arguments={"text": "call Ravi", "when": "17:00"}
            )
        ],
        "I've put that in a card, Sir.",
    )
    await w.send(message(1, "remind me to call Ravi at 5"))
    [card] = await w.gateway.pending()
    return w, card.id


async def test_an_r2_card_comes_with_approve_and_decline_buttons() -> None:
    w, cid = await _card_world()
    buttons = [p for p in w.bot.of("sendMessage") if "reply_markup" in p]
    assert len(buttons) == 1
    row = buttons[0]["reply_markup"]["inline_keyboard"][0]
    assert [b["callback_data"] for b in row] == [f"a:{cid}", f"d:{cid}"]
    assert "call Ravi" in buttons[0]["text"]
    assert w.things.reminders == []


async def test_the_bound_owner_can_approve() -> None:
    w, cid = await _card_world()
    w.provider.script("Done, Sir. Reminder set.")
    await w.send(callback(2, f"a:{cid}"))
    assert [r["text"] for r in w.things.reminders] == ["call Ravi"]
    assert w.bot.of("answerCallbackQuery")[0]["callback_query_id"] == "cb2"
    assert w.bot.of("editMessageReplyMarkup")  # the buttons go away
    assert "Reminder set" in w.bot.texts[-1]


async def test_decline_runs_nothing() -> None:
    w, cid = await _card_world()
    w.provider.script("Okay, dropped.")
    await w.send(callback(2, f"d:{cid}"))
    assert w.things.reminders == [] and await w.gateway.pending() == []


async def test_another_telegram_user_cannot_approve() -> None:
    w, cid = await _card_world()
    await w.send(callback(2, f"a:{cid}", user=STRANGER_TG, chat=STRANGER_TG))
    assert w.things.reminders == [] and len(await w.gateway.pending()) == 1
    assert len(w.audited("telegram_rejected")) == 1


async def test_the_owner_in_another_chat_cannot_approve() -> None:
    w, cid = await _card_world()
    await w.send(callback(2, f"a:{cid}", chat=OWNER_CHAT + 1))
    assert w.things.reminders == [] and len(w.audited("telegram_rejected")) == 1


async def test_a_card_from_another_conversation_is_refused() -> None:
    w, cid = await _card_world()
    await w.send(message(5, "/new"))
    w.provider.script("Fresh start.")
    await w.send(message(6, "hello"))
    await w.send(callback(7, f"a:{cid}"))
    assert w.things.reminders == []
    assert "console" in w.bot.texts[-1].lower() or "expired" in w.bot.texts[-1].lower()


async def test_r3_cards_wait_in_the_console_and_raise_an_alert() -> None:
    w = build_world()
    await w.pair()
    w.provider.script_tool_calls(
        [
            ToolCall(
                id="c1", name="send_message", arguments={"to": "priya@example.com", "body": "hi"}
            )
        ],
        "Ready to send, Sir; it needs your approval.",
    )
    await w.send(message(1, "send priya hi"))
    assert not any("reply_markup" in p for p in w.bot.of("sendMessage"))  # no buttons
    joined = "\n".join(w.bot.texts)
    assert "Waiting in the console for your approval (and passkey)" in joined
    alerts = [t for t in w.bot.texts if "approval" in t.lower() and "console" in t.lower()]
    assert len(alerts) >= 2  # the in-conversation line and the alert
    assert w.things.sent == []
    assert len(w.audited("telegram_alert")) == 1


async def test_a_forged_approve_of_an_r3_card_is_refused() -> None:
    w = build_world()
    await w.pair()
    w.provider.script_tool_calls(
        [
            ToolCall(
                id="c1", name="send_message", arguments={"to": "priya@example.com", "body": "hi"}
            )
        ],
        "Needs approval.",
    )
    await w.send(message(1, "send priya hi"))
    [card] = await w.gateway.pending()
    await w.send(callback(2, f"a:{card.id}"))
    assert w.things.sent == [] and len(await w.gateway.pending()) == 1
    assert "approve in the console" in w.bot.texts[-1].lower()
    # nor can it be declined away by a button: R3 is the console's alone
    await w.send(callback(3, f"d:{card.id}"))
    assert len(await w.gateway.pending()) == 1


async def test_bad_callback_data_is_ignored_politely() -> None:
    w = build_world(policy=_ask_reminders())
    await w.pair()
    for i, data in enumerate(["", "x:1", "a:", "a:../../etc", "a:" + "x" * 500, "garbage"]):
        await w.send(callback(10 + i, data))
    assert w.things.reminders == [] and w.provider.calls == []
    assert len(w.bot.of("answerCallbackQuery")) == 6


async def test_an_approved_card_cannot_be_approved_twice() -> None:
    w, cid = await _card_world()
    w.provider.script("Done.")
    await w.send(callback(2, f"a:{cid}"))
    await w.send(callback(3, f"a:{cid}"))
    assert len(w.things.reminders) == 1
    assert "already" in w.bot.texts[-1].lower()


async def test_the_owner_id_is_what_is_checked() -> None:
    w, cid = await _card_world()
    assert OWNER_TG != STRANGER_TG
    await w.send(callback(2, f"a:{cid}", user=OWNER_TG))
    assert len(w.things.reminders) == 1
