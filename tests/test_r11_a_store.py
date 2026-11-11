# tests/test_r11_a_store.py -- R11 Part A (data model): `bills/{uid}` keeps his bills sealed with
# the keyring purpose `bills` (AAD bills/{uid}/v1) and his Part A choices beside them; without a
# keyring the bills are OFF (never stored in clear) while the choices still work; a payment is
# "ready" for 10 minutes and is taken once; claims (`bills_told`, `birthdays_told`) are made once,
# released for a retry, hashed (no name, no date in them) and swept after their retention.
from __future__ import annotations

from datetime import date, timedelta

import pytest
from r11_fakes import NOON_IST, UID
from r11_fakes_a import FAKE_UPI, every_text, keyring

from jarvis.helpers.today.models import Bill, Due, Prefs
from jarvis.helpers.today.store import BillsOff, BillStore, Claims
from jarvis.integrations.vault import VaultError
from jarvis.storage.docs import MemoryDocs, Set

DUE = Due(start=date(2026, 11, 13), every_months=1)


def _bill(label: str = "Electricity", bid: str = "a1b2c3d4e5f6") -> Bill:
    return Bill(id=bid, label=label, payee="Power Co", upi=FAKE_UPI, amount=124000, due=DUE)


async def test_bills_are_sealed_and_read_back() -> None:
    docs = MemoryDocs()
    store = BillStore(docs, keyring(), prefix="jarvis_")
    await store.change(UID, lambda b: b.with_bills((_bill(),)))
    raw = every_text(docs)
    assert "Electricity" not in raw and FAKE_UPI not in raw and "124000" not in raw
    book = await store.book(UID)
    assert book.bills == (_bill(),) and book.prefs == Prefs() and book.rev == 1


async def test_the_seal_is_bound_to_the_owner() -> None:
    docs = MemoryDocs()
    store = BillStore(docs, keyring(), prefix="jarvis_")
    await store.change(UID, lambda b: b.with_bills((_bill(),)))
    blob = (await docs.get(f"jarvis_bills/{UID}"))["sealed"]  # type: ignore[index]
    await docs.write([Set("jarvis_bills/u_other", {"uid": "u_other", "sealed": blob})])
    with pytest.raises(VaultError):
        await store.book("u_other")


async def test_without_a_keyring_bills_are_off_but_his_choices_are_kept() -> None:
    docs = MemoryDocs()
    store = BillStore(docs, None, prefix="jarvis_")
    assert not store.available
    with pytest.raises(BillsOff):
        await store.change(UID, lambda b: b.with_bills((_bill(),)))
    got = await store.change(UID, lambda b: b.with_prefs(Prefs(birthdays_on=True)))
    assert got.prefs.birthdays_on and got.bills == ()
    assert (await store.book(UID)).prefs.birthdays_on
    assert "sealed" not in (await docs.get(f"jarvis_bills/{UID}") or {})


async def test_a_ready_payment_is_taken_once_and_expires() -> None:
    docs = MemoryDocs()
    store = BillStore(docs, keyring(), prefix="jarvis_")
    await store.change(UID, lambda b: b.with_bills((_bill(),)))
    grant = {"paise": 89950, "due": date(2026, 11, 13), "now": NOON_IST}
    await store.make_ready(UID, "a1b2c3d4e5f6", **grant)  # type: ignore[arg-type]
    assert "89950" not in every_text(docs)  # the grant is sealed with the bills
    got = await store.take_ready(UID, "a1b2c3d4e5f6", NOON_IST + timedelta(minutes=9))
    assert got is not None and got.paise == 89950 and got.due == date(2026, 11, 13)
    assert await store.take_ready(UID, "a1b2c3d4e5f6", NOON_IST + timedelta(minutes=9)) is None
    await store.make_ready(UID, "a1b2c3d4e5f6", **grant)  # type: ignore[arg-type]
    assert await store.take_ready(UID, "a1b2c3d4e5f6", NOON_IST + timedelta(minutes=11)) is None


async def test_delete_all_takes_the_bills_doc() -> None:
    docs = MemoryDocs()
    store = BillStore(docs, keyring(), prefix="jarvis_")
    await store.change(UID, lambda b: b.with_bills((_bill(),)))
    assert await store.delete_all(UID) == 1
    assert await docs.get(f"jarvis_bills/{UID}") is None
    assert await store.delete_all(UID) == 0


async def test_a_claim_is_made_once_released_for_a_retry_and_holds_no_words() -> None:
    docs = MemoryDocs()
    claims = Claims(docs, "birthdays_told", prefix="jarvis_", keep_days=400)
    key = "people/c123|2026"
    assert await claims.claim(UID, key, NOON_IST)
    assert not await claims.claim(UID, key, NOON_IST)
    await claims.release(UID, key)
    assert await claims.claim(UID, key, NOON_IST)
    raw = every_text(docs)
    assert "c123" not in raw and "2026-11" in raw  # only when it was claimed
    assert await claims.count(UID) == 1


async def test_claims_are_swept_after_their_retention() -> None:
    docs = MemoryDocs()
    claims = Claims(docs, "bills_told", prefix="jarvis_", keep_days=60)
    await claims.claim(UID, "old", NOON_IST - timedelta(days=61))
    await claims.claim(UID, "new", NOON_IST - timedelta(days=59))
    assert await claims.sweep(UID, NOON_IST) == 1
    assert await claims.count(UID) == 1
    assert await claims.delete_all(UID) == 1 and await claims.count(UID) == 0
