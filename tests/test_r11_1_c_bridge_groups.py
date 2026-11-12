# tests/test_r11_1_c_bridge_groups.py -- R11.1 O7 (plan D15, D21-C): the bridge's face-groups
# plugin. Its four routes answer ids and counts only; an unknown face seen in 3 pictures becomes a
# group; a group is named only for a person the cloud synced as consented; afterwards a new photo
# AND the camera recognise that person with no further step; unnamed groups expire, can be
# forgotten, and a deleted person's groups go before the delete is acknowledged.
from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import Any

import pytest
from r11_1_fakes_c import A, B, FakeLib, ScriptedEngine, leaks, picture

from jarvis.home.ports import BRIDGE_ROUTES, BridgeState, FacesState, HomeRefused
from jarvis.homebridge.face_groups import (
    DEFAULT_KEEP_DAYS,
    FaceGroupsPlugin,
    confidence,
    create_plugin,
)
from jarvis.homebridge.faces import FacesPlugin
from jarvis.homebridge.plugins import PLUGIN_ENV_KEYS, BridgeContext, check_routes

PHOTOS = ("POST", "/bridge/v1/faces/photos")
ENROL = ("POST", "/bridge/v1/faces/enrol")
GROUPS = ("GET", "/bridge/v1/faces/groups")
FORGET = ("POST", "/bridge/v1/faces/groups/forget")
DAY = 86_400.0


class Events:
    def __init__(self) -> None:
        self.posted: list[Any] = []

    async def post_event(self, event: Any) -> bool:
        self.posted.append(event)
        return True


class Rig:
    def __init__(self, tmp: Path, **env: str) -> None:
        self.t = 1_800_000_000.0
        self.lib, self.engine, self.events = FakeLib(), ScriptedEngine(), Events()
        (tmp / "att").mkdir(exist_ok=True)
        peers: dict[str, Any] = {}
        ctx = BridgeContext(
            env={"FACES_ATTEMPTS_DIR": str(tmp / "att"), **env},
            data_dir=tmp,
            events=self.events,
            now=lambda: self.t,
            peers=peers,
        )
        self.faces = FacesPlugin(ctx, self.lib)
        self.groups = FaceGroupsPlugin(ctx, engine=self.engine)
        peers.update({"faces": self.faces, "facegroups": self.groups})
        check_routes([self.faces, self.groups])
        self.routes = {(r.method, r.path): r.handler for r in self.groups.routes()}
        self.replies: list[dict[str, Any]] = []

    async def call(self, route: tuple[str, str], body: dict[str, Any] | None = None) -> Any:
        reply = await self.routes[route]({}, body)
        self.replies.append(reply)
        return reply

    async def send(self, *people: int, n: int = 0, needle: bool = False) -> list[dict[str, Any]]:
        image = base64.b64encode(picture(*people, n=n, needle=needle)).decode()
        return (await self.call(PHOTOS, {"image": image}))["faces"]

    async def consent(self, *people: str, deleting: tuple[str, ...] = (), rev: int = 1) -> None:
        state = BridgeState(faces=FacesState(rev=rev, people=people, deleting=deleting))
        await self.faces.apply_state(state)
        await self.groups.apply_state(state)

    async def seen(self, person: int, pictures: int = 3, *, start: int = 0) -> str:
        ids = {(await self.send(person, n=start + i))[0]["cluster"] for i in range(pictures)}
        assert len(ids) == 1
        return ids.pop()


def test_the_four_routes_are_on_the_bridges_fixed_list(tmp_path: Path) -> None:
    rig = Rig(tmp_path)
    assert set(rig.routes) == {PHOTOS, ENROL, GROUPS, FORGET}
    assert set(rig.routes) <= BRIDGE_ROUTES and len(BRIDGE_ROUTES) == 11
    assert {"PHOTOS_DIR", "FACE_GROUPS_KEEP_DAYS", "FACE_MODELS_DIR"} <= PLUGIN_ENV_KEYS
    assert DEFAULT_KEEP_DAYS == 90


