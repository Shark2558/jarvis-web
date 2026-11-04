# tests/test_telegram_hardening.py -- integration review (r1-fix-2): M2 a pairing swarm cannot lock
# the owner out, M3 a stranger costs no store write, H2(seams) a Telegram turn has a whole-turn
# budget.
from __future__ import annotations

import asyncio
import logging
from typing import Any

import pytest
from telegram_fakes import OWNER_CHAT, OWNER_TG, UID, build_world, message

from jarvis.telegram import service as telegram_service
from jarvis.telegram.pairing import GLOBAL_TRIES, MAX_TRIES, TRY_WINDOW_S
from jarvis.telegram.service import SENDER_MESSAGES_PER_WINDOW

SWARM = GLOBAL_TRIES // MAX_TRIES  # senders needed to trip the global cooldown


def _claims(w: Any) -> list[str]:
    return [k for k in w.docs._data if "telegram_updates" in k]


# ---- M2: a matching code still pairs during the global cooldown ---------------------------------


async def test_after_a_swarm_of_bad_tries_the_owners_valid_code_still_pairs() -> None:
    w = build_world()
    code, _ = await w.store.start_pairing(UID)
    for sender in range(SWARM):
        for _ in range(MAX_TRIES):
            await w.store.finish_pairing("ZZZZZZZZ", tg_user_id=1000 + sender, chat_id=1)
    assert await w.store.finish_pairing("ZZZZZZZZ", tg_user_id=5000, chat_id=1) is None
    assert await w.store.finish_pairing(code, tg_user_id=OWNER_TG, chat_id=OWNER_CHAT) == UID


async def test_the_per_sender_limit_still_holds_for_a_locked_sender() -> None:
    w = build_world()
    code, _ = await w.store.start_pairing(UID)
    for _ in range(MAX_TRIES):
        await w.store.finish_pairing("ZZZZZZZZ", tg_user_id=9, chat_id=9)
    assert await w.store.finish_pairing(code, tg_user_id=9, chat_id=9) is None


async def test_the_cooldown_tripping_is_audited_and_logged_without_codes(
    caplog: pytest.LogCaptureFixture,
) -> None:
    w = build_world()
    code, _ = await w.store.start_pairing(UID)
    caplog.set_level(logging.WARNING)
    for sender in range(SWARM):
        for i in range(MAX_TRIES):
            uid = 10_000 + sender * 10 + i
            await w.send(message(uid, "/start ZZZZZZZZ", user=2000 + sender, chat=2000 + sender))
    [entry] = w.audited("telegram_pairing_cooldown")
    assert entry.agent == "telegram"
    warned = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert any("cooldown" in r.getMessage() for r in warned)
    dump = "\n".join(r.getMessage() for r in caplog.records) + repr(entry)
    assert code not in dump and "ZZZZZZZZ" not in dump
    await w.send(message(99_999, f"/start {code}"))
    assert (await w.store.get(UID)) is not None  # the owner still paired


# ---- M3: a stranger costs no Firestore write before the sender check ----------------------------


async def test_a_strangers_ordinary_message_makes_no_store_write() -> None:
    w = build_world()
    await w.pair()
    before = dict(w.docs._data)
    await w.send(message(1, "hello", user=777, chat=777))
    await w.send(message(2, "/unpair", user=777, chat=777))
    await w.send(message(3, "hi", user=888, chat=-1, chat_type="group"))
    assert _claims(w) == []
    assert {k for k in w.docs._data} == set(before)


async def test_the_owner_and_a_start_from_an_eligible_sender_are_still_claimed() -> None:
    w = build_world()
    code, _ = await w.store.start_pairing(UID)
    await w.send(message(10, f"/start {code}"))
    await w.send(message(11, "hello"))
    await w.send(message(12, "/start ZZZZZZZZ", user=777, chat=777))
    assert len(_claims(w)) == 3


async def test_a_replayed_owner_update_is_still_a_noop() -> None:
    w = build_world()
    await w.pair()
    await w.send(message(1, "hi"))
    await w.send(message(1, "hi"))
    assert len(w.provider.calls) == 1


async def test_a_flooding_stranger_is_throttled_in_memory() -> None:
    w = build_world()
    await w.pair()
    for i in range(SENDER_MESSAGES_PER_WINDOW + 40):
        await w.send(message(i + 1, f"/start ZZZZZZZZ{i}", user=777, chat=777))
    assert len(_claims(w)) == SENDER_MESSAGES_PER_WINDOW
    w.clock.advance(seconds=TRY_WINDOW_S + 1)
    await w.send(message(5000, "/start ZZZZZZZZ", user=777, chat=777))
    assert len(_claims(w)) == SENDER_MESSAGES_PER_WINDOW + 1


# ---- seams H2: a whole-turn budget on Telegram -------------------------------------------------


async def test_a_turn_over_budget_tells_the_owner_audits_and_returns(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert telegram_service.TURN_BUDGET_S == 240
    monkeypatch.setattr(telegram_service, "TURN_BUDGET_S", 0.05)
    w = build_world()
    await w.pair()

    async def slow(_req: Any) -> Any:
        await asyncio.sleep(30)

    monkeypatch.setattr(w.brain, "chat", slow)
    async with asyncio.timeout(5):  # the webhook returns well inside the budget plus slack
        await w.send(message(1, "plan my year"))
    assert w.bot.texts == [telegram_service.TOO_SLOW]
    assert "took too long" in telegram_service.TOO_SLOW
    [entry] = w.audited("telegram_turn_timeout")
    assert entry.outcome == "timeout"


async def test_a_turn_inside_the_budget_is_unaffected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(telegram_service, "TURN_BUDGET_S", 5)
    w = build_world()
    await w.pair()
    w.provider.script("Fine.")
    await w.send(message(1, "hi"))
    assert w.bot.texts == ["Fine."] and w.audited("telegram_turn_timeout") == []
