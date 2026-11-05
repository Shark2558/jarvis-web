# tests/test_faces_service.py -- R3 D13: add / update / delete / ack / bridge state / pictures.
from __future__ import annotations

import pytest
from faces_fakes import UID, add_adult, add_child, enrol, faces

from jarvis.faces.service import PersonRejected
from jarvis.faces.store import FacesUnavailable
from jarvis.home.ports import Ack, Heartbeat, HeartbeatParts


async def test_nobody_is_enrolled_by_default() -> None:
    f = faces()
    view = await f.svc.view(UID)
    assert view.people == () and view.total == 0 and view.limit == 30
    assert (await f.svc.state_part(UID)).faces is not None
    assert (await f.svc.state_part(UID)).faces.people == ()  # type: ignore[union-attr]


async def test_add_starts_consented_not_enrolled_and_tells_the_bridge_the_id_only() -> None:
    f = faces()
    p = await add_adult(f)
    assert p.state == "consented" and p.id.startswith("fp_")
    (call,) = f.home.calls
    assert call[1] == "/bridge/v1/state"
    assert call[2] == {"faces": {"rev": 1, "people": [p.id], "deleting": []}}
    assert "Anjali" not in str(call)


async def test_name_rules() -> None:
    f = faces()
    await add_adult(f, "Anjali")
    for bad, code in (("   ", "no_name"), ("x" * 41, "too_long"), ("anjali", "duplicate_name")):
        with pytest.raises(PersonRejected) as err:
            await add_adult(f, bad)
        assert err.value.code == code
    with pytest.raises(PersonRejected) as err:
        await add_adult(f, "Ravi", relation="boss")
    assert err.value.code == "bad_relation"


async def test_at_most_thirty_people() -> None:
    f = faces()
    for i in range(30):
        await add_adult(f, f"P{i}")
    with pytest.raises(PersonRejected) as err:
        await add_adult(f, "One too many")
    assert err.value.code == "people_full" and err.value.status == 409


async def test_update_changes_name_relation_vip_but_not_the_child_mark() -> None:
    f = faces()
    p = await add_adult(f)
    new = await f.svc.update(UID, p.id, name="Anju", relation="family", vip=True)
    assert (new.name, new.relation, new.vip, new.child) == ("Anju", "family", True, False)
    assert new.consent_at == p.consent_at  # editing never refreshes consent
    with pytest.raises(PersonRejected) as err:
        await f.svc.update(UID, "fp_000000000000", vip=True)
    assert err.value.status == 404


async def test_a_person_being_deleted_cannot_be_edited() -> None:
    f = faces(online=False)
    p = await add_adult(f)
    await f.svc.remove(UID, p.id)
    with pytest.raises(PersonRejected):
        await f.svc.update(UID, p.id, vip=True)


async def test_delete_marks_deleting_pushes_and_the_ack_removes_the_record() -> None:
    f = faces()
    p = await add_adult(f)
    res = await f.svc.remove(UID, p.id)
    assert res.pushed is True
    assert f.home.calls[-1][2] == {"faces": {"rev": 2, "people": [], "deleting": [p.id]}}
    assert (await f.svc.view(UID)).total == 0  # the name mapping is gone at once
    assert (await f.store.load(UID)).people[0].state == "deleting"
    await f.svc.handle(
        UID,
        Ack.model_validate(
            {"type": "ack", "id": "e1", "at": 1.0, "what": "face_deleted", "person": p.id}
        ),
    )
    assert (await f.store.load(UID)).people == ()
    (entry,) = f.audit.entries
    assert entry["args"] == {"count": 1} and "Anjali" not in str(entry)


async def test_laptop_off_the_delete_waits_and_the_next_heartbeat_reply_carries_it() -> None:
    f = faces(online=False)
    p = await add_adult(f)
    res = await f.svc.remove(UID, p.id)
    assert res.pushed is False
    part = await f.svc.state_part(UID)
    assert part.faces is not None and part.faces.deleting == (p.id,) and part.faces.people == ()
    view = await f.svc.view(UID)
    assert view.people[0].state == "deleting"


async def test_a_second_delete_is_harmless_and_unknown_is_404() -> None:
    f = faces(online=False)
    p = await add_adult(f)
    await f.svc.remove(UID, p.id)
    await f.svc.remove(UID, p.id)
    with pytest.raises(PersonRejected) as err:
        await f.svc.remove(UID, "fp_000000000000")
    assert err.value.status == 404


async def test_a_stray_ack_never_deletes_a_consented_person() -> None:
    f = faces()
    p = await add_adult(f)
    assert await f.svc.ack(UID, p.id) is False
    assert await f.svc.ack(UID, "fp_000000000000") is False
    assert len((await f.store.load(UID)).people) == 1
    assert f.audit.entries == []


async def test_delete_all_marks_everyone_and_returns_the_count() -> None:
    f = faces(online=False)
    await add_adult(f, "A")
    await add_child(f, "B")
    assert await f.svc.remove_all(UID) == 2
    assert await f.svc.remove_all(UID) == 0
    assert (await f.svc.view(UID)).total == 0


async def test_pictures_move_a_person_between_consented_and_enrolled() -> None:
    f = faces()
    p = await add_adult(f)
    await enrol(f, p, 4)
    assert (await f.store.load(UID)).people[0].state == "enrolled"
    assert (await f.svc.view(UID)).people[0].pictures == 4
    rev = (await f.store.load(UID)).rev
    await enrol(f, p, 4)  # unchanged: no write
    assert (await f.store.load(UID)).rev == rev
    await f.svc.apply_pictures(UID, {"fp_0000000000aa": 3})  # an id nobody knows is ignored
    assert (await f.store.load(UID)).rev == rev
    await enrol(f, p, 0)
    assert (await f.store.load(UID)).people[0].state == "consented"


async def test_heartbeat_event_carries_the_counts() -> None:
    f = faces()
    p = await add_adult(f)
    beat = Heartbeat(
        type="heartbeat",
        id="h1",
        at=1.0,
        bridge_version="1.0.0",
        state_rev=1,
        parts=HeartbeatParts(faces={p.id: 3}),
    )
    await f.svc.handle(UID, beat)
    assert (await f.store.load(UID)).people[0].state == "enrolled"


async def test_events_on_an_unreadable_registry_are_dropped_quietly() -> None:
    f = faces()
    p = await add_adult(f)
    f.docs._data["jarvis_faces/" + UID]["blob"] = "x"  # type: ignore[attr-defined]
    await f.svc.handle(
        UID,
        Ack.model_validate(
            {"type": "ack", "id": "e1", "at": 1.0, "what": "face_deleted", "person": p.id}
        ),
    )
    with pytest.raises(FacesUnavailable):
        await f.store.load(UID)
    assert (await f.svc.state_part(UID)).faces is None  # "unchanged" for the bridge


async def test_export_has_consent_records_and_no_pictures() -> None:
    f = faces()
    await add_adult(f)
    data = await f.svc.export(UID)
    assert data["people"][0]["consent"]["version"] == "fc1"
    assert data["pictures"] == "only on your laptop"


async def test_no_home_means_nothing_is_pushed_and_nothing_breaks() -> None:
    f = faces()
    f.svc._home = None  # type: ignore[attr-defined]
    p = await add_adult(f)
    assert (await f.svc.remove(UID, p.id)).pushed is False
