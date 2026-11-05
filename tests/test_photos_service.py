# tests/test_photos_service.py -- R4 D8: pick -> home edge -> faces, consent-gated.
# Non-negotiables: consent gate blocks naming without a yes; a stranger is never named or
# auto-enrolled; pictures go to the home edge only and the cloud keeps ids only.
from __future__ import annotations

import asyncio
import json

import pytest
from faces_fakes import UID, add_adult, add_child, enrol
from photos_fakes import C1, C2, JPEG, consent_args, rig

from jarvis.faces.service import PersonRejected
from jarvis.integrations.google import GoogleNotFound
from jarvis.photos.models import FaceHit
from jarvis.photos.service import NoSession

PID = "fp_0123456789ab"


async def test_begin_creates_a_session_and_remembers_only_its_id() -> None:
    r = rig()
    s = await r.svc.begin(UID)
    assert s.picker_uri.startswith("https://photos.google.com/")
    assert (await r.state.get(UID)).session_id == "sess1"


async def test_begin_refuses_when_the_faces_feature_has_no_registry() -> None:
    r = rig()
    r.svc._faces = None  # noqa: SLF001
    with pytest.raises(NoSession):
        await r.svc.begin(UID)


async def test_collect_without_a_session_says_so() -> None:
    r = rig()
    assert (await r.svc.collect(UID)).status == "no_session"


async def test_collect_waits_until_the_owner_has_picked() -> None:
    r = rig(ready=False)
    await r.svc.begin(UID)
    res = await r.svc.collect(UID)
    assert res.status == "waiting" and r.edge.received == []


async def test_selected_photos_go_to_the_edge_and_the_session_is_closed() -> None:
    r = rig([(FaceHit(C1, None, 0.5),), ()])
    await r.svc.begin(UID)
    res = await r.svc.collect(UID)
    assert res.status == "done" and res.photos == 2 and res.faces_found == 1
    assert r.edge.received == [JPEG, JPEG]
    assert r.picker.deleted == ["sess1"]
    assert (await r.state.get(UID)).session_id is None


async def test_a_stranger_is_never_named() -> None:
    r = rig([(FaceHit(C1, None, 0.99),)])
    await r.svc.begin(UID)
    res = await r.svc.collect(UID)
    assert res.recognised == () and res.unknown_clusters == (C1,)


async def test_a_recognised_enrolled_consented_person_is_named() -> None:
    r = rig()
    p = await add_adult(r.f)
    await enrol(r.f, p)
    r.edge.script = [(FaceHit(C1, p.id, 0.95),)]
    await r.svc.begin(UID)
    res = await r.svc.collect(UID)
    assert [x.name for x in res.recognised] == ["Anjali"] and res.unknown_clusters == ()


async def test_a_low_score_match_is_treated_as_unknown() -> None:
    r = rig()
    p = await add_adult(r.f)
    await enrol(r.f, p)
    r.edge.script = [(FaceHit(C1, p.id, 0.5),)]
    await r.svc.begin(UID)
    res = await r.svc.collect(UID)
    assert res.recognised == () and res.unknown_clusters == (C1,)


async def test_a_person_without_enrolment_is_not_named_even_if_the_edge_says_so() -> None:
    r = rig()
    p = await add_adult(r.f)  # consented, not enrolled
    r.edge.script = [(FaceHit(C1, p.id, 0.99),)]
    await r.svc.begin(UID)
    assert (await r.svc.collect(UID)).recognised == ()


async def test_an_unknown_person_id_from_the_edge_is_not_named() -> None:
    r = rig([(FaceHit(C1, PID, 0.99),)])
    await r.svc.begin(UID)
    assert (await r.svc.collect(UID)).recognised == ()


async def test_a_child_is_reported_as_a_child_flag_for_the_tool_to_mask() -> None:
    r = rig()
    c = await add_child(r.f)
    await enrol(r.f, c)
    r.edge.script = [(FaceHit(C1, c.id, 0.95),)]
    await r.svc.begin(UID)
    (rec,) = (await r.svc.collect(UID)).recognised
    assert rec.child is True


async def test_laptop_offline_keeps_the_session_for_a_retry() -> None:
    r = rig(online=False)
    await r.svc.begin(UID)
    res = await r.svc.collect(UID)
    assert res.status == "laptop_offline" and r.picker.deleted == []
    assert (await r.state.get(UID)).session_id == "sess1"


async def test_unknown_clusters_are_remembered_as_ids_only() -> None:
    r = rig([(FaceHit(C1, None, 0.4), FaceHit(C2, None, 0.4))])
    await r.svc.begin(UID)
    await r.svc.collect(UID)
    stored = json.dumps(r.f.docs._data, default=str)  # noqa: SLF001
    assert C1 in stored and "image" not in stored.lower() and "embedding" not in stored.lower()