async def test_a_photo_answers_ids_and_scores_only(tmp_path: Path) -> None:
    rig = Rig(tmp_path)
    faces = await rig.send(1, 2, needle=True)
    assert len(faces) == 2
    for face in faces:
        assert set(face) == {"cluster", "person", "score"}
        assert face["cluster"].startswith("c_") and len(face["cluster"]) == 14
        assert face["person"] is None and face["score"] == 0.0
    assert leaks(json.dumps(rig.replies)) == []  # no picture, no crop, no embedding in the answer
    assert rig.engine.own_files == [False]  # a picture from the cloud gets the strict caps


async def test_an_unknown_face_seen_in_three_pictures_becomes_a_group(tmp_path: Path) -> None:
    rig = Rig(tmp_path)
    gid = (await rig.send(1, n=0))[0]["cluster"]
    assert (await rig.send(1, n=1))[0]["cluster"] == gid
    listed = await rig.call(GROUPS)
    assert listed["groups"] == [] and listed["strays"] == 1
    assert (await rig.send(1, n=2))[0]["cluster"] == gid
    listed = await rig.call(GROUPS)
    (row,) = listed["groups"]
    assert row == {"id": gid, "n": 1, "photos": 3, "first": int(rig.t), "last": int(rig.t)}
    assert listed["strays"] == 0 and listed["named"] == 0 and listed["engine"] == "ready"
    assert listed["folder"] == "off" and listed["keep_days"] == 90
    assert leaks(json.dumps(rig.replies)) == []


async def test_the_same_photo_sent_twice_counts_once(tmp_path: Path) -> None:
    rig = Rig(tmp_path)
    first = await rig.send(1, n=0)
    again = await rig.send(1, n=0)
    assert again == first and len(rig.engine.seen) == 1  # answered from the record
    await rig.send(1, n=1)
    assert (await rig.call(GROUPS))["groups"] == []  # two pictures, not three


async def test_naming_needs_the_clouds_consent_for_that_person(tmp_path: Path) -> None:
    rig = Rig(tmp_path)
    gid = await rig.seen(1)
    with pytest.raises(HomeRefused) as err:
        await rig.call(ENROL, {"cluster": gid, "person": A})
    assert err.value.code == "no_consent"
    await rig.consent(B)  # consent for someone else is not consent for A
    with pytest.raises(HomeRefused):
        await rig.call(ENROL, {"cluster": gid, "person": A})
    assert rig.lib.pictures == {} and (await rig.call(GROUPS))["named"] == 0
    assert (await rig.send(1, n=9))[0]["person"] is None


async def test_once_named_a_new_photo_and_the_camera_recognise_them_with_no_further_step(
    tmp_path: Path,
) -> None:
    rig = Rig(tmp_path)
    gid = await rig.seen(1)
    await rig.consent(A)
    reply = await rig.call(ENROL, {"cluster": gid, "person": A})
    assert reply == {"pictures": 3, "camera": "copied"}
    # the group's crops are now in the camera's face library under the person's id ...
    assert list(rig.lib.pictures) == [A] and len(rig.lib.pictures[A]) == 3
    # ... so the camera's own recognition of that id passes the bridge's consent filter
    match = rig.faces.library.match(A, 0.95, "person")
    assert match is not None and match.person == A
    # and a NEW photo of that person is recognised by the laptop, at the contract's 0.9 or more
    (face,) = await rig.send(1, n=7)
    assert face["cluster"] == gid and face["person"] == A and face["score"] >= 0.9
    (other,) = await rig.send(2, n=7)
    assert other["person"] is None  # a stranger in the same folder stays a stranger
    listed = await rig.call(GROUPS)
    assert listed["groups"] == [] and listed["named"] == 1
    # review C-code M8: the group's crops are the camera's 3 pictures: counted once, by Frigate
    assert rig.groups.store.pictures_of(A) == 4 and rig.groups.store.person_pictures() == {}
    assert (await rig.faces.heartbeat_part()).faces == {A: 3}
    assert leaks(json.dumps(rig.replies)) == []


