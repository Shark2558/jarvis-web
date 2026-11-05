# tests/test_vault_inbox_store.py -- R2 D9: the inbox record on the Docs port: round trip, the
# newest 500 `seen` entries, fail-closed reads, nothing from inside a file or its name stored.
from __future__ import annotations

from datetime import UTC, datetime

import pytest

from jarvis.storage.docs import MemoryDocs
from jarvis.vault_inbox.store import MAX_SEEN, Inbox, InboxStore, InboxUnreadable, Seen

UID = "u_owner"
NOW = datetime(2026, 11, 5, tzinfo=UTC)


def _box(**kw: object) -> Inbox:
    base: dict[str, object] = {
        "folder_id": "inbox1",
        "name": "Vault inbox",
        "email": "akash@example.com",
        "confirmed_at": NOW,
    }
    return Inbox(**{**base, **kw})  # type: ignore[arg-type]


async def test_round_trip_and_remove() -> None:
    st = InboxStore(MemoryDocs())
    assert await st.load(UID) is None and await st.folder_id(UID) is None
    await st.change(UID, lambda _o: _box())
    got = await st.load(UID)
    assert got is not None and got.folder_id == "inbox1" and got.email == "akash@example.com"
    assert await st.folder_id(UID) == "inbox1"
    await st.change(UID, lambda _o: None)
    assert await st.load(UID) is None


async def test_seen_keeps_the_newest_500() -> None:
    box = _box()
    for i in range(MAX_SEEN + 20):
        box = box.with_seen(f"d{i}", Seen(f"v{i}", f"v_{i:012x}", None, "t"))
    assert len(box.seen) == MAX_SEEN and "d0" not in box.seen and f"d{MAX_SEEN + 19}" in box.seen
    st = InboxStore(MemoryDocs())
    await st.change(UID, lambda _o: box)
    loaded = await st.load(UID)
    assert loaded is not None and len(loaded.seen) == MAX_SEEN


async def test_a_seen_entry_is_moved_to_the_end_when_updated() -> None:
    box = _box().with_seen("a", Seen("1")).with_seen("b", Seen("1")).with_seen("a", Seen("2"))
    assert list(box.seen) == ["b", "a"] and box.seen["a"].version == "2"


async def test_storage_trouble_and_corrupt_data_fail_closed() -> None:
    docs = MemoryDocs()
    st = InboxStore(docs)
    await st.change(UID, lambda _o: _box())
    docs._data[f"jarvis_vault_inbox/{UID}"]["folder_id"] = "bad id!"  # type: ignore[attr-defined]
    with pytest.raises(InboxUnreadable):
        await st.load(UID)
    with pytest.raises(InboxUnreadable):  # and a corrupt record is never overwritten
        await st.change(UID, lambda _o: _box(name="other"))

    class Broken(MemoryDocs):
        async def get(self, path: str) -> None:
            raise RuntimeError("firestore internal")

    with pytest.raises(InboxUnreadable) as e:
        await InboxStore(Broken()).load(UID)
    assert "firestore" not in str(e.value)


async def test_no_file_name_or_content_is_stored() -> None:
    docs = MemoryDocs()
    st = InboxStore(docs)
    await st.change(UID, lambda _o: _box().with_seen("d1", Seen("md5:x", "v_000000000001")))
    text = str(docs._data)  # type: ignore[attr-defined]
    assert "PAN" not in text and "pdf" not in text.lower()


def test_a_bad_owner_id_is_refused() -> None:
    with pytest.raises(ValueError):
        InboxStore(MemoryDocs())._path("../x")
