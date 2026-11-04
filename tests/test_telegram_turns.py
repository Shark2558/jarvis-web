# tests/test_telegram_turns.py -- R1 D2/D3/D5: the owner's Telegram conversation. Only the paired
# private chat reaches the brain; strangers get no reply and one audit line; replies are plain text.
from __future__ import annotations

from typing import Any

from telegram_fakes import OWNER_CHAT, OWNER_TG, STRANGER_TG, UID, World, build_world, message

from jarvis.core import channel
from jarvis.core.guardrails import ActionRisk
from jarvis.llm.base import ToolCall
from jarvis.telegram.service import MAX_MESSAGES_PER_WINDOW, REJECTED_AUDIT_PER_HOUR
from jarvis.tools.base import Tool

R1 = ActionRisk.READ_ONLY


async def _paired() -> World:
    w = build_world()
    await w.pair()
    return w


async def test_the_owner_gets_an_answer_in_telegram() -> None:
    w = await _paired()
    w.provider.script("You have two meetings today.")
    await w.send(message(1, "what's on today?"))
    assert w.bot.texts == ["You have two meetings today."]
    assert w.bot.of("sendMessage")[0]["chat_id"] == OWNER_CHAT


async def test_the_request_is_a_telegram_channel_turn_for_the_owner() -> None:
    seen: list[Any] = []

    def probe(_: dict[str, Any]) -> dict[str, Any]:
        seen.append(channel.on_telegram())
        return {"ok": True}

    tool = Tool("probe", "probe", {"type": "object", "properties": {}}, R1, probe)
    w = build_world(extra_tools=[tool])
    await w.pair()
    w.provider.script_tool_calls([ToolCall(id="c1", name="probe", arguments={})], "done")
    await w.send(message(1, "probe it"))
    assert seen == [True] and channel.on_telegram() is False
    session = await w.brain.store.get_or_raise((await w.store.get(UID)).session_id)  # type: ignore[union-attr]
    assert session.user_id == UID and session.turns[0].channel == "telegram"


async def test_one_rolling_conversation_and_new_starts_fresh() -> None:
    w = await _paired()
    await w.send(message(1, "first"))
    sid1 = (await w.store.get(UID)).session_id  # type: ignore[union-attr]
    await w.send(message(2, "second"))
    assert (await w.store.get(UID)).session_id == sid1  # type: ignore[union-attr]
    assert len((await w.brain.store.get_or_raise(sid1)).turns) == 4
    await w.send(message(3, "/new"))
    assert (await w.store.get(UID)).session_id is None  # type: ignore[union-attr]
    assert "fresh" in w.bot.texts[-1].lower()
    await w.send(message(4, "third"))
    sid2 = (await w.store.get(UID)).session_id  # type: ignore[union-attr]
    assert sid2 and sid2 != sid1


async def test_a_stranger_is_rejected_audited_and_never_reaches_the_brain() -> None:
    w = await _paired()
    await w.send(message(1, "give me the owner's mail", user=STRANGER_TG, chat=STRANGER_TG))
    assert w.bot.calls == [] and w.provider.calls == []
    [e] = w.audited("telegram_rejected")
    assert e.agent == "telegram" and e.outcome == "rejected"


async def test_unpaired_text_is_rejected_and_never_stored() -> None:
    w = build_world()
    await w.send(message(1, "hello is anyone there"))
    assert w.bot.calls == [] and w.provider.calls == []
    assert len(w.audited("telegram_rejected")) == 1
    assert "hello is anyone" not in str(w.docs._data)


async def test_right_user_wrong_chat_and_group_chats_are_rejected() -> None:
    w = await _paired()
    await w.send(message(1, "hi", chat=999))  # same user, another chat
    await w.send(message(2, "hi", chat=-100123, chat_type="group"))
    assert w.provider.calls == [] and w.bot.calls == []
    assert len(w.audited("telegram_rejected")) == 2


async def test_a_bot_sender_is_rejected() -> None:
    w = await _paired()
    await w.send(message(1, "hi", is_bot=True))
    assert w.provider.calls == [] and len(w.audited("telegram_rejected")) == 1


async def test_rejections_are_audited_at_most_20_an_hour_then_only_logged() -> None:
    w = build_world()
    for i in range(REJECTED_AUDIT_PER_HOUR + 15):
        await w.send(message(i + 1, "spam", user=STRANGER_TG, chat=STRANGER_TG))
    assert len(w.audited("telegram_rejected")) == REJECTED_AUDIT_PER_HOUR
    w.clock.advance(hours=1, minutes=1)
    await w.send(message(500, "spam", user=STRANGER_TG, chat=STRANGER_TG))
    assert len(w.audited("telegram_rejected")) == REJECTED_AUDIT_PER_HOUR + 1


async def test_pairing_through_the_start_link() -> None:
    w = build_world()
    code, _ = await w.store.start_pairing(UID)
    await w.send(message(1, f"/start {code}"))
    link = await w.store.get(UID)
    assert link is not None and link.tg_user_id == OWNER_TG and link.chat_id == OWNER_CHAT
    assert "paired" in w.bot.texts[-1].lower()
    assert len(w.audited("telegram_paired")) == 1
    assert w.provider.calls == []


