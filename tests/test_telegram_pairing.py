# tests/test_telegram_pairing.py -- R1 D2: one owner, one Telegram user. An 8 character Crockford
# base32 code (40 bits), 10 minutes, single use, stored as SHA-256, void after 5 wrong tries.
from __future__ import annotations

import hashlib
import json

from telegram_fakes import NOW, Clock

from jarvis.storage.docs import MemoryDocs
from jarvis.telegram.pairing import (
    ALPHABET,
    CODE_TTL_S,
    GLOBAL_TRIES,
    MAX_TRIES,
    TRY_WINDOW_S,
    hash_code,
    new_code,
    normalise,
)
from jarvis.telegram.store import TelegramStore


def _store() -> tuple[TelegramStore, MemoryDocs, Clock]:
    docs, clock = MemoryDocs(), Clock()
    return TelegramStore(docs, prefix="jarvis_", clock=clock), docs, clock


def test_codes_are_eight_crockford_characters_and_differ() -> None:
    codes = {new_code() for _ in range(50)}
    assert len(codes) == 50
    assert all(len(c) == 8 and set(c) <= set(ALPHABET) for c in codes)
    assert (
        "I" not in ALPHABET and "L" not in ALPHABET and "O" not in ALPHABET and "U" not in ALPHABET
    )


def test_normalise_forgives_case_spaces_hyphens_and_lookalikes() -> None:
    assert normalise("abcd-efgh") == "ABCDEFGH"
    assert normalise("oil0 oil0") == "01100110"
    assert normalise("short") is None
    assert normalise("ABCDEFGHJ") is None  # nine characters
    assert normalise("ABCD$FGH") is None
    assert normalise("") is None


def test_hash_is_sha256_of_the_normalised_code() -> None:
    assert hash_code("abcd-efgh") == hashlib.sha256(b"ABCDEFGH").hexdigest()


async def test_a_right_code_binds_both_ids_once() -> None:
    store, _, _ = _store()
    code, ttl = await store.start_pairing("owner")
    assert ttl == CODE_TTL_S
    assert await store.finish_pairing(code, tg_user_id=11, chat_id=22) == "owner"
    link = await store.get("owner")
    assert link is not None and (link.tg_user_id, link.chat_id) == (11, 22)
    assert link.allow_private_reads is False and link.alerts.approval_waiting is True
    assert await store.uid_for(11) == "owner"
    # single use
    assert await store.finish_pairing(code, tg_user_id=33, chat_id=44) is None
    assert (await store.get("owner")).tg_user_id == 11  # type: ignore[union-attr]


async def test_a_lowercase_hyphenated_code_works() -> None:
    store, _, _ = _store()
    code, _ = await store.start_pairing("owner")
    typed = (code[:4] + "-" + code[4:]).lower()
    assert await store.finish_pairing(typed, tg_user_id=1, chat_id=1) == "owner"


async def test_an_expired_code_fails() -> None:
    store, _, clock = _store()
    code, _ = await store.start_pairing("owner")
    clock.advance(seconds=CODE_TTL_S + 1)
    assert await store.finish_pairing(code, tg_user_id=1, chat_id=1) is None
    assert await store.get("owner") is None


async def test_five_wrong_tries_lock_that_sender_for_ten_minutes() -> None:
    store, _, clock = _store()
    code, _ = await store.start_pairing("owner")
    for _ in range(MAX_TRIES):
        assert await store.finish_pairing("ZZZZZZZZ", tg_user_id=1, chat_id=1) is None
    # that sender is locked, even with the right code ...
    assert await store.finish_pairing(code, tg_user_id=1, chat_id=1) is None
    # ... but the owner's code was not voided by it: someone else can still use it
    assert await store.finish_pairing(code, tg_user_id=2, chat_id=2) == "owner"
    clock.advance(seconds=TRY_WINDOW_S + 1)
    fresh, _ = await store.start_pairing("u_other")
    assert await store.finish_pairing(fresh, tg_user_id=1, chat_id=1) == "u_other"


async def test_strangers_cannot_void_the_owners_code() -> None:
    store, _, _ = _store()
    code, _ = await store.start_pairing("owner")
    for stranger in range(100, 120):  # twenty different senders, one wrong try each
        await store.finish_pairing("ZZZZZZZZ", tg_user_id=stranger, chat_id=stranger)
    assert await store.has_pending("owner") is True  # the code is still alive
    assert await store.finish_pairing(code, tg_user_id=5, chat_id=5) == "owner"


