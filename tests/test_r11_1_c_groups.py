# tests/test_r11_1_c_groups.py -- R11.1 O7 end to end on fakes (plan D15, D21-C): the cloud's
# face-groups service over the REAL signed channel and the REAL bridge plugins (a scripted face
# engine stands in for the two models). Naming a group runs the consent check once per person; a
# guardian's yes for a child; without a yes nothing is enrolled and the bridge is never told;
# afterwards a new photo AND the camera recognise that person with no further step; a group is
# forgotten only when the laptop confirms it; new groups are announced once, as a count.
from __future__ import annotations

from pathlib import Path

import pytest
from home_fakes import ROOT, UID
from r11_1_fakes_c import Cloud, build_cloud, consent, picture

from jarvis.facegroups.service import FaceGroupsService
from jarvis.facegroups.store import GroupsStore
from jarvis.faces.directory import Directory
from jarvis.faces.service import PersonRejected
from jarvis.faces.store import FacesStore
from jarvis.keyring import Keyring

ENROL = ("POST", "/bridge/v1/faces/enrol")
STATE = ("POST", "/bridge/v1/state")


async def people(c: Cloud) -> tuple:
    return (await c.home.faces.state(UID)).people


async def test_the_laptops_groups_reach_the_console_as_ids_and_counts(tmp_path: Path) -> None:
    c = await build_cloud(tmp_path)
    gid = await c.group_of(1)
    await c.at_home(2)  # one picture only: a stray, not a group
    view = await c.groups.view(UID)
    assert view.available and view.laptop == "online" and view.heard_at
    (g,) = view.groups
    assert (g.id, g.n, g.photos) == (gid, 1, 3)
    assert (view.strays, view.named, view.engine_ready, view.keep_days) == (1, 0, True, 90)
    await c.home.aclose()


async def test_naming_runs_the_consent_check_and_then_everything_recognises_them(
    tmp_path: Path,
) -> None:
    c = await build_cloud(tmp_path)
    gid = await c.group_of(1)
    done = await c.groups.name(UID, gid, **consent())
    (person,) = await people(c)
    assert done.at_home and done.person.id == person.id and person.name == "Anjali"
    assert person.state == "enrolled"  # at once: the laptop confirmed how many pictures it holds
    assert c.home.down.calls.count(ENROL) == 1
    # a NEW photo of that person, picked in Google Photos, is recognised with no further step
    res = await c.import_all([picture(1, n=7), picture(2, n=7)])
    assert res.status == "done" and [p.name for p in res.recognised] == ["Anjali"]
    assert res.faces_found == 2 and res.unknown == 1
    # and so is a camera sighting: Frigate's library has their crops under the id, the bridge's
    # consent filter passes that id, and the cloud's directory turns it into the name
    assert len(c.home.lib.pictures[person.id]) == 3
    match = c.home.faces_plugin.library.match(person.id, 0.95, "person")
    assert match is not None
    directory = Directory(FacesStore(c.home.docs, Keyring(ROOT)))
    assert (await directory.resolve(UID, match.person, match.score)).name == "Anjali"
    assert (await c.groups.view(UID)).groups == ()  # no longer "to name"
    assert [e["tool"] for e in c.home.audit.entries] == ["faces_group_name"]
    assert c.home.audit.entries[0]["args"] == {"count": 1}  # a count, never a name
    await c.home.aclose()


async def test_without_a_yes_nothing_is_enrolled_and_the_bridge_is_never_told(
    tmp_path: Path,
) -> None:
    c = await build_cloud(tmp_path)
    gid = await c.group_of(1)
    before = list(c.home.down.calls)
    for bad in (consent(confirm=False), consent(confirm="yes"), consent(consent_version="old")):
        with pytest.raises(PersonRejected) as err:
            await c.groups.name(UID, gid, **bad)
        assert err.value.code == "consent_missing"
    assert await people(c) == ()
    told = c.home.down.calls[len(before) :]
    assert ENROL not in told and STATE not in told  # not the name, not even a consent list
    assert (await c.home.groups.look(picture(1, n=9)))[1][0].person is None
    assert c.home.lib.pictures == {} and c.home.audit.entries == []
    await c.home.aclose()