async def test_a_named_group_whose_person_lost_consent_names_nobody(tmp_path: Path) -> None:
    rig = Rig(tmp_path)
    gid = await rig.seen(1)
    await rig.consent(A)
    await rig.call(ENROL, {"cluster": gid, "person": A})
    rig.faces.library.people = frozenset()  # e.g. the synced state could not be read
    (face,) = await rig.send(1, n=8)
    assert face["person"] is None and face["cluster"] == gid


async def test_the_camera_copy_waits_for_frigate_and_is_done_later(tmp_path: Path) -> None:
    rig = Rig(tmp_path)
    gid = await rig.seen(1)
    await rig.consent(A)
    rig.lib.down = True
    reply = await rig.call(ENROL, {"cluster": gid, "person": A})
    assert reply == {"pictures": 3, "camera": "waiting"} and rig.lib.pictures == {}
    (face,) = await rig.send(1, n=5)
    assert face["person"] == A  # photos are recognised by the laptop even while Frigate is down
    assert (await rig.faces.heartbeat_part()).faces == {A: 4}
    rig.lib.down = False
    assert await rig.groups.copy_to_camera() == 1
    assert len(rig.lib.pictures[A]) == 4 and await rig.groups.copy_to_camera() == 0


@pytest.mark.parametrize(
    ("body", "code"),
    [
        ({"cluster": "c_0123456789ab", "person": A}, "unknown_group"),
        ({"cluster": "../etc", "person": A}, "unknown_group"),
        ({"cluster": None, "person": A}, "unknown_group"),
        ({"person": A}, "unknown_group"),
    ],
)
async def test_enrol_refuses_what_it_does_not_know(
    tmp_path: Path, body: dict[str, Any], code: str
) -> None:
    rig = Rig(tmp_path)
    await rig.consent(A)
    with pytest.raises(HomeRefused) as err:
        await rig.call(ENROL, body)
    assert err.value.code == code


async def test_a_group_carries_one_person_only(tmp_path: Path) -> None:
    rig = Rig(tmp_path)
    gid = await rig.seen(1)
    await rig.consent(A, B)
    await rig.call(ENROL, {"cluster": gid, "person": A})
    assert (await rig.call(ENROL, {"cluster": gid, "person": A}))["pictures"] == 3  # again: fine
    with pytest.raises(HomeRefused) as err:
        await rig.call(ENROL, {"cluster": gid, "person": B})
    assert err.value.code == "already_named"
    with pytest.raises(HomeRefused) as err:
        await rig.call(ENROL, {"cluster": gid, "person": "Anjali"})
    assert err.value.code == "no_consent"  # a name is never an id


@pytest.mark.parametrize(
    "body",
    [
        None,
        {},
        {"image": 7},
        {"image": "not base64 !!"},
        {"image": base64.b64encode(b"GIF89a" + bytes(20)).decode()},
        {"image": base64.b64encode(picture(1)).decode(), "also": "x"},
    ],
)
async def test_a_bad_photo_request_is_refused_with_a_short_code(
    tmp_path: Path, body: dict[str, Any] | None
) -> None:
    rig = Rig(tmp_path)
    with pytest.raises(HomeRefused) as err:
        await rig.call(PHOTOS, body)
    assert err.value.code in {"bad_request", "bad_image"}
    assert rig.engine.seen == []  # nothing reached the engine


async def test_an_engine_that_cannot_run_says_so_and_stores_nothing(tmp_path: Path) -> None:
    rig = Rig(tmp_path)
    rig.engine.ready = "the face model files are not on this laptop yet"
    with pytest.raises(HomeRefused) as err:
        await rig.send(1)
    assert err.value.code == "no_engine"
    listed = await rig.call(GROUPS)
    assert listed["engine"] == "off" and listed["groups"] == []


