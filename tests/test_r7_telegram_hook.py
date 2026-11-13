# tests/test_r7_telegram_hook.py -- R7 I0 seam 15 (docs/plans/r7-mobile.md D20): the Telegram
# front door's one hook for SOS contacts. A join word carries the fixed prefix `sos-` and is
# checked BEFORE pairing, so a wrong one never counts against the owner's pairing tries; a pairing
# code never joins SOS; a known contact's `/stop` reaches the hook before the turn-away; anyone
# else is still turned away and audited. Part D's code behind the hook lives in `jarvis.sos`.
from __future__ import annotations

from typing import Any

from telegram_fakes import OWNER_TG, STRANGER_TG, World, build_world, message

from jarvis.sos.hook import SOS_WORD_PREFIX

WORD = SOS_WORD_PREFIX + "Zx9_" + "k" * 20  # >= 128 random bits in a real one
TRIES_ALL = "jarvis_telegram_pairing_tries/all"


class FakeHook:
    """Part D's side, faked: who is a contact, what joined, who left."""

    def __init__(self, contacts: set[int] | None = None, *, accept: bool = True) -> None:
        self.contacts = contacts or set()
        self.accept = accept
        self.joins: list[tuple[str, int, int]] = []
        self.stops: list[tuple[int, int]] = []

    async def is_contact(self, tg_user_id: int) -> bool:
        return tg_user_id in self.contacts

    async def join(self, word: str, *, tg_user_id: int, chat_id: int) -> str | None:
        self.joins.append((word, tg_user_id, chat_id))
        return "You are now an emergency contact." if self.accept else None

    async def stop(self, *, tg_user_id: int, chat_id: int) -> str | None:
        self.stops.append((tg_user_id, chat_id))
        return "You have left."


def _world(hook: FakeHook | None) -> World:
    w = build_world()
    w.service.sos = hook
    return w


async def _tries(w: World) -> Any:
    return await w.docs.get(TRIES_ALL)


async def test_a_wrong_sos_word_leaves_the_pairing_counter_unchanged() -> None:
    hook = FakeHook(accept=False)
    w = _world(hook)
    await w.send(message(1, f"/start {WORD}", user=STRANGER_TG, chat=STRANGER_TG))
    assert hook.joins == [(WORD, STRANGER_TG, STRANGER_TG)]
    assert await _tries(w) is None  # the owner's pairing tries never moved
    assert w.audited("telegram_rejected")  # a word that did not join is turned away, audited
    assert w.provider.calls == []  # never the brain


async def test_a_right_sos_word_gets_the_hooks_one_reply() -> None:
    hook = FakeHook()
    w = _world(hook)
    await w.send(message(2, f"/start {WORD}", user=STRANGER_TG, chat=STRANGER_TG))
    assert w.bot.texts == ["You are now an emergency contact."]
    assert await _tries(w) is None and not w.audited("telegram_paired")


async def test_without_a_hook_an_sos_word_is_turned_away_and_never_tried_as_a_code() -> None:
    w = _world(None)
    await w.send(message(3, f"/start {WORD}", user=STRANGER_TG, chat=STRANGER_TG))
    assert await _tries(w) is None and w.audited("telegram_rejected")


async def test_a_pairing_code_never_joins_sos() -> None:
    hook = FakeHook()
    w = _world(hook)
    code, _ = await w.store.start_pairing("owner")
    await w.send(message(4, f"/start {code}", user=OWNER_TG, chat=OWNER_TG))
    assert hook.joins == [] and w.audited("telegram_paired")
    await w.send(message(5, "/start ABCD2345", user=STRANGER_TG, chat=STRANGER_TG))
    assert hook.joins == []  # a wrong code is a wrong code: counted, as before
    assert (await _tries(w)) is not None


async def test_a_contacts_stop_reaches_the_hook_before_the_turn_away() -> None:
    hook = FakeHook(contacts={STRANGER_TG})
    w = _world(hook)
    await w.send(message(6, "/stop", user=STRANGER_TG, chat=STRANGER_TG))
    assert hook.stops == [(STRANGER_TG, STRANGER_TG)]
    assert w.bot.texts == ["You have left."] and not w.audited("telegram_rejected")


async def test_anyone_else_is_still_turned_away_and_audited() -> None:
    hook = FakeHook(contacts={STRANGER_TG})
    w = _world(hook)
    await w.send(message(7, "/stop", user=STRANGER_TG + 1, chat=STRANGER_TG + 1))
    await w.send(message(8, "hello", user=STRANGER_TG, chat=STRANGER_TG))  # a contact chatting
    assert hook.stops == [] and w.bot.texts == []
    assert len(w.audited("telegram_rejected")) == 2 and w.provider.calls == []
    await w.send(message(9, "/stop", user=STRANGER_TG, chat=STRANGER_TG, chat_type="group"))
    assert hook.stops == []  # private chats only, as pairing
