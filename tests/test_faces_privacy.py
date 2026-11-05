# tests/test_faces_privacy.py -- R3 D14: the `faces` privacy source replaces the placeholder: count,
# rev, export (consent records, no pictures), delete (names gone now, record kept until the
# laptop acks), Privacy count 0 afterwards, another owner untouched.
from __future__ import annotations

from faces_fakes import OTHER, UID, add_adult, add_child, faces

from jarvis.faces.privacy import FacesPrivacy
from jarvis.home.ports import Ack
from jarvis.privacy.ports import PrivacyRegistry, PrivacySource


async def test_describe_counts_people_and_rev_changes_with_the_data() -> None:
    f = faces()
    p = FacesPrivacy(f.svc)
    assert isinstance(p, PrivacySource) and p.section == "Faces" and p.id == "faces"
    empty = await p.describe(UID)
    assert empty.count == 0 and empty.delete == "none"
    await add_adult(f)
    one = await p.describe(UID)
    assert one.count == 1 and one.delete == "passkey" and one.export and one.encrypted_by_jarvis
    assert one.rev and one.rev != empty.rev and "laptop" in one.where


async def test_no_service_is_a_plain_unavailable_row() -> None:
    view = await FacesPrivacy(None).describe(UID)
    assert view.count == 0 and "no encryption key" in view.note
    assert await FacesPrivacy(None).export(UID) is None
    assert await FacesPrivacy(None).delete(UID) == 0


async def test_delete_all_leaves_count_zero_and_waits_for_the_laptop() -> None:
    f = faces(online=False)
    p = FacesPrivacy(f.svc)
    a = await add_adult(f)
    await add_child(f)
    assert await p.delete(UID) == 2
    after = await p.describe(UID)
    assert after.count == 0 and after.delete == "none" and "2 being deleted" in after.note
    assert len((await f.store.load(UID)).people) == 2  # records stay until the laptop answers
    await f.svc.handle(
        UID,
        Ack.model_validate(
            {"type": "ack", "id": "e1", "at": 1.0, "what": "face_deleted", "person": a.id}
        ),
    )
    assert len((await f.store.load(UID)).people) == 1


async def test_export_is_consent_records_without_pictures_or_deleting_people() -> None:
    f = faces(online=False)
    p = FacesPrivacy(f.svc)
    a = await add_adult(f, "Anjali")
    await add_adult(f, "Ravi")
    await f.svc.remove(UID, a.id)
    data = await p.export(UID)
    assert data is not None and [x["name"] for x in data["people"]] == ["Ravi"]
    assert "image" not in str(data).replace("images_at_home", "")


async def test_another_owner_is_untouched() -> None:
    f = faces()
    await add_adult(f)
    await f.svc.add(
        OTHER,
        name="Z",
        relation="other",
        child=False,
        vip=False,
        given_by="self",
        consent_version="fc1",
        confirm=True,
    )
    await FacesPrivacy(f.svc).delete(UID)
    assert (await FacesPrivacy(f.svc).describe(OTHER)).count == 1


async def test_a_failing_store_keeps_its_row() -> None:
    f = faces()
    reg = PrivacyRegistry()
    reg.register(FacesPrivacy(f.svc))

    async def boom(*_: object) -> None:
        raise RuntimeError("x")

    f.store.load = boom  # type: ignore[method-assign]
    (view,) = await reg.describe_all(UID)
    assert view.id == "faces" and view.available is False
