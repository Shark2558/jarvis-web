# tests/test_r4_i2_erasure.py -- R4 I2 F3: privacy erasure completes (Photos state, People cache),
# and a refused target's name is never persisted.
from __future__ import annotations

from typing import Any

from photos_fakes import C1, rig

from jarvis.api.r4_wiring import FacesAndPhotosPrivacy
from jarvis.integrations.google import GoogleNotConnected
from jarvis.people.cache import TTL_S, DossierCache
from jarvis.people.models import Dossier
from jarvis.people.privacy import PeoplePrivacy
from jarvis.photos.picker import PickerClient
from jarvis.photos.service import PhotosData, PhotosState
from jarvis.storage.docs import MemoryDocs

UID = "owner"


class Disconnected:
    async def request(self, *a: Any, **k: Any) -> Any:
        raise GoogleNotConnected("not connected")


async def test_picker_delete_session_survives_a_disconnected_google() -> None:
    await PickerClient(Disconnected()).delete_session(UID, "sess1")  # type: ignore[arg-type]


async def test_purge_clears_the_state_even_when_ending_the_google_session_fails() -> None:
    r = rig()

    async def boom(uid: str, sid: str) -> None:
        raise GoogleNotConnected("gone")

    r.picker.delete_session = boom  # type: ignore[method-assign]
    await r.state.put(UID, PhotosData("sess1", (C1,), "2999-01-01T00:00:00Z", ()))

    try:
        await r.svc.purge(UID)
    except GoogleNotConnected:
        pass

    assert await r.state.get(UID) == PhotosData()


async def test_delete_all_purges_stale_photos_state_when_photos_is_off() -> None:
    docs = MemoryDocs()
    state = PhotosState(docs)
    await state.put(UID, PhotosData(None, (C1,), "", ()))

    class Faces:
        async def remove_all(self, uid: str) -> int:
            return 0

    src = FacesAndPhotosPrivacy(Faces(), None, stale=state)  # type: ignore[arg-type]
    await src.delete(UID)

    assert await state.get(UID) == PhotosData()


# ---- people cache -----------------------------------------------------------------------------


def dossier(name: str = "Satya Nadella") -> Dossier:
    return Dossier(name=name, context="")


async def test_a_refused_target_is_never_persisted() -> None:
    docs = MemoryDocs()
    cache = DossierCache(docs)

    await cache.put(UID, "Private Person", "neighbour", None)

    assert await cache.get(UID) is not None  # in-process follow-up check still works
    assert all("Private Person" not in repr(d) for _, d in await _all(docs))


async def test_an_expired_entry_is_deleted_from_the_store_on_read() -> None:
    docs = MemoryDocs()
    now = [1000.0]
    cache = DossierCache(docs, clock=lambda: now[0])
    await cache.put(UID, "Satya Nadella", "Microsoft", dossier())
    assert await _all(docs)
    now[0] += TTL_S + 1
    fresh = DossierCache(docs, clock=lambda: now[0])  # a restart: nothing in memory

    assert await fresh.get(UID) is None
    assert await _all(docs) == []


async def test_the_stored_entry_carries_expires_at() -> None:
    docs = MemoryDocs()
    cache = DossierCache(docs, clock=lambda: 1000.0)
    await cache.put(UID, "Satya Nadella", "Microsoft", dossier())

    ((_, doc),) = await _all(docs)

    assert doc["expires_at"] == 1000.0 + TTL_S


async def test_the_people_privacy_source_exports_and_deletes_the_last_research() -> None:
    docs = MemoryDocs()
    cache = DossierCache(docs)
    await cache.put(UID, "Satya Nadella", "Microsoft", dossier())
    src = PeoplePrivacy(cache)

    view = await src.describe(UID)
    exported = await src.export(UID)
    removed = await src.delete(UID)

    assert view.id == "people_research" and view.count == 1 and view.delete != "none"
    assert exported is not None and exported["name"] == "Satya Nadella"
    assert removed == 1 and await cache.get(UID) is None and await _all(docs) == []
    assert await src.export(UID) is None


async def _all(docs: MemoryDocs) -> list[tuple[str, dict[str, Any]]]:
    from jarvis.storage.docs import Query

    return list(await docs.query(Query("jarvis_people_last")))
