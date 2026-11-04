# tests/test_telegram_models.py -- R1 D1/D2: Telegram updates parsed strictly but tolerantly.
from __future__ import annotations

import json

from telegram_fakes import OWNER_TG, callback, message

from jarvis.telegram.models import parse_update


def test_a_text_message_parses() -> None:
    u = parse_update(message(5, "what's on today?"))
    assert u is not None and u.update_id == 5
    m = u.message
    assert m is not None and m.text == "what's on today?"
    assert m.sender is not None and m.sender.id == OWNER_TG and m.sender.is_bot is False
    assert m.chat.type == "private"


def test_bytes_and_str_are_accepted() -> None:
    raw = json.dumps(message(6, "hi")).encode()
    assert parse_update(raw) is not None
    assert parse_update(raw.decode()) is not None


def test_a_callback_parses() -> None:
    u = parse_update(callback(9, "a:abc"))
    assert u is not None and u.callback_query is not None
    cq = u.callback_query
    assert cq.data == "a:abc" and cq.sender.id == OWNER_TG
    assert cq.message is not None and cq.message.chat.id == OWNER_TG


def test_unknown_fields_are_ignored() -> None:
    raw = message(7, "hi")
    raw["message"]["entities"] = [{"type": "bot_command"}]
    raw["something_new"] = {"x": 1}
    assert parse_update(raw) is not None


def test_non_text_messages_have_no_text() -> None:
    u = parse_update(message(8, None))
    assert u is not None and u.message is not None and u.message.text is None


def test_garbage_is_none_never_an_exception() -> None:
    for bad in (b"", b"not json", b"[]", b"123", b'{"update_id": "x"}', b'{"message": {}}', None):
        assert parse_update(bad) is None  # type: ignore[arg-type]


def test_a_message_without_a_sender_still_parses() -> None:
    raw = message(10, "hi")
    del raw["message"]["from"]
    u = parse_update(raw)
    assert u is not None and u.message is not None and u.message.sender is None


def test_huge_text_is_kept_whole_for_the_service_to_judge() -> None:
    u = parse_update(message(11, "x" * 10_000))
    assert u is not None and u.message is not None and len(u.message.text or "") == 10_000
