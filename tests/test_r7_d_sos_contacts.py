# tests/test_r7_d_sos_contacts.py -- R7 Part D (docs/plans/r7-mobile.md D20, I0 seam 15): SOS
# contacts join by their own Start with a one-time word (at least 128 random bits, stored only as
# `keyring.mac("sos", word)`, 24 hours); a word joins ONCE; a wrong word counts on its own counter
# and never touches the owner's pairing; a pairing code never joins; a contact's /stop reaches the
# hook, removes them and tells the owner (`sos_contact_left`, no name); anything else a contact
# writes gets no reply and never reaches the brain; a stranger is still rejected and audited.
from __future__ import annotations

import json
from typing import Any

import pytest
from r7_fakes_d import ASHA, RAVI, UID, BrokenDocs, Clock, Notes, PinBot, settings
from telegram_fakes import OWNER_TG, STRANGER_TG, World, build_world, message

from jarvis.keyring import Keyring
from jarvis.sos.contacts_hook import ContactHook
from jarvis.sos.hook import is_sos_word
from jarvis.sos.models import clean_label, clean_phone
from jarvis.sos.service import SosRefused, SosService
from jarvis.sos.store import WRONG_PER_CHAT, SosStore
from jarvis.storage.docs import MemoryDocs
from jarvis.tools.audit import AuditLog

TRIES_ALL = "jarvis_telegram_pairing_tries/all"


def _svc(docs: Any = None, clock: Clock | None = None, notes: Notes | None = None) -> SosService:
    s = settings()
    ring = Keyring.from_settings(s)
    clock = clock or Clock()
    store = SosStore(docs or MemoryDocs(), ring, prefix=s.firestore_prefix, now=clock)
    client = PinBot().client()
    return SosService(
        store,
        s,
        telegram=lambda: client,
        notifier=lambda: notes,
        audit=AuditLog(),
        now=clock,
    )


async def _word(svc: SosService, person: tuple[str, str, int] = ASHA) -> tuple[str, str]:
    c = await svc.add_contact(UID, person[0], person[1])
    link = await svc.join_link(UID, c.id)
    assert link["link"].startswith("https://t.me/jarvis_test_bot?start=sos-")
    return c.id, link["link"].split("start=", 1)[1]


async def test_a_join_word_holds_enough_randomness_and_is_kept_only_as_a_mac() -> None:
    docs = MemoryDocs()
    svc = _svc(docs)
    _, word = await _word(svc)
    assert is_sos_word(word) and len(word) - len("sos-") >= 22  # 22 base64url chars: 132 bits
    dump = json.dumps(docs._data, default=str)
    assert word not in dump and word[4:] not in dump
    (join_path,) = [p for p in docs._data if "sos_join/" in p]
    assert join_path.rsplit("/", 1)[1] == Keyring.from_settings(settings()).mac("sos", word)


async def test_a_contact_joins_by_the_word_once() -> None:
    svc = _svc()
    await svc.set_label(UID, "Kiran Example")
    _, word = await _word(svc)
    reply = await svc.join(word, tg_user_id=ASHA[2], chat_id=ASHA[2])
    assert reply == (
        "You are now an emergency contact for Kiran Example. This bot writes to you only when "
        "Kiran Example presses SOS or sends a test. Send /stop to leave."
    )
    assert await svc.join(word, tg_user_id=RAVI[2], chat_id=RAVI[2]) is None  # used up
    view = await svc.view(UID)
    assert [(c["label"], c["joined"], c["pending"]) for c in view["contacts"]] == [
        ("Asha Example", True, False)
    ]
    assert await svc.is_contact(ASHA[2]) and not await svc.is_contact(RAVI[2])


async def test_a_word_expires_after_24_hours() -> None:
    clock = Clock()
    svc = _svc(clock=clock)
    _, word = await _word(svc)
    clock.move(hours=24, seconds=1)
    assert await svc.join(word, tg_user_id=ASHA[2], chat_id=ASHA[2]) is None


async def test_a_new_link_replaces_the_old_one() -> None:
    svc = _svc()
    cid, old = await _word(svc)
    new = (await svc.join_link(UID, cid))["link"].split("start=", 1)[1]
    assert await svc.join(old, tg_user_id=ASHA[2], chat_id=ASHA[2]) is None
    assert await svc.join(new, tg_user_id=ASHA[2], chat_id=ASHA[2]) is not None


async def test_wrong_words_have_their_own_counter_and_it_stops_that_chat() -> None:
    svc = _svc()
    _, word = await _word(svc)
    for i in range(WRONG_PER_CHAT):
        bad = "sos-" + f"{i:02d}" + "x" * 22
        assert await svc.join(bad, tg_user_id=9, chat_id=9) is None
    assert await svc.join(word, tg_user_id=9, chat_id=9) is None  # that chat is held for the hour


async def test_removing_a_contact_drops_its_word_and_the_limit_holds() -> None:
    svc = _svc()
    cid, word = await _word(svc)
    await svc.remove_contact(UID, cid)
    assert await svc.join(word, tg_user_id=ASHA[2], chat_id=ASHA[2]) is None
    for i in range(5):
        await svc.add_contact(UID, f"Person {i} Example", None)
    with pytest.raises(SosRefused) as ei:
        await svc.add_contact(UID, "One Too Many", None)
    assert "5" in str(ei.value)


@pytest.mark.parametrize(
    ("raw", "label"),
    [("  Asha  Example ", "Asha Example"), ("Asha‮evil", "Ashaevil"), ("x" * 50, "x" * 40)],
)
def test_labels_are_cleaned(raw: str, label: str) -> None:
    assert clean_label(raw) == label