async def test_a_wrong_start_code_gets_no_reply_and_is_audited() -> None:
    w = build_world()
    await w.store.start_pairing(UID)
    await w.send(message(1, "/start ZZZZZZZZ"))
    assert w.bot.calls == [] and await w.store.get(UID) is None
    assert len(w.audited("telegram_rejected")) == 1


async def test_a_group_chat_cannot_pair() -> None:
    w = build_world()
    code, _ = await w.store.start_pairing(UID)
    await w.send(message(1, f"/start {code}", chat=-5, chat_type="group"))
    assert await w.store.get(UID) is None


async def test_a_bot_cannot_pair() -> None:
    w = build_world()
    code, _ = await w.store.start_pairing(UID)
    await w.send(message(1, f"/start {code}", is_bot=True))
    assert await w.store.get(UID) is None


async def test_unpair_from_the_bound_account() -> None:
    w = await _paired()
    await w.send(message(1, "/unpair"))
    assert await w.store.get(UID) is None
    assert "unpaired" in w.bot.texts[-1].lower()
    assert len(w.audited("telegram_unpaired")) == 1
    await w.send(message(2, "hello again"))
    assert w.provider.calls == []


async def test_non_text_messages_get_a_plain_line() -> None:
    w = await _paired()
    await w.send(message(1, None))
    assert w.bot.texts == ["I can read text messages only for now."]
    assert w.provider.calls == []


async def test_a_duplicate_update_is_processed_once() -> None:
    w = await _paired()
    await w.send(message(1, "once"))
    await w.send(message(1, "once"))
    assert len(w.provider.calls) == 1 and len(w.bot.texts) == 1


async def test_offline_answers_are_marked() -> None:
    w = await _paired()
    orig = w.brain.chat

    async def chat(req: Any) -> Any:
        resp = await orig(req)
        return resp.model_copy(update={"offline": True})

    w.brain.chat = chat  # type: ignore[method-assign]
    await w.send(message(1, "hi"))
    assert w.bot.texts[0].startswith("(Offline — answered by your laptop)")


async def test_a_long_reply_is_split_into_at_most_three_messages() -> None:
    w = await _paired()
    w.provider.script("word " * 4000)  # 20,000 characters
    await w.send(message(1, "write a lot"))
    texts = w.bot.texts
    assert len(texts) == 3 and all(len(t) <= 4096 for t in texts)
    assert "the rest is in the console" in texts[-1]


async def test_twenty_messages_per_ten_minutes() -> None:
    w = await _paired()
    for i in range(MAX_MESSAGES_PER_WINDOW):
        await w.send(message(i + 1, "hi"))
    calls = len(w.provider.calls)
    await w.send(message(100, "one too many"))
    assert len(w.provider.calls) == calls
    assert "too many" in w.bot.texts[-1].lower() or "slow" in w.bot.texts[-1].lower()
    w.clock.advance(minutes=11)
    await w.send(message(101, "fine again"))
    assert len(w.provider.calls) == calls + 1


async def test_a_brain_failure_is_friendly_and_leaks_nothing() -> None:
    w = await _paired()

    async def boom(req: Any) -> Any:
        raise RuntimeError("secret internal detail " + "sk-ant-xyz")

    w.brain.chat = boom  # type: ignore[method-assign]
    await w.send(message(1, "hi"))
    assert len(w.bot.texts) == 1
    assert "secret" not in w.bot.texts[0] and "sk-ant" not in w.bot.texts[0]
    assert "try again" in w.bot.texts[0].lower()


async def test_a_too_long_message_is_refused_in_plain_words() -> None:
    w = await _paired()
    await w.send(message(1, "x" * 900))  # max_input_chars is 500 in tests
    assert w.provider.calls == []
    assert "too long" in w.bot.texts[-1].lower()


async def test_a_telegram_send_failure_does_not_raise() -> None:
    w = await _paired()
    w.bot.fail.add("sendMessage")
    await w.send(message(1, "hi"))  # must not raise


async def test_replies_are_plain_text_with_card_links() -> None:
    from jarvis.whatsapp.draft import WhatsAppCard

    w = await _paired()
    card = WhatsAppCard(
        name="Priya",
        number="+919876543210",
        text="Running late",
        link="https://wa.me/919876543210?text=Running%20late",
    )
    orig = w.brain.chat

    async def chat(req: Any) -> Any:
        resp = await orig(req)
        return resp.model_copy(update={"cards": [card]})

    w.brain.chat = chat  # type: ignore[method-assign]
    await w.send(message(1, "draft a message to Priya"))
    joined = "\n".join(w.bot.texts)
    assert "Open in WhatsApp: https://wa.me/919876543210?text=Running%20late" in joined
    assert all("parse_mode" not in p for p in w.bot.of("sendMessage"))
