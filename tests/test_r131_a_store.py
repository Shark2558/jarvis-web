# tests/test_r131_a_store.py -- R13.1 Part A (docs/plans/r13-1-try-on.md D4, D14, "Data model"):
# the sealed `tryon/{uid}` document. Purpose `tryon`, AAD `tryon/{uid}/v1`, a plain `owner` and
# `updated_at` (found and deleted without the key, R13 I1's M1 rule), at most 200 KB sealed. No
# keyring or no storage: Off, nothing in clear. An unreadable document is never overwritten.
from __future__ import annotations

import json

import pytest
from r131_fakes import NOW, RING, UID, FixedClock, sample_body

from jarvis.keyring import Keyring
from jarvis.storage.docs import MemoryDocs, Set
from jarvis.wardrobe.tryon import model as m
from jarvis.wardrobe.tryon.store import Off, TooBig, TryonDoc, TryonStore, Unreadable

PREFIX = "jarvis_"
PATH = f"{PREFIX}tryon/{UID}"


def _store(docs: MemoryDocs | None = None, ring: Keyring | None = RING) -> TryonStore:
    return TryonStore(docs if docs is not None else MemoryDocs(), ring, prefix=PREFIX,
                      now=FixedClock(NOW))  # fmt: skip


async def test_nothing_kept_reads_as_an_empty_document() -> None:
    doc = await _store().read(UID)
    assert doc == TryonDoc() and doc.current is None and doc.saved == () and doc.assets == {}


async def test_a_change_is_sealed_with_a_plain_owner_and_updated_at() -> None:
    docs = MemoryDocs()
    store = _store(docs)
    body = sample_body(178)
    await store.change(UID, lambda d: d.model_copy(update={"current": body}))
    raw = await docs.get(PATH)
    assert raw is not None and raw["owner"] == UID and raw["updated_at"] == NOW.isoformat()
    assert set(raw) == {"owner", "rev", "blob", "updated_at"}
    assert "178" not in json.dumps(raw)  # never in clear
    plain = RING.cipher("tryon").decrypt(raw["blob"], aad=m.aad_tryon(UID))
    assert json.loads(plain)["current"]["height"] == 178
    assert (await store.read(UID)).current == body


async def test_the_blob_opens_only_under_its_own_owner_and_purpose() -> None:
    docs = MemoryDocs()
    await _store(docs).change(UID, lambda d: d.model_copy(update={"current": sample_body()}))
    raw = await docs.get(PATH)
    assert raw is not None
    await docs.write([Set(f"{PREFIX}tryon/someone-else", {**raw, "owner": "someone-else"})])
    with pytest.raises(Unreadable):
        await _store(docs).read("someone-else")  # AAD names the owner: a moved blob won't open
    with pytest.raises(Exception):  # noqa: B017 - any refusal: another purpose's key
        RING.cipher("wardrobe").decrypt(raw["blob"], aad=m.aad_tryon(UID))


async def test_each_change_bumps_the_rev() -> None:
    docs = MemoryDocs()
    store = _store(docs)
    for _ in range(3):
        await store.change(UID, lambda d: d)
    raw = await docs.get(PATH)
    assert raw is not None and raw["rev"] == 3


async def test_an_unreadable_document_is_never_overwritten() -> None:
    docs = MemoryDocs()
    await _store(docs).change(UID, lambda d: d.model_copy(update={"current": sample_body()}))
    before = await docs.get(PATH)
    other = _store(docs, Keyring(bytes(range(1, 33))))  # the key changed
    with pytest.raises(Unreadable):
        await other.read(UID)
    with pytest.raises(Unreadable):
        await other.change(UID, lambda d: d.model_copy(update={"current": sample_body(180)}))
    assert await docs.get(PATH) == before


async def test_a_document_past_200_kb_sealed_is_refused_and_nothing_is_written() -> None:
    docs = MemoryDocs()
    store = _store(docs)
    await store.change(UID, lambda d: d.model_copy(update={"current": sample_body()}))
    before = await docs.get(PATH)
    huge = {f"wi_{n:012x}": {"template": "shirt"} for n in range(6000)}
    with pytest.raises(TooBig):
        await store.change(UID, lambda d: d.model_copy(update={"assets": huge}))
    assert await docs.get(PATH) == before


async def test_no_keyring_or_no_storage_is_off_and_writes_nothing() -> None:
    docs = MemoryDocs()
    for store in (_store(docs, None), TryonStore(None, RING, prefix=PREFIX, now=FixedClock(NOW))):
        assert store.available is False
        with pytest.raises(Off):
            await store.read(UID)
        with pytest.raises(Off):
            await store.change(UID, lambda d: d)
    assert await docs.get(PATH) is None


async def test_present_and_delete_need_no_key() -> None:
    docs = MemoryDocs()
    await _store(docs).change(UID, lambda d: d)
    keyless = _store(docs, None)
    assert await keyless.present(UID) is True
    assert await keyless.delete(UID) == 1 and await docs.get(PATH) is None
    assert await keyless.present(UID) is False and await keyless.delete(UID) == 0


async def test_a_bad_owner_id_never_reaches_a_path() -> None:
    with pytest.raises(ValueError):
        await _store().read("../wardrobe/x")


def test_the_document_bounds_its_lists() -> None:
    body = sample_body()
    with pytest.raises(ValueError):
        TryonDoc(earlier=(body,) * (m.EARLIER_MAX + 1))
    TryonDoc(earlier=(body,) * m.EARLIER_MAX)  # five are fine


async def test_the_stamp_is_the_plain_rev_and_time_with_no_key() -> None:
    docs = MemoryDocs()
    assert await _store(docs, None).stamp(UID) is None
    await _store(docs).change(UID, lambda d: d)
    await _store(docs).change(UID, lambda d: d)
    assert await _store(docs, None).stamp(UID) == (2, NOW.isoformat())