@pytest.mark.parametrize(
    ("raw", "phone"),
    [("+1 000 000 0001", "+10000000001"), ("(000) 000-0001", "0000000001"), ("12", None)],
)
def test_phone_numbers_are_cleaned(raw: str, phone: str | None) -> None:
    assert clean_phone(raw) == phone


async def test_bad_labels_and_numbers_are_refused_in_plain_words() -> None:
    svc = _svc()
    with pytest.raises(SosRefused):
        await svc.add_contact(UID, "   ", None)
    with pytest.raises(SosRefused):
        await svc.add_contact(UID, "Asha Example", "call me")


async def test_without_telegram_a_link_says_why() -> None:
    s = settings()
    store = SosStore(MemoryDocs(), Keyring.from_settings(s), now=Clock())
    svc = SosService(store, s, telegram=lambda: None, notifier=None, audit=AuditLog(), now=Clock())
    c = await svc.add_contact(UID, "Asha Example", None)
    with pytest.raises(SosRefused) as ei:
        await svc.join_link(UID, c.id)
    assert "Telegram" in str(ei.value)


async def test_without_a_token_key_nothing_is_kept() -> None:
    s = settings()
    docs = MemoryDocs()
    svc = SosService(
        SosStore(docs, None, now=Clock()), s, telegram=lambda: None, notifier=None,
        audit=AuditLog(), now=Clock(),
    )  # fmt: skip
    with pytest.raises(SosRefused) as ei:
        await svc.add_contact(UID, "Asha Example", None)
    assert "token key" in str(ei.value) and docs._data == {}


async def test_stop_removes_the_contact_and_tells_the_owner_without_a_name() -> None:
    notes = Notes()
    svc = _svc(notes=notes)
    await svc.set_label(UID, "Kiran Example")
    _, word = await _word(svc)
    await svc.join(word, tg_user_id=ASHA[2], chat_id=ASHA[2])
    reply = await svc.stop(tg_user_id=ASHA[2], chat_id=ASHA[2])
    assert reply == "You are no longer an emergency contact for Kiran Example. They have been told."
    assert (await svc.view(UID))["contacts"] == []
    (uid, kind, words) = notes.sent[-1]
    assert (uid, kind) == (UID, "sos_contact_left") and "Asha" not in words
    assert await svc.stop(tg_user_id=ASHA[2], chat_id=ASHA[2]) is None  # not a contact any more


async def test_the_hook_never_raises_on_a_broken_store() -> None:
    hook = ContactHook(_svc(BrokenDocs()))
    assert await hook.is_contact(ASHA[2]) is False
    assert await hook.join("sos-" + "a" * 30, tg_user_id=1, chat_id=1) is None
    assert await hook.stop(tg_user_id=1, chat_id=1) is None


# ---- through the real Telegram front door (I0's hook) --------------------------------------------
def _door(svc: SosService) -> World:
    w = build_world()
    w.service.sos = ContactHook(svc)
    return w


async def test_through_telegram_a_contact_joins_once_and_the_pairing_counter_never_moves() -> None:
    svc = _svc()
    await svc.set_label(UID, "Kiran Example")
    _, word = await _word(svc)
    w = _door(svc)
    await w.send(message(1, f"/start {word}", user=STRANGER_TG, chat=STRANGER_TG))
    assert w.bot.texts[-1].startswith("You are now an emergency contact for Kiran Example.")
    await w.send(message(2, f"/start {word}", user=STRANGER_TG + 1, chat=STRANGER_TG + 1))
    assert len(w.bot.texts) == 1 and w.audited("telegram_rejected")  # the second use: turned away
    await w.send(message(3, "/start sos-" + "W" * 30, user=STRANGER_TG + 2, chat=STRANGER_TG + 2))
    assert await w.docs.get(TRIES_ALL) is None  # wrong SOS words never count against pairing
    assert w.provider.calls == []


async def test_through_telegram_a_pairing_code_never_joins_sos() -> None:
    svc = _svc()
    w = _door(svc)
    code, _ = await w.store.start_pairing("owner")
    await w.send(message(4, f"/start {code}", user=OWNER_TG, chat=OWNER_TG))
    assert w.audited("telegram_paired") and (await svc.view(UID))["contacts"] == []


async def test_through_telegram_a_contacts_stop_reaches_the_hook_and_chatter_goes_nowhere() -> None:
    svc = _svc()
    _, word = await _word(svc)
    w = _door(svc)
    await w.send(message(5, f"/start {word}", user=STRANGER_TG, chat=STRANGER_TG))
    await w.send(message(6, "please call me back", user=STRANGER_TG, chat=STRANGER_TG))
    assert len(w.bot.texts) == 1 and w.provider.calls == []  # no reply, never the brain
    await w.send(message(7, "/stop", user=STRANGER_TG, chat=STRANGER_TG))
    assert w.bot.texts[-1].startswith("You are no longer an emergency contact")
    assert not await svc.is_contact(STRANGER_TG)


async def test_through_telegram_a_stranger_without_a_word_is_still_rejected_and_audited() -> None:
    w = _door(_svc())
    await w.send(message(8, "hello", user=STRANGER_TG, chat=STRANGER_TG))
    await w.send(message(9, "/stop", user=STRANGER_TG, chat=STRANGER_TG))
    assert w.bot.texts == [] and len(w.audited("telegram_rejected")) == 2