# ---- enrolment: consent-gated, never automatic --------------------------------------------


async def _with_cluster(contacts: tuple[str, ...] = ()):
    r = rig([(FaceHit(C1, None, 0.5),)], contacts=contacts)
    await r.svc.begin(UID)
    await r.svc.collect(UID)
    return r


async def test_enrol_without_a_yes_is_refused_and_nothing_reaches_the_edge() -> None:
    r = await _with_cluster()
    with pytest.raises(PersonRejected) as err:
        await r.svc.enrol(UID, C1, name="Anjali", **consent_args(confirm=False))
    assert err.value.code == "consent_missing"
    assert r.edge.enrolled == [] and (await r.f.svc.state(UID)).people == ()


async def test_enrol_for_a_child_needs_a_guardian() -> None:
    r = await _with_cluster()
    with pytest.raises(PersonRejected) as err:
        await r.svc.enrol(UID, C1, name="Mini", **consent_args(child=True, given_by="self"))
    assert err.value.code == "child_needs_guardian" and r.edge.enrolled == []


async def test_enrol_with_consent_registers_the_person_and_tells_the_edge() -> None:
    r = await _with_cluster()
    out = await r.svc.enrol(UID, C1, name="Anjali", **consent_args())
    assert r.edge.enrolled == [(C1, out.person.id)] and out.at_home is True
    assert (await r.state.get(UID)).clusters == ()


async def test_enrol_refuses_a_cluster_the_cloud_never_saw() -> None:
    r = await _with_cluster()
    with pytest.raises(PersonRejected) as err:
        await r.svc.enrol(UID, C2, name="Anjali", **consent_args())
    assert err.value.code == "unknown_face" and r.edge.enrolled == []


async def test_enrol_when_the_laptop_is_off_keeps_the_person_and_the_cluster() -> None:
    r = await _with_cluster()
    r.edge.online = False
    out = await r.svc.enrol(UID, C1, name="Anjali", **consent_args())
    assert out.at_home is False and len((await r.f.svc.state(UID)).people) == 1
    assert C1 in (await r.state.get(UID)).clusters  # still finishable


async def test_offline_then_retry_links_the_same_person_without_adding_twice() -> None:
    r = await _with_cluster()
    r.edge.online = False
    first = await r.svc.enrol(UID, C1, name="Anjali", **consent_args())
    r.edge.online = True
    again = await r.svc.enrol(UID, C1, name="Anjali", **consent_args())
    assert again.at_home is True and again.person.id == first.person.id
    assert r.edge.enrolled == [(C1, first.person.id)]
    assert len((await r.f.svc.state(UID)).people) == 1
    data = await r.state.get(UID)
    assert data.clusters == () and data.pending == ()


async def test_a_home_unavailable_from_a_custom_edge_is_also_offline() -> None:
    from jarvis.home.ports import HomeOffline

    r = await _with_cluster()

    async def boom(uid: str, cluster: str, person_id: str) -> None:
        raise HomeOffline()

    r.edge.enrol = boom  # type: ignore[method-assign]
    out = await r.svc.enrol(UID, C1, name="Anjali", **consent_args())
    assert out.at_home is False and (await r.state.get(UID)).pending


async def test_a_pending_person_deleted_meanwhile_cannot_be_linked() -> None:
    r = await _with_cluster()
    r.edge.online = False
    out = await r.svc.enrol(UID, C1, name="Anjali", **consent_args())
    await r.f.svc.remove(UID, out.person.id)
    r.edge.online = True
    with pytest.raises(PersonRejected) as err:
        await r.svc.enrol(UID, C1, name="Anjali", **consent_args())
    assert err.value.code == "unknown_face" and r.edge.enrolled == []


async def test_a_child_is_never_matched_against_contacts() -> None:
    r = await _with_cluster(("Mini",))
    out = await r.svc.enrol(
        UID, C1, name="Mini", **consent_args(child=True, given_by="parent_guardian")
    )
    assert out.contact_matched is False and r.contacts.queries == []


async def test_collect_never_enrols_anyone_by_itself() -> None:
    r = await _with_cluster()
    assert r.edge.enrolled == [] and (await r.f.svc.state(UID)).people == ()


# ---- contacts ---------------------------------------------------------------------------


async def test_suggest_matches_a_google_contact_by_exact_name() -> None:
    r = await _with_cluster(("Anjali Nair", "Anjali"))
    m = await r.svc.match_contact(UID, "anjali")
    assert m is not None and m.name == "Anjali"


async def test_suggest_returns_none_when_no_exact_contact() -> None:
    r = await _with_cluster(("Anjali Nair",))
    assert await r.svc.match_contact(UID, "Anjali") is None


