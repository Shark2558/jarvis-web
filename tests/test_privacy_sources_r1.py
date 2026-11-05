# tests/test_privacy_sources_r1.py - R2 D14: the R1 categories (Telegram, Activity, laptop brain,
# Groceries, family, parcels) on the Docs twin: owner-only counts, no secret in a view or export,
# deletes that empty the category and leave the others alone.
from __future__ import annotations

from datetime import UTC, date, datetime

from pydantic import SecretStr

from jarvis.activity.models import ActivityItem
from jarvis.activity.store import ActivityStore
from jarvis.family.models import Member
from jarvis.family.store import FamilyStore
from jarvis.groceries.store import GroceryStore
from jarvis.integrations.vault import TokenCipher
from jarvis.offline.store import LocalBrainStore
from jarvis.privacy import PrivacyRegistry
from jarvis.privacy.export import scrub
from jarvis.privacy.sources_r1 import (
    R1Parts,
    activity_source,
    family_source,
    groceries_source,
    offline_source,
    packages_source,
    r1_sources,
    telegram_source,
)
from jarvis.storage.docs import MemoryDocs
from jarvis.telegram.store import TelegramStore

UID = "u_owner"
OTHER = "u_other"
TODAY = date(2026, 11, 5)
NEEDLE = "NEEDLE-9137-abc"


def dump(docs: MemoryDocs) -> str:
    return repr(docs._data)


async def test_telegram_pairing_is_listed_exported_without_ids_and_unpaired() -> None:
    docs = MemoryDocs()
    store = TelegramStore(docs)
    code, _ = await store.start_pairing(UID)
    assert await store.finish_pairing(code, tg_user_id=777_001, chat_id=888_002) == UID
    src = telegram_source(store)
    v = await src.describe(UID)
    assert (v.count, v.delete, v.export) == (1, "simple", True)
    exp = await src.export(UID)
    assert exp is not None and exp["paired"] is True
    assert "777001" not in str(exp) and "888002" not in str(exp)
    assert await src.delete(UID) == 1
    assert (await src.describe(UID)).count == 0
    assert "777001" not in dump(docs).replace("_", "")
    assert await src.delete(UID) == 0


def _item(i: int, uid: str, words: str) -> ActivityItem:
    return ActivityItem(
        id=f"act_{i:020x}",
        user_id=uid,
        at=datetime(2026, 11, 4, 9, i, tzinfo=UTC),
        tool="calendar_list",
        risk="read_only",
        kind="read",
        outcome="done",
        words=words,
    )


async def test_activity_counts_the_last_week_exports_and_clears_every_day() -> None:
    docs = MemoryDocs()
    store = ActivityStore(docs)
    await store.add(_item(1, UID, f"Looked at {NEEDLE}"), "20261104")
    await store.add(_item(2, UID, "Looked"), "20261105")
    await store.add(_item(3, OTHER, "theirs"), "20261104")
    src = activity_source(store, lambda: TODAY)
    v = await src.describe(UID)
    assert v.count == 2 and v.delete == "passkey"
    exp = await src.export(UID)
    assert exp is not None and len(exp["rows"]) == 2 and NEEDLE in str(exp)
    assert await src.delete(UID) == 2
    assert (await src.describe(UID)).count == 0 and (await src.describe(OTHER)).count == 1
    assert NEEDLE not in dump(docs)


async def test_activity_delete_covers_a_day_with_more_than_one_sweep_batch() -> None:
    store = ActivityStore(MemoryDocs())
    for i in range(1, 6):
        await store.add(_item(i, UID, "x"), "20261104")
    src = activity_source(store, lambda: TODAY)
    assert await src.delete(UID) == 5


async def test_offline_shows_only_that_one_is_set_and_never_its_address_or_key() -> None:
    docs = MemoryDocs()
    cipher = TokenCipher(bytes(range(1, 33)))
    store = LocalBrainStore(docs, cipher)
    await store.put(
        url="https://laptop.example/v1",
        key=SecretStr("sk-LAPTOPKEY"),
        model="llama3",
        enabled=True,
        set_by="owner",
    )
    src = offline_source(store)
    v = await src.describe(UID)
    assert (v.count, v.delete, v.export, v.encrypted_by_jarvis) == (1, "simple", False, True)
    assert "LAPTOPKEY" not in v.model_dump_json() and "laptop.example" not in v.model_dump_json()
    assert await src.export(UID) is None
    assert await src.delete(UID) == 1
    assert (await src.describe(UID)).count == 0 and "LAPTOPKEY" not in dump(docs)


async def test_groceries_list_pointer_is_exported_and_forgotten() -> None:
    docs = MemoryDocs()
    store = GroceryStore(docs)
    await store.remember(UID, "list_abc")
    await store.remember(OTHER, "list_other")
    src = groceries_source(store)
    v = await src.describe(UID)
    assert v.count == 1 and v.delete == "simple" and "Google Tasks" in v.note
    exp = await src.export(UID)
    assert exp is not None and exp["list_id"] == "list_abc"
    assert await src.delete(UID) == 1
    assert (await src.describe(UID)).count == 0 and (await src.describe(OTHER)).count == 1


async def test_family_members_are_listed_exported_and_removed() -> None:
    store = FamilyStore(MemoryDocs())
    for i, name in enumerate(("Priya", "Arun")):
        await store.add(
            UID,
            Member(
                id=f"m{i}",
                name=name,
                calendar_id=f"{name.lower()}@example.com",
                access="reader",
                added_at="2026-11-01",
                verified_at="2026-11-01",
            ),
        )
    src = family_source(store)
    v = await src.describe(UID)
    assert v.count == 2 and v.delete == "simple"
    exp = await src.export(UID)
    assert exp is not None and {m["name"] for m in exp["members"]} == {"Priya", "Arun"}
    assert await src.delete(UID) == 2
    assert (await src.describe(UID)).count == 0


async def test_parcels_say_nothing_is_stored() -> None:
    v = await packages_source().describe(UID)
    assert v.count == 0 and v.delete == "none" and not v.export
    assert "Nothing is stored" in v.note


async def test_r1_sources_skip_what_is_off_and_always_list_parcels() -> None:
    docs = MemoryDocs()
    parts = R1Parts(telegram=TelegramStore(docs), groceries=GroceryStore(docs))
    reg = PrivacyRegistry()
    for s in r1_sources(parts):
        reg.register(s)
    assert reg.ids() == ["telegram", "groceries", "packages"]
    assert all(v.available for v in await reg.describe_all(UID))


async def test_no_r1_export_contains_a_secret_looking_key() -> None:
    docs = MemoryDocs()
    store = TelegramStore(docs)
    code, _ = await store.start_pairing(UID)
    await store.finish_pairing(code, tg_user_id=1, chat_id=2)
    exp = await telegram_source(store).export(UID)
    assert scrub(exp) == exp
