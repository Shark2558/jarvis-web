# tests/test_r18_i0_store.py -- R18 I0: the call store on the Docs port (Firestore in production)
# and its in-memory twin; numbers are sealed and referenced by a keyed hash, never stored in clear.
from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta

import pytest

from jarvis.calls.models import CallCard, CallRecord, CallState, LanguageResult, SpeechOption
from jarvis.calls.ports import CallStore, CallStoreUnreadable, DayCounts
from jarvis.calls.store import DocCallStore, KeyringSealer, MemoryCallStore, MemorySealer
from jarvis.keyring import Keyring
from jarvis.storage.docs import MemoryDocs

UID = "u_0123456789abcdef"
NUMBER, OTHER = "+919000000001", "+919000000002"
AT = datetime(2026, 11, 27, 5, 0, tzinfo=UTC)
DAY = date(2026, 11, 27)


def _keyring() -> Keyring:
    return Keyring(bytes(range(32)))


def _store() -> tuple[DocCallStore, MemoryDocs]:
    docs = MemoryDocs()
    return DocCallStore(docs, prefix="t_", sealer=KeyringSealer(_keyring())), docs


def _no_digits_stored(docs: MemoryDocs) -> None:
    dumped = json.dumps(docs._data)  # noqa: SLF001 - the test reads the raw documents
    assert "9000000001" not in dumped and "9000000002" not in dumped


def test_both_stores_meet_the_port() -> None:
    stores: list[CallStore] = [_store()[0], MemoryCallStore()]
    assert len(stores) == 2


async def test_a_card_round_trips_with_its_number_sealed() -> None:
    store, docs = _store()
    card = CallCard(number_e164=NUMBER, purpose="Book a pickup", languages=("en-IN", "ml-IN"))
    await store.put_card(UID, card)
    assert await store.get_card(UID, card.id) == card
    assert await store.get_card(UID, "cc_000000000000") is None
    _no_digits_stored(docs)
    await store.delete_card(UID, card.id)
    assert await store.get_card(UID, card.id) is None


async def test_records_list_newest_first_and_keep_and_delete() -> None:
    store, docs = _store()
    old = CallRecord(number_e164=NUMBER, started_at=AT - timedelta(days=40))
    new = CallRecord(number_e164=OTHER, started_at=AT, state=CallState.ENDED)
    for r in (old, new):
        await store.put_record(UID, r)
    assert [r.id for r in await store.list_records(UID)] == [new.id, old.id]
    assert [r.id for r in await store.list_records(UID, limit=1)] == [new.id]
    assert [r.id for r in await store.due_for_deletion(UID, AT)] == [old.id]
    kept = await store.set_keep(UID, old.id, True)
    assert kept is not None and kept.keep and await store.due_for_deletion(UID, AT) == []
    assert await store.set_keep(UID, "call_000000000000", True) is None
    assert await store.delete_record(UID, new.id) is True
    assert await store.delete_record(UID, new.id) is False
    assert await store.get_record(UID, new.id) is None
    _no_digits_stored(docs)


async def test_counting_a_call_is_one_transaction_with_the_limit_check() -> None:
    store, _ = _store()
    assert await store.known_number(UID, NUMBER) is False
    counts, refused = await store.count_call(UID, DAY, NUMBER)
    assert refused is None and counts.calls == 1 and counts.new_numbers == 1
    assert await store.known_number(UID, NUMBER) is True
    seen: list[tuple[DayCounts, bool]] = []

    def check(c: DayCounts, new: bool) -> str | None:
        seen.append((c, new))
        return "Two calls to this number today already." if c.calls >= 1 and not new else None

    counts, refused = await store.count_call(UID, DAY, NUMBER, check=check)
    assert refused == "Two calls to this number today already." and counts.calls == 1
    assert seen[0][1] is False  # called before: not new
    counts, refused = await store.count_call(UID, DAY, OTHER, check=check)
    assert refused is None and (counts.calls, counts.new_numbers) == (2, 2)
    day = await store.day_counts(UID, DAY)
    ref = store.sealer.ref(UID, NUMBER)
    assert day.to_number(ref) == 1 and day == counts
    assert (await store.day_counts(UID, date(2026, 11, 28))).calls == 0
    after = await store.count_no_answer(UID, DAY, OTHER)
    assert after.no_answer == {store.sealer.ref(UID, OTHER): 1}


async def test_month_spend_adds_up_and_refuses_bad_amounts() -> None:
    store, _ = _store()
    assert await store.month_spend(UID, "2026-11") == 0
    assert await store.add_spend(UID, "2026-11", 1.25) == 1.25
    assert await store.add_spend(UID, "2026-11", 0.5) == 1.75
    for bad in (-1.0, float("nan"), float("inf")):
        with pytest.raises(ValueError):
            await store.add_spend(UID, "2026-11", bad)
    with pytest.raises(ValueError):
        await store.month_spend(UID, "Nov 2026")


async def test_settings_and_language_results() -> None:
    store = MemoryCallStore()
    assert (await store.settings(UID)).answering_on is False
    saved = await store.save_settings(UID, {"answering_on": True, "answer_after_rings": 4})
    assert saved.answering_on and (await store.settings(UID)).answer_after_rings == 4
    r = LanguageResult(lang="ml-IN", option=SpeechOption.GOOGLE, checked_at=AT, passed=True)
    await store.put_language_result(r)
    await store.put_language_result(r.model_copy(update={"passed": False}))
    assert await store.language_results() == [r.model_copy(update={"passed": False})]


async def test_an_unreadable_document_is_never_read_as_none() -> None:
    store, docs = _store()
    card = CallCard(number_e164=NUMBER, purpose="x")
    await store.put_card(UID, card)
    path = next(p for p in docs._data if "/cards/" in p)  # noqa: SLF001
    docs._data[path]["number_sealed"] = "tampered"  # noqa: SLF001
    with pytest.raises(CallStoreUnreadable):
        await store.get_card(UID, card.id)
    docs._data[path] = {"id": card.id}  # noqa: SLF001
    with pytest.raises(CallStoreUnreadable):
        await store.get_card(UID, card.id)


async def test_an_owner_id_is_never_a_path() -> None:
    store = MemoryCallStore()
    with pytest.raises(ValueError):
        await store.get_card("u/../other", "cc_000000000000")


def test_the_sealers_hide_the_number_and_refs_are_keyed() -> None:
    k = KeyringSealer(_keyring())
    sealed = k.seal(UID, NUMBER)
    assert NUMBER not in sealed and k.open(UID, sealed) == NUMBER
    with pytest.raises(CallStoreUnreadable):
        k.open("u_other", sealed)  # bound to its owner
    assert k.ref(UID, NUMBER) == k.ref(UID, NUMBER) != k.ref("u_other", NUMBER)
    assert len(k.ref(UID, NUMBER)) == 32
    other = KeyringSealer(Keyring(bytes(range(1, 33))))
    assert other.ref(UID, NUMBER) != k.ref(UID, NUMBER)
    m = MemorySealer()
    token = m.seal(UID, NUMBER)
    assert "9000000001" not in token and m.open(UID, token) == NUMBER
    with pytest.raises(CallStoreUnreadable):
        m.open(UID, "nope")