async def test_a_child_needs_a_guardians_yes(tmp_path: Path) -> None:
    c = await build_cloud(tmp_path)
    gid = await c.group_of(1)
    with pytest.raises(PersonRejected) as err:
        await c.groups.name(UID, gid, **consent(name="Mini", child=True, given_by="self"))
    assert err.value.code == "child_needs_guardian"
    assert await people(c) == () and ENROL not in c.home.down.calls
    done = await c.groups.name(
        UID, gid, **consent(name="Mini", child=True, given_by="parent_guardian")
    )
    assert done.at_home and done.person.child is True and done.contact_matched is False
    res = await c.import_all([picture(1, n=8)])
    (seen,) = res.recognised
    assert seen.child is True  # the routes and tools then say "a child from your family"
    await c.home.aclose()


async def test_the_consent_check_runs_once_per_person_not_once_per_group(tmp_path: Path) -> None:
    c = await build_cloud(tmp_path)
    first = await c.group_of(1)
    second = await c.group_of(40, start=10)  # the same person from another angle: a second group
    assert first != second
    named = await c.groups.name(UID, first, **consent())
    (person,) = await people(c)
    again = await c.groups.name_existing(UID, second, named.person.id)
    assert again.at_home and again.person.id == named.person.id
    (still,) = await people(c)
    assert still.consent_at == person.consent_at  # one person, one consent, asked once
    assert c.home.groups.person_pictures() == {named.person.id: 6}
    with pytest.raises(PersonRejected):  # a made-up person id is nobody's consent
        await c.groups.name_existing(UID, second, "fp_ffffffffffff")
    await c.home.aclose()


async def test_a_group_the_laptop_never_listed_cannot_be_named(tmp_path: Path) -> None:
    c = await build_cloud(tmp_path)
    await c.group_of(1)
    for bad in ("c_0123456789ab", "nope", "../x", ""):
        with pytest.raises(PersonRejected) as err:
            await c.groups.name(UID, bad, **consent())
        assert err.value.code == "unknown_face"
    assert await people(c) == ()
    await c.home.aclose()


async def test_named_while_the_laptop_sleeps_is_finished_by_the_poll(tmp_path: Path) -> None:
    c = await build_cloud(tmp_path)
    gid = await c.group_of(1)
    c.home.online = False
    done = await c.groups.name(UID, gid, **consent())
    assert done.at_home is False and len(await people(c)) == 1
    view = await c.groups.view(UID)
    assert view.laptop == "offline" and view.names_waiting == 1
    assert (await c.groups.poll(UID))["away"] == 1  # known to be asleep: not even called
    c.home.online = True
    assert (await c.groups.poll(UID))["named"] == 1
    assert (await people(c))[0].state == "enrolled"
    assert (await c.groups.view(UID)).names_waiting == 0
    await c.home.aclose()


async def test_forget_is_done_only_when_the_laptop_confirms_it(tmp_path: Path) -> None:
    c = await build_cloud(tmp_path)
    one = await c.group_of(1)
    two = await c.group_of(2, start=10)
    done = await c.groups.forget(UID, one)
    assert (done.done, done.forgotten, done.left) == (True, 1, 1)
    assert [g.id for g in (await c.groups.view(UID)).groups] == [two]
    c.home.online = False
    waiting = await c.groups.forget(UID, two)
    assert waiting.done is False and waiting.forgotten == 0
    view = await c.groups.view(UID)
    assert view.groups == () and view.forgets_waiting == 1  # hidden here, NOT yet gone there
    assert c.home.groups.groups_view()["groups"][0]["id"] == two
    c.home.online = True
    assert (await c.groups.poll(UID))["forgotten"] == 1
    assert c.home.groups.groups_view()["groups"] == []
    assert (await c.groups.view(UID)).forgets_waiting == 0
    tools = [e["tool"] for e in c.home.audit.entries]
    assert tools == ["faces_group_forget", "faces_group_forget"]  # each when it really happened
    await c.home.aclose()


