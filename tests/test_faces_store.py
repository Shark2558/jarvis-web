# tests/test_faces_store.py -- R3 D13/D14: the registry is AES-GCM under the `faces` key, AAD;
# nothing readable in Firestore; swapped / tampered / wrong-key data is refused, never overwritten.
from __future__ import annotations

import pytest
from faces_fakes import OTHER, ROOT, UID, add_adult, add_child, faces

from jarvis.faces.models import Person, State
from jarvis.faces.store import FacesStore, FacesUnavailable
from jarvis.keyring import Keyring
from jarvis.storage.docs import MemoryDocs


async def test_nothing_readable_lands_in_firestore() -> None:
    f = faces()
    await add_adult(f, "Anjali Verma")
    await add_child(f, "Mini")
    data = f.docs._data  # type: ignore[attr-defined]
    assert data, "the registry must have been written"
    # Only the envelope's own fields are searched for the needles: the sealed blob is random
    # text, and a short needle turns up in it by chance (main CI #79 found "fc1"). The blob is
    # proved sealed by opening it with the faces key and the owner's AAD, so nothing collides.
    envelope = {path: {k: v for k, v in doc.items() if k != "blob"} for path, doc in data.items()}
    dump = str(envelope).lower()
    for needle in ("anjali", "verma", "mini", "friend", "parent_guardian", "fc1"):
        assert needle not in dump
    cipher = Keyring(ROOT).cipher("faces")
    for path, doc in data.items():
        assert set(doc) == {"rev", "v", "kid", "blob", "updated_at"}
        uid = path.split("/", 1)[1]
        assert " " not in doc["blob"]  # base64 text: the spaced full name can never appear in it
        plain = cipher.decrypt(doc["blob"], aad=FacesStore._aad(uid)).decode()
        assert "Anjali Verma" in plain and "Mini" in plain and "fc1" in plain


async def test_round_trip_and_rev() -> None:
    f = faces()
    p = await add_adult(f)
    state = await f.store.load(UID)
    assert state.rev == 1 and state.people == (p,)


async def test_an_empty_owner_loads_nobody() -> None:
    assert await faces().store.load(UID) == State()


async def test_another_owners_registry_cannot_be_swapped_in() -> None:
    f = faces()
    await add_adult(f)
    data = f.docs._data  # type: ignore[attr-defined]
    data["jarvis_faces/" + OTHER] = dict(data["jarvis_faces/" + UID])
    with pytest.raises(FacesUnavailable):
        await f.store.load(OTHER)


async def test_wrong_key_and_tampering_fail_closed_and_are_not_overwritten() -> None:
    f = faces()
    await add_adult(f)
    other = FacesStore(f.docs, Keyring(bytes(range(40, 72))))
    with pytest.raises(FacesUnavailable):
        await other.load(UID)
    with pytest.raises(FacesUnavailable):
        await other.change(UID, lambda s: s)
    assert (await FacesStore(f.docs, Keyring(ROOT)).load(UID)).rev == 1
    f.docs._data["jarvis_faces/" + UID]["blob"] = "AAAA"  # type: ignore[attr-defined]
    with pytest.raises(FacesUnavailable):
        await f.store.load(UID)


async def test_storage_trouble_is_plain_and_hides_the_cause() -> None:
    class Broken(MemoryDocs):
        async def get(self, path: str) -> None:
            raise RuntimeError("firestore internal detail 10.0.0.7")

    with pytest.raises(FacesUnavailable) as err:
        await FacesStore(Broken(), Keyring(ROOT)).load(UID)
    assert "firestore" not in str(err.value) and "10.0.0.7" not in str(err.value)


async def test_a_failed_write_changes_nothing() -> None:
    f = faces()
    await add_adult(f)

    async def boom(_fn: object) -> None:
        raise RuntimeError("tx down")

    f.docs.transaction = boom  # type: ignore[method-assign]
    with pytest.raises(FacesUnavailable):
        await f.store.change(UID, lambda s: s)


async def test_a_bad_owner_id_is_refused() -> None:
    with pytest.raises(ValueError):
        await faces().store.load("../x")


async def test_wipe_removes_the_document() -> None:
    f = faces()
    await add_adult(f)
    await f.store.wipe(UID)
    assert await f.store.load(UID) == State()


def test_a_child_cannot_be_recorded_with_an_adults_consent() -> None:
    kw = dict(
        id="fp_aaaaaaaaaaaa",
        name="M",
        relation="family",
        vip=False,
        consent_version="fc1",
        consent_at="2026-11-05T12:00:00+00:00",
        state="consented",
        created_at="2026-11-05T12:00:00+00:00",
    )
    with pytest.raises(ValueError):
        Person(child=True, given_by="self", **kw)  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        Person(child=False, given_by="parent_guardian", **kw)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "bad",
    [
        None,
        {"consent": 1},
        {"consent": {}, "id": "x"},
    ],
)
def test_bad_records_are_refused(bad: object) -> None:
    with pytest.raises((ValueError, KeyError)):
        Person.from_json(bad)
