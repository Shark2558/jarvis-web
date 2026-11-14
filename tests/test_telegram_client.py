# tests/test_telegram_client.py -- R1 D1: the Bot API client. httpx only, no SDK; the bot token sits
# in the URL path, so nothing it logs or raises may contain a URL or the token.
from __future__ import annotations

import logging

import pytest
from telegram_fakes import TOKEN, FakeBot

from jarvis.telegram.client import TelegramError


async def test_send_message_posts_plain_text_to_the_token_path() -> None:
    bot = FakeBot()
    mid = await bot.client().send_message(42, "hello there")
    assert mid == 101
    assert bot.paths == [f"/bot{TOKEN}/sendMessage"]
    payload = bot.of("sendMessage")[0]
    assert payload == {"chat_id": 42, "text": "hello there"}  # no parse_mode, no markup
    assert "parse_mode" not in payload


async def test_send_message_with_buttons_builds_an_inline_keyboard() -> None:
    bot = FakeBot()
    await bot.client().send_message(42, "ok?", buttons=[("Approve", "a:x1"), ("Decline", "d:x1")])
    markup = bot.of("sendMessage")[0]["reply_markup"]
    row = markup["inline_keyboard"][0]
    assert [(b["text"], b["callback_data"]) for b in row] == [
        ("Approve", "a:x1"),
        ("Decline", "d:x1"),
    ]


async def test_answer_callback_and_edit_buttons() -> None:
    bot = FakeBot()
    c = bot.client()
    await c.answer_callback("cb1", "Done")
    await c.edit_buttons(42, 7)
    assert bot.of("answerCallbackQuery") == [{"callback_query_id": "cb1", "text": "Done"}]
    edit = bot.of("editMessageReplyMarkup")[0]
    assert edit["chat_id"] == 42 and edit["message_id"] == 7
    assert edit["reply_markup"] == {"inline_keyboard": []}


async def test_get_me_is_cached() -> None:
    bot = FakeBot("my_bot")
    c = bot.client()
    assert await c.get_me() == "my_bot"
    assert await c.get_me() == "my_bot"
    assert [m for m, _ in bot.calls].count("getMe") == 1


async def test_webhook_info_in_our_own_words() -> None:
    bot = FakeBot()
    bot.pending = 3
    bot.webhook_error = True
    info = await bot.client().webhook_info()
    assert info["registered"] is True and info["pending"] == 3
    assert info["last_error"] and "VENDOR" not in info["last_error"]
    bot.webhook_url = ""
    bot.webhook_error = False
    again = await bot.client().webhook_info()
    assert again == {"registered": False, "pending": 3, "last_error": None}


async def test_telegram_refusal_raises_without_vendor_text_or_token(
    caplog: pytest.LogCaptureFixture,
) -> None:
    bot = FakeBot()
    bot.fail.add("sendMessage")
    with caplog.at_level(logging.DEBUG), pytest.raises(TelegramError) as ei:
        await bot.client().send_message(1, "x")
    text = str(ei.value) + repr(ei.value) + caplog.text
    assert "VENDOR" not in text and TOKEN not in text and "api.telegram.org" not in text
    assert "sendMessage" in str(ei.value)


async def test_transport_errors_never_carry_the_url(caplog: pytest.LogCaptureFixture) -> None:
    bot = FakeBot()
    bot.raise_transport = True
    with caplog.at_level(logging.DEBUG), pytest.raises(TelegramError) as ei:
        await bot.client().send_message(1, "x")
    shown = str(ei.value) + repr(ei.value) + caplog.text
    assert TOKEN not in shown and "api.telegram.org" not in shown and "boom" not in shown
    assert ei.value.__cause__ is None and ei.value.__suppress_context__


async def test_a_redirect_is_not_followed() -> None:
    bot = FakeBot()
    bot.status = 302
    with pytest.raises(TelegramError):
        await bot.client().send_message(1, "x")
    assert len(bot.calls) == 1


async def test_an_oversized_reply_is_refused() -> None:
    bot = FakeBot()
    bot.big = True
    with pytest.raises(TelegramError):
        await bot.client().send_message(1, "x")


async def test_the_token_is_not_in_the_clients_repr() -> None:
    assert TOKEN not in repr(FakeBot().client())


# ---- R7 D19 (Part D): the SOS map pin ----------------------------------------------------------
async def test_send_location_posts_the_pin_in_the_body_never_in_the_address(
    caplog: pytest.LogCaptureFixture,
) -> None:
    bot = FakeBot()
    with caplog.at_level(logging.DEBUG):
        await bot.client().send_location(42, -1.234567, -23.456789, accuracy_m=20)
    assert bot.paths == [f"/bot{TOKEN}/sendLocation"]  # the address holds no coordinate
    assert bot.of("sendLocation") == [
        {"chat_id": 42, "latitude": -1.234567, "longitude": -23.456789, "horizontal_accuracy": 20}
    ]
    assert "1.234567" not in caplog.text and "23.456789" not in caplog.text


async def test_send_location_caps_the_accuracy_at_telegrams_limit_and_drops_a_bad_one() -> None:
    bot = FakeBot()
    c = bot.client()
    await c.send_location(42, 1.0, 2.0, accuracy_m=5000)
    await c.send_location(42, 1.0, 2.0, accuracy_m=None)
    await c.send_location(42, 1.0, 2.0, accuracy_m=-3)
    sent = bot.of("sendLocation")
    assert sent[0]["horizontal_accuracy"] == 1500
    assert "horizontal_accuracy" not in sent[1] and "horizontal_accuracy" not in sent[2]


@pytest.mark.parametrize(("lat", "lon"), [(91.0, 0.0), (0.0, 181.0), (float("nan"), 0.0)])
async def test_send_location_refuses_an_impossible_place_before_any_call(
    lat: float, lon: float
) -> None:
    bot = FakeBot()
    with pytest.raises(TelegramError) as ei:
        await bot.client().send_location(42, lat, lon)
    assert bot.calls == [] and "sendLocation" in str(ei.value)
    assert not any(ch.isdigit() for ch in str(ei.value))  # no coordinate in the words


async def test_a_failed_pin_names_the_method_only(caplog: pytest.LogCaptureFixture) -> None:
    bot = FakeBot()
    bot.fail.add("sendLocation")
    with caplog.at_level(logging.DEBUG), pytest.raises(TelegramError) as ei:
        await bot.client().send_location(42, -1.234567, -23.456789)
    assert "sendLocation" in str(ei.value) and "VENDOR" not in str(ei.value)
    assert "1.234567" not in caplog.text + str(ei.value)