async def test_contacts_not_available_means_no_match_not_an_error() -> None:
    r = await _with_cluster()
    r.svc._contacts = None  # noqa: SLF001
    assert await r.svc.match_contact(UID, "Anjali") is None


async def test_an_expired_picker_session_is_forgotten_so_a_new_one_can_start() -> None:
    r = rig()
    await r.svc.begin(UID)

    async def gone(uid: str, sid: str):  # noqa: ANN202
        raise GoogleNotFound("gone")

    r.picker.get_session = gone  # type: ignore[method-assign]
    assert (await r.svc.collect(UID)).status == "no_session"
    assert (await r.state.get(UID)).session_id is None


# ---- review fixes: streaming, locking, budget, session hygiene --------------------------------


async def test_photos_are_processed_one_at_a_time_never_batched() -> None:
    r = rig([(), (), ()], items=3)
    await r.svc.begin(UID)
    await r.svc.collect(UID)
    assert r.picker.events == [
        "download m0", "analyse 1", "download m1", "analyse 1", "download m2", "analyse 1",
    ]  # fmt: skip


async def test_an_unreadable_photo_is_skipped_and_the_rest_still_go() -> None:
    r = rig([(FaceHit(C1, None, 0.5),)], items=3)
    r.picker.fail = {"m0"}
    await r.svc.begin(UID)
    res = await r.svc.collect(UID)
    assert res.status == "done" and res.photos == 2 and res.skipped == 1


async def test_begin_deletes_the_previous_google_session_first() -> None:
    r = rig()
    await r.svc.begin(UID)
    await r.svc.begin(UID)
    assert r.picker.deleted == ["sess1"]
    assert (await r.state.get(UID)).session_id == "sess2"


async def test_concurrent_collects_for_one_owner_do_not_double_process(monkeypatch) -> None:  # noqa: ANN001
    r = rig([(), ()], items=2)
    r.picker.slow = 0.01
    await r.svc.begin(UID)
    a, b = await asyncio.gather(r.svc.collect(UID), r.svc.collect(UID))
    assert sorted([a.status, b.status]) == ["done", "no_session"]
    assert r.picker.events.count("download m0") == 1


async def test_collect_has_a_global_time_budget_and_keeps_the_session(monkeypatch) -> None:  # noqa: ANN001
    import jarvis.photos.service as svc_mod

    monkeypatch.setattr(svc_mod, "COLLECT_BUDGET_S", 0.05)
    r = rig([(), ()], items=2)
    r.picker.slow = 0.2
    await r.svc.begin(UID)
    res = await r.svc.collect(UID)
    assert res.status == "timed_out"
    assert (await r.state.get(UID)).session_id == "sess1" and r.picker.deleted == []


async def test_a_bad_edge_reply_is_reported_apart_from_offline() -> None:
    r = rig([()])
    r.edge.bad = True
    await r.svc.begin(UID)
    res = await r.svc.collect(UID)
    assert res.status == "edge_error" and r.picker.deleted == []


async def test_waiting_gives_the_picker_link_back() -> None:
    r = rig(ready=False)
    await r.svc.begin(UID)
    res = await r.svc.collect(UID)
    assert res.status == "waiting" and res.picker_uri.startswith("https://photos.google.com/")


async def test_a_locally_expired_session_is_cleared_without_calling_google() -> None:
    from datetime import UTC, datetime

    r = rig()
    r.picker.expires = "2026-11-05T10:00:00Z"
    r.svc._now = lambda: datetime(2026, 11, 5, 11, tzinfo=UTC)  # noqa: SLF001
    await r.svc.begin(UID)
    res = await r.svc.collect(UID)
    assert res.status == "no_session" and (await r.state.get(UID)).session_id is None
    assert r.picker.events == []


async def test_a_stale_list_items_404_self_heals() -> None:
    r = rig()
    await r.svc.begin(UID)

    async def gone(uid: str, sid: str):  # noqa: ANN202
        raise GoogleNotFound("gone")

    r.picker.list_items = gone  # type: ignore[method-assign]
    assert (await r.svc.collect(UID)).status == "no_session"
    assert (await r.state.get(UID)).session_id is None


async def test_purge_removes_the_session_and_every_cluster_id() -> None:
    r = await _with_cluster()
    await r.svc.begin(UID)
    await r.svc.purge(UID)
    data = await r.state.get(UID)
    assert data.session_id is None and data.clusters == () and r.picker.deleted
    assert not any("photos" in k for k in r.f.docs._data)  # noqa: SLF001


async def test_no_assert_guards_remain_in_the_service() -> None:
    import inspect

    import jarvis.photos.service as svc_mod

    assert "assert " not in inspect.getsource(svc_mod)
