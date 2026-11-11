# tests/test_r11_d_store.py -- R11 Part D (plan data model): the kitchen and the grocery spend,
# sealed by JARVIS (keyring purposes `kitchen` and `spend`, AAD `<collection>/{uid}/v1`); without
# a keyring each says it is off and stores nothing in clear.
from __future__ import annotations

import json
from datetime import UTC, date, datetime

import pytest
from r11_fakes import UID
from r11_fakes_d import keyring

from jarvis.helpers.kitchen.models import Kitchen, Prefs
from jarvis.helpers.kitchen.receipts import Receipt
from jarvis.helpers.kitchen.store import (
    KitchenOff,
    KitchenStore,
    KitchenUnavailable,
    SpendStore,
)
from jarvis.storage.docs import MemoryDocs, Set

NOW = datetime(2026, 11, 10, 6, 30, tzinfo=UTC)


def _kitchen(docs: MemoryDocs, sealed: bool = True) -> KitchenStore:
    return KitchenStore(docs, keyring() if sealed else None, now=lambda: NOW)


def _spend(docs: MemoryDocs, sealed: bool = True) -> SpendStore:
    return SpendStore(docs, keyring() if sealed else None, now=lambda: NOW)


def _r(key: str, day: date, paise: int, cancelled: bool = False) -> Receipt:
    return Receipt(key.ljust(32, "0"), "BigBasket", day, paise, cancelled)


async def test_the_kitchen_is_sealed_and_holds_no_words_in_clear() -> None:
    docs = MemoryDocs()
    store = _kitchen(docs)
    assert (await store.load(UID)) == Kitchen()
    note = "NEEDLE-PANTRY-NOTE no mushrooms"
    await store.change(
        UID, lambda k: k.model_copy(update={"pantry": ("toor dal",), "prefs": Prefs(note=note)})
    )
    raw = json.dumps(await docs.get(f"jarvis_kitchen/{UID}"))
    assert "toor dal" not in raw and "NEEDLE" not in raw and '"blob"' in raw
    got = await store.load(UID)
    assert got.pantry == ("toor dal",) and got.prefs.note == note


async def test_another_owners_blob_does_not_open() -> None:
    docs = MemoryDocs()
    store = _kitchen(docs)
    await store.change(UID, lambda k: k.model_copy(update={"pantry": ("rice",)}))
    moved = await docs.get(f"jarvis_kitchen/{UID}")
    assert moved is not None
    await docs.write([Set("jarvis_kitchen/u_other", moved)])
    with pytest.raises(KitchenUnavailable):
        await store.load("u_other")


async def test_a_broken_document_is_never_overwritten() -> None:
    docs = MemoryDocs()
    await docs.write([Set(f"jarvis_kitchen/{UID}", {"v": 1, "blob": "not-base64!"})])
    store = _kitchen(docs)
    with pytest.raises(KitchenUnavailable):
        await store.change(UID, lambda k: k)
    assert (await docs.get(f"jarvis_kitchen/{UID}")) == {"v": 1, "blob": "not-base64!"}


async def test_without_a_keyring_the_kitchen_is_off_and_writes_nothing() -> None:
    docs = MemoryDocs()
    store = _kitchen(docs, sealed=False)
    assert store.sealed is False
    with pytest.raises(KitchenOff):
        await store.load(UID)
    with pytest.raises(KitchenOff):
        await store.change(UID, lambda k: k)
    assert docs.sets == 0


async def test_delete_removes_the_kitchen() -> None:
    docs = MemoryDocs()
    store = _kitchen(docs)
    await store.change(UID, lambda k: k.model_copy(update={"pantry": ("rice",)}))
    assert await store.delete(UID) == 1
    assert await docs.get(f"jarvis_kitchen/{UID}") is None
    assert await store.delete(UID) == 0


async def test_spend_keeps_one_order_per_key_and_drops_a_cancelled_one() -> None:
    docs = MemoryDocs()
    store = _spend(docs)
    await store.apply(UID, [_r("a1", date(2026, 11, 3), 123450), _r("b2", date(2026, 11, 7), 210)])
    await store.apply(
        UID, [_r("a1", date(2026, 11, 4), 123450), _r("b2", date(2026, 11, 7), 0, True)]
    )
    months = await store.months(UID)
    assert [m.month for m in months] == ["2026-11"]
    assert months[0].total_paise == 123450 and len(months[0].orders) == 1
    assert months[0].orders[0].day == "2026-11-03"  # the order's first mail


async def test_an_order_whose_mails_cross_a_month_counts_once() -> None:
    store = _spend(MemoryDocs())
    await store.apply(UID, [_r("c3", date(2026, 10, 31), 5000), _r("c3", date(2026, 11, 1), 5500)])
    months = {m.month: m for m in await store.months(UID)}
    assert set(months) == {"2026-10"} and months["2026-10"].total_paise == 5500


async def test_spend_is_sealed_and_months_past_thirteen_are_swept() -> None:
    docs = MemoryDocs()
    store = _spend(docs)
    await store.apply(UID, [_r("d4", date(2025, 9, 30), 999), _r("e5", date(2026, 11, 2), 4400)])
    assert [m.month for m in await store.months(UID)] == ["2026-11"]
    raw = json.dumps(await docs.get(f"jarvis_spend/{UID}_202611"))
    assert "BigBasket" not in raw and "paise" not in raw and '"blob"' in raw


async def test_the_scan_state_keeps_at_most_500_seen_hashes_and_is_not_sealed() -> None:
    docs = MemoryDocs()
    store = _spend(docs)
    assert (await store.scan(UID)).on is False
    seen = tuple(f"{i:032x}" for i in range(600))
    await store.set_scan(UID, lambda s: s.model_copy(update={"on": True, "seen": seen}))
    got = await store.scan(UID)
    assert got.on is True and len(got.seen) == 500 and got.seen[-1] == seen[-1]


async def test_without_a_keyring_spend_is_off() -> None:
    store = _spend(MemoryDocs(), sealed=False)
    with pytest.raises(KitchenOff):
        await store.months(UID)
    with pytest.raises(KitchenOff):
        await store.apply(UID, [])


async def test_delete_all_spend_removes_months_and_the_scan_state() -> None:
    docs = MemoryDocs()
    store = _spend(docs)
    await store.apply(UID, [_r("f6", date(2026, 11, 2), 100), _r("g7", date(2026, 10, 2), 100)])
    await store.set_scan(UID, lambda s: s.model_copy(update={"on": True}))
    assert await store.delete_all(UID) == 3
    assert await store.months(UID) == [] and (await store.scan(UID)).on is False


def test_the_keyed_hash_never_shows_the_text() -> None:
    store = _spend(MemoryDocs())
    h = store.key(UID, "order:bigbasket:BB-ORDER-1001")
    assert len(h) == 32 and "BB" not in h and h == store.key(UID, "order:bigbasket:BB-ORDER-1001")
    assert h != store.key("u_other", "order:bigbasket:BB-ORDER-1001")