async def test_new_groups_are_announced_once_as_a_count(tmp_path: Path) -> None:
    c = await build_cloud(tmp_path)
    await c.group_of(1)
    await c.group_of(2, start=10)
    assert (await c.groups.poll(UID))["told"] == 2
    ((uid, signal, text),) = c.home.notes.sent
    assert uid == UID and signal.kind == "faces_to_name" and signal.source == "home"
    assert text == "2 new groups of faces to name, Sir. Open Faces -> Unnamed groups."
    assert (await c.groups.poll(UID))["told"] == 0 and len(c.home.notes.sent) == 1
    await c.group_of(3, start=20)
    assert (await c.groups.poll(UID))["told"] == 1
    assert c.home.notes.sent[-1][2].startswith("1 new group of faces to name")
    # a second clock ticking at the same moment claims nothing: told once
    other = FaceGroupsService(
        lambda: c.photos, GroupsStore(c.home.docs), notifier=lambda: c.home.notes
    )
    assert (await other.poll(UID))["told"] == 0 and len(c.home.notes.sent) == 2
    await c.home.aclose()


async def test_a_sleeping_laptop_shows_what_it_last_said(tmp_path: Path) -> None:
    c = await build_cloud(tmp_path)
    gid = await c.group_of(1)
    heard = (await c.groups.view(UID)).heard_at
    c.home.online = False
    view = await c.groups.view(UID)
    assert view.laptop == "offline" and [g.id for g in view.groups] == [gid]
    assert view.heard_at == heard
    await c.home.aclose()


async def test_photos_off_on_this_server_is_said_plainly(tmp_path: Path) -> None:
    c = await build_cloud(tmp_path)
    off = FaceGroupsService(lambda: None, GroupsStore(c.home.docs))
    view = await off.view(UID)
    assert view.available is False and "home kit" in view.reason and view.laptop == "off"
    with pytest.raises(PersonRejected) as err:
        await off.name(UID, "c_0123456789ab", **consent())
    assert err.value.status == 503
    assert (await off.poll(UID))["away"] == 1
    await c.home.aclose()


async def test_a_name_given_while_the_laptop_slept_survives_a_forget_all(tmp_path: Path) -> None:
    c = await build_cloud(tmp_path)
    gid = await c.group_of(1)
    other = await c.group_of(2, start=10)
    c.home.online = False
    await c.groups.name(UID, gid, **consent())
    view = await c.groups.view(UID)
    assert [g.id for g in view.groups] == [other]  # named: no longer "to name", though it waits
    assert view.names_waiting == 1
    assert (await c.groups.forget_all(UID)).done is False
    view = await c.groups.view(UID)
    assert view.groups == () and (view.names_waiting, view.forgets_waiting) == (1, 1)
    c.home.online = True
    out = await c.groups.poll(UID)  # the name reaches the laptop BEFORE the forget
    assert (out["named"], out["forgotten"], out["away"]) == (1, 1, 0)
    (person,) = await people(c)
    assert person.state == "enrolled" and c.home.groups.person_pictures() == {person.id: 3}
    assert c.home.groups.groups_view()["groups"] == []
    await c.home.aclose()


async def test_forget_all_first_tells_the_laptop_the_names_that_wait(tmp_path: Path) -> None:
    """The laptop woke up, the 5-minute poll has not run yet, and the owner forgets the rest."""
    c = await build_cloud(tmp_path)
    gid = await c.group_of(1)
    await c.group_of(2, start=10)
    c.home.online = False
    await c.groups.name(UID, gid, **consent())
    c.home.online = True
    done = await c.groups.forget_all(UID)
    assert (done.done, done.forgotten, done.left) == (True, 1, 0)
    (person,) = await people(c)
    assert person.state == "enrolled" and c.home.groups.person_pictures() == {person.id: 3}
    await c.home.aclose()


async def test_a_group_whose_name_waits_is_not_an_unnamed_group_to_forget(tmp_path: Path) -> None:
    c = await build_cloud(tmp_path)
    gid = await c.group_of(1)
    c.home.online = False
    await c.groups.name(UID, gid, **consent())
    with pytest.raises(PersonRejected) as err:
        await c.groups.forget(UID, gid)
    assert err.value.code == "unknown_face"
    c.home.online = True
    assert (await c.groups.poll(UID))["named"] == 1  # the name still arrives
    await c.home.aclose()