async def test_forget_this_group_and_forget_all_report_what_is_left(tmp_path: Path) -> None:
    rig = Rig(tmp_path)
    one, two, named = await rig.seen(1), await rig.seen(2), await rig.seen(3)
    await rig.send(4)  # a stray
    await rig.consent(A)
    await rig.call(ENROL, {"cluster": named, "person": A})
    assert await rig.call(FORGET, {"groups": [one, "c_ffffffffffff"]}) == {
        "forgotten": 1,
        "left": 2,
    }
    assert [g["id"] for g in (await rig.call(GROUPS))["groups"]] == [two]
    assert await rig.call(FORGET, {"all": True}) == {"forgotten": 2, "left": 0}
    listed = await rig.call(GROUPS)
    assert listed["groups"] == [] and listed["strays"] == 0 and listed["named"] == 1
    for bad in (
        None,
        {},
        {"groups": "c_0123456789ab"},
        {"all": "yes"},
        {"groups": [], "all": True},
    ):
        with pytest.raises(HomeRefused):
            await rig.call(FORGET, bad)


async def test_unnamed_groups_expire_after_the_kept_days_and_named_ones_stay(
    tmp_path: Path,
) -> None:
    rig = Rig(tmp_path, FACE_GROUPS_KEEP_DAYS="30")
    unnamed, named = await rig.seen(1), await rig.seen(2)
    await rig.send(3)
    await rig.consent(A)
    await rig.call(ENROL, {"cluster": named, "person": A})
    assert (await rig.call(GROUPS))["keep_days"] == 30
    rig.t += 29 * DAY
    assert await rig.groups.expire() == 0
    rig.t += 2 * DAY
    assert await rig.groups.expire() == 2
    listed = await rig.call(GROUPS)
    assert listed["groups"] == [] and listed["strays"] == 0 and listed["named"] == 1
    assert unnamed not in json.dumps(listed)


@pytest.mark.parametrize("bad", ["", "abc", "0", "-5", "99999", "1e3"])
async def test_a_bad_keep_days_setting_falls_back_to_ninety(tmp_path: Path, bad: str) -> None:
    rig = Rig(tmp_path, FACE_GROUPS_KEEP_DAYS=bad)
    assert (await rig.call(GROUPS))["keep_days"] == 90


async def test_deleting_a_person_removes_their_groups_before_the_ack(tmp_path: Path) -> None:
    rig = Rig(tmp_path)
    gid = await rig.seen(1)
    await rig.consent(A)
    await rig.call(ENROL, {"cluster": gid, "person": A})
    assert rig.groups.store.pictures_of(A) == 3
    await rig.consent(deleting=(A,), rev=2)
    assert not rig.groups.store.holds(A) and rig.lib.pictures == {}
    assert [e.person for e in rig.events.posted] == [A]  # acked only after everything went
    (face,) = await rig.send(1, n=9)
    assert face["person"] is None and face["cluster"] != gid  # the embeddings are gone too


async def test_a_delete_is_not_acked_while_the_groups_cannot_be_removed(tmp_path: Path) -> None:
    rig = Rig(tmp_path)
    gid = await rig.seen(1)
    await rig.consent(A)
    await rig.call(ENROL, {"cluster": gid, "person": A})

    async def broken(person: str) -> bool:
        raise OSError("disk")

    rig.groups.forget_person = broken  # type: ignore[method-assign]
    await rig.consent(deleting=(A,), rev=2)
    assert (
        rig.events.posted == [] and A in rig.faces.library.deleting
    )  # retried later, never "done"


def test_the_score_meets_the_clouds_bar_exactly_at_the_laptops_threshold() -> None:
    assert confidence(0.42, 0.42) == 0.9
    assert confidence(1.0, 0.42) == 1.0 and 0.9 < confidence(0.7, 0.42) < 1.0
    assert confidence(0.41, 0.42) < 0.9 and confidence(0.0, 0.42) == 0.0
    assert confidence(-0.3, 0.42) == 0.0 and confidence(2.0, 0.42) == 1.0


def test_the_registry_factory_builds_the_real_engine_lazily(tmp_path: Path) -> None:
    ctx = BridgeContext(env={"FACE_MODELS_DIR": str(tmp_path)}, data_dir=tmp_path, events=Events())
    plugin = create_plugin(ctx)
    assert plugin.name == "facegroups" and len(plugin.tasks()) >= 2
    assert plugin.groups_view()["engine"] == "off"  # no model files here: plain "off", no crash