async def test_a_global_cooldown_stops_a_swarm_without_voiding_the_code() -> None:
    store, _, clock = _store()
    code, _ = await store.start_pairing("owner")
    for stranger in range(200, 200 + GLOBAL_TRIES):
        await store.finish_pairing("ZZZZZZZZ", tg_user_id=stranger, chat_id=stranger)
    # cooling down: another WRONG code is refused, but the right one still pairs (review M2)
    assert await store.finish_pairing("ZZZZZZZZ", tg_user_id=6, chat_id=6) is None
    assert await store.has_pending("owner") is True  # not voided
    assert await store.finish_pairing(code, tg_user_id=5, chat_id=5) == "owner"
    clock.advance(seconds=TRY_WINDOW_S + 1)  # the swarm's window is over
    fresh, _ = await store.start_pairing("owner")
    assert await store.finish_pairing(fresh, tg_user_id=7, chat_id=7) == "owner"


async def test_four_wrong_tries_leave_the_sender_unlocked() -> None:
    store, _, _ = _store()
    code, _ = await store.start_pairing("owner")
    for _ in range(MAX_TRIES - 1):
        await store.finish_pairing("ZZZZZZZZ", tg_user_id=1, chat_id=1)
    assert await store.finish_pairing(code, tg_user_id=1, chat_id=1) == "owner"


async def test_has_pending_follows_the_code_life() -> None:
    store, _, clock = _store()
    assert await store.has_pending("owner") is False
    await store.start_pairing("owner")
    assert await store.has_pending("owner") is True
    clock.advance(seconds=CODE_TTL_S + 1)
    assert await store.has_pending("owner") is False


async def test_the_code_is_stored_only_as_a_hash() -> None:
    store, docs, _ = _store()
    code, _ = await store.start_pairing("owner")
    dump = json.dumps(docs._data, default=str)
    assert code not in dump and hash_code(code) in dump


async def test_starting_again_replaces_the_pending_code() -> None:
    store, _, _ = _store()
    first, _ = await store.start_pairing("owner")
    second, _ = await store.start_pairing("owner")
    assert await store.finish_pairing(first, tg_user_id=1, chat_id=1) is None
    assert await store.finish_pairing(second, tg_user_id=1, chat_id=1) == "owner"


async def test_a_telegram_user_bound_to_someone_else_is_refused() -> None:
    store, _, _ = _store()
    a, _ = await store.start_pairing("u_a")
    assert await store.finish_pairing(a, tg_user_id=9, chat_id=9) == "u_a"
    b, _ = await store.start_pairing("u_b")
    assert await store.finish_pairing(b, tg_user_id=9, chat_id=9) is None


async def test_unpair_removes_the_binding_and_pending_code() -> None:
    store, _, _ = _store()
    code, _ = await store.start_pairing("owner")
    await store.finish_pairing(code, tg_user_id=5, chat_id=6)
    pending, _ = await store.start_pairing("owner")
    assert await store.unpair("owner") is True
    assert await store.get("owner") is None and await store.uid_for(5) is None
    assert await store.finish_pairing(pending, tg_user_id=5, chat_id=6) is None
    assert await store.unpair("owner") is False


async def test_update_claims_are_create_only_and_swept_after_48_hours() -> None:
    store, docs, clock = _store()
    assert await store.claim_update(100) is True
    assert await store.claim_update(100) is False
    clock.advance(hours=47)
    assert await store.sweep() == 0
    clock.advance(hours=2)
    assert await store.sweep() == 1
    assert await store.claim_update(100) is True
    assert NOW  # clock shared


async def test_settings_update_bumps_the_revision() -> None:
    store, _, _ = _store()
    code, _ = await store.start_pairing("owner")
    await store.finish_pairing(code, tg_user_id=5, chat_id=6)
    link = await store.set_settings("owner", allow_private_reads=True, alerts={"brief_ready": True})
    assert link.allow_private_reads is True and link.alerts.brief_ready is True
    assert link.alerts.approval_waiting is True and link.rev >= 1
    assert await store.set_settings("nobody", allow_private_reads=True) is None
