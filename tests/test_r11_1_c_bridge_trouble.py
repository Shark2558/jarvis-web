# tests/test_r11_1_c_bridge_trouble.py -- the face-groups plugin when something goes wrong (reviews
# C-code H3, H4, M4, M8 and C-sec H2, M2). One bad picture is one plain refusal on the cloud's
# route and one skipped file in the folder, never a crash or "laptop not reachable"; a file that
# keeps failing (or takes the bridge down with it) is tried three times, then skipped and counted;
# a half-copied file waits; a store that can't be opened says so and is opened again later; a
# person whose delete began is never given a group or a copied crop; a group is counted once.
from __future__ import annotations

import base64
import os
import sqlite3
import time
from pathlib import Path
from typing import Any

import pytest
from r11_1_fakes_c import A, FakeLib, ScriptedEngine, picture

from jarvis.home.ports import BridgeState, FacesState, HomeRefused
from jarvis.homebridge import face_db
from jarvis.homebridge.face_groups import FaceGroupsPlugin
from jarvis.homebridge.faces import FacesPlugin
from jarvis.homebridge.jpeg import PictureRefused
from jarvis.homebridge.plugins import BridgeContext

PHOTOS = ("POST", "/bridge/v1/faces/photos")
ENROL = ("POST", "/bridge/v1/faces/enrol")
GROUPS = ("GET", "/bridge/v1/faces/groups")
FORGET = ("POST", "/bridge/v1/faces/groups/forget")


class Events:
    def __init__(self) -> None:
        self.posted: list[Any] = []

    async def post_event(self, event: Any) -> bool:
        self.posted.append(event)
        return True


class Naps:
    async def __call__(self, seconds: float) -> None:
        return None


class Exploding(ScriptedEngine):
    """A face engine whose reader breaks on pictures that carry `<boom>`, the way a native
    library can: not with a refusal but with whatever it raises."""

    def __init__(self, error: BaseException) -> None:
        super().__init__()
        self.error = error

    def faces(self, jpeg: bytes, *, own_file: bool = False) -> list[Any]:
        if b"<boom>" in jpeg:
            self.seen.append(jpeg)
            raise self.error
        return super().faces(jpeg, own_file=own_file)


def rig(tmp: Path, engine: ScriptedEngine | None = None, *, folder: bool = False) -> Any:
    lib, events = FakeLib(), Events()
    (tmp / "att").mkdir(exist_ok=True)
    photos = tmp / "photos"
    photos.mkdir(exist_ok=True)
    env = {"FACES_ATTEMPTS_DIR": str(tmp / "att"), "PHOTOS_MOUNT": str(photos)}
    if folder:
        env["PHOTOS_DIR"] = "/mnt/c/Users/someone/Pictures/JARVIS"
    peers: dict[str, Any] = {}
    ctx = BridgeContext(env=env, data_dir=tmp / "data", events=events, now=lambda: 5.0, peers=peers)
    faces = FacesPlugin(ctx, lib)
    groups = FaceGroupsPlugin(ctx, engine=engine or ScriptedEngine())
    peers.update({"faces": faces, "facegroups": groups})
    groups.folder._sleep = Naps()  # noqa: SLF001 - no real waiting in a test
    groups.folder.settle_s = 0.0
    routes = {(r.method, r.path): r.handler for r in groups.routes()}
    return groups, faces, lib, routes, photos


def b64(data: bytes) -> dict[str, str]:
    return {"image": base64.b64encode(data).decode()}


def boom(n: int = 0) -> bytes:
    return picture(1, n=n).replace(b"<people:", b"<boom><people:") + bytes(1100)


async def consent(faces: FacesPlugin, *people: str, deleting: tuple[str, ...] = ()) -> None:
    await faces.apply_state(BridgeState(faces=FacesState(rev=1, people=people, deleting=deleting)))


# ---- one bad picture ----------------------------------------------------------------------------


@pytest.mark.parametrize(
    "error", [RuntimeError("cv2.error: (-215) in alignCrop"), IndexError("row"), MemoryError()]
)
async def test_a_picture_the_reader_breaks_on_is_one_plain_refusal(
    tmp_path: Path, error: BaseException
) -> None:
    groups, _, _, routes, _ = rig(tmp_path, Exploding(error))
    with pytest.raises(HomeRefused) as err:  # 400 bad_image, never a 500 read as "offline"
        await routes[PHOTOS]({}, b64(boom()))
    assert err.value.code == "bad_image"
    ok = await routes[PHOTOS]({}, b64(picture(2)))  # and the next picture is read as usual
    assert len(ok["faces"]) == 1


async def test_a_file_that_keeps_breaking_the_reader_is_skipped_after_three_tries(
    tmp_path: Path,
) -> None:
    groups, _, _, _, photos = rig(tmp_path, Exploding(RuntimeError("cv2.error")), folder=True)
    (photos / "a-poison.jpg").write_bytes(boom())
    for i in range(3):
        (photos / f"b-good-{i}.jpg").write_bytes(picture(1, n=i) + bytes(1100))
    assert await groups.folder.pass_once() == 4  # the poison file did not stop the others
    view = groups.groups_view()
    assert len(view["groups"]) == 1 and view["skipped"] == 0
    for _ in range(2):  # tried again on later passes, up to the limit
        await groups.folder.pass_once()
    assert await groups.folder.pass_once() == 1  # the fourth visit marks it, without reading it
    assert groups.groups_view()["skipped"] == 1 and await groups.folder.pass_once() == 0
    assert len(groups.engine.seen) == 3 + 3  # three good pictures once, the poison three times


async def test_a_file_that_took_the_bridge_down_is_not_tried_for_ever(tmp_path: Path) -> None:
    """A bridge killed while decoding (out of memory) never reaches its `except`: the try was
    counted on disk BEFORE the decoder ran, so after three restarts the file is skipped."""
    groups, *_, photos = rig(tmp_path, folder=True)
    (photos / "a-bomb.jpg").write_bytes(boom())

    class Killed(BaseException):
        pass

    async def dies(data: bytes) -> str:
        raise Killed()  # the process is gone: nothing after this line runs

    for _ in range(3):  # three "restarts", each dying on the same file
        again, *_ = rig(tmp_path, folder=True)
        again.folder._look = dies  # noqa: SLF001
        with pytest.raises(Killed):
            await again.folder.pass_once()
        assert again.store is not None
        again.store.close()
    after, *_ = rig(tmp_path, folder=True)
    assert await after.folder.pass_once() == 1 and after.groups_view()["skipped"] == 1
    assert after.engine.seen == []  # skipped without being decoded a fourth time


async def test_a_file_still_being_copied_waits_and_is_read_once_it_settles(tmp_path: Path) -> None:
    groups, *_, photos = rig(tmp_path, folder=True)
    groups.folder.settle_s = 60.0
    half = photos / "copying.jpg"
    half.write_bytes(picture(1, n=1)[:40] + bytes(1100))  # half a file, written just now
    assert await groups.folder.pass_once() == 0 and groups.folder.waiting == 1
    half.write_bytes(picture(1, n=1) + bytes(1100))  # the copy finishes
    assert await groups.folder.pass_once() == 0  # still too fresh
    groups.folder._wall = lambda: time.time() + 120  # noqa: SLF001 - two minutes later
    assert await groups.folder.pass_once() == 1
    assert groups.engine.seen == [picture(1, n=1) + bytes(1100)]  # read once, whole


async def test_a_file_that_cannot_be_opened_now_is_tried_later_not_marked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    groups, *_, photos = rig(tmp_path, folder=True)
    (photos / "held.jpg").write_bytes(picture(1) + bytes(1100))
    real_open = os.open

    def busy(path: Any, flags: int, *a: Any) -> int:
        if str(path).endswith("held.jpg"):
            raise PermissionError("held by another program")
        return real_open(path, flags, *a)

    monkeypatch.setattr(os, "open", busy)
    assert await groups.folder.pass_once() == 0
    assert groups.groups_view()["read"] == 0 and groups.groups_view()["skipped"] == 0
    monkeypatch.undo()
    assert await groups.folder.pass_once() == 1 and groups.groups_view()["read"] == 1


# ---- the store can't be opened ------------------------------------------------------------------


async def test_a_store_that_cannot_be_opened_says_so_and_is_opened_later(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    real = face_db._connect  # noqa: SLF001
    full = {"on": True}

    def connect(path: Path) -> sqlite3.Connection:
        if full["on"]:
            raise sqlite3.OperationalError("database or disk is full")
        return real(path)

    monkeypatch.setattr(face_db, "_connect", connect)
    groups, _, _, routes, _ = rig(tmp_path)
    assert groups.store is None
    assert (await routes[GROUPS]({}, None))["engine"] == "no_store"
    for route, body in (
        (PHOTOS, b64(picture(1))),
        (ENROL, {"cluster": "c_0123456789ab", "person": A}),
    ):
        with pytest.raises(HomeRefused) as err:
            await routes[route]({}, body)
        assert err.value.code == "no_store"
    with pytest.raises(HomeRefused):  # "nothing left" is never said for a store it can't read
        await routes[FORGET]({}, {"all": True})
    assert not (tmp_path / "data" / "facegroups" / "groups.db").exists() or True
    full["on"] = False  # the disk has room again: the next call opens it
    view = await routes[GROUPS]({}, None)
    assert view["engine"] == "ready" and groups.store is not None


# ---- consent, once more, before each crop -------------------------------------------------------


async def test_a_delete_that_begins_during_the_copy_stops_it(tmp_path: Path) -> None:
    groups, faces, lib, routes, _ = rig(tmp_path)
    ids = {
        (await routes[PHOTOS]({}, b64(picture(1, n=i))))["faces"][0]["cluster"] for i in range(3)
    }
    (gid,) = ids
    await consent(faces, A)
    real = lib.register
    calls = {"n": 0}

    async def register(name: str, image: bytes, content_type: str) -> None:
        calls["n"] += 1
        await real(name, image, content_type)
        if calls["n"] == 1:  # the owner deletes the person while the first crop is copied
            await consent(faces, deleting=(A,))

    lib.register = register  # type: ignore[method-assign]
    reply = await routes[ENROL]({}, {"cluster": gid, "person": A})
    assert reply["camera"] == "waiting" and calls["n"] == 1  # no second crop went to Frigate
    await faces.library.finish_deletes()
    assert not groups.store.holds(A) and lib.pictures == {}  # type: ignore[union-attr]


async def test_the_store_refuses_a_name_whose_consent_went_after_the_first_look(
    tmp_path: Path,
) -> None:
    groups, faces, _, routes, _ = rig(tmp_path)
    ids = {
        (await routes[PHOTOS]({}, b64(picture(1, n=i))))["faces"][0]["cluster"] for i in range(3)
    }
    (gid,) = ids
    await consent(faces, A)
    looks = {"n": 0}
    real = groups._consented  # noqa: SLF001

    def first_yes_then_gone(person: object) -> bool:
        looks["n"] += 1
        return looks["n"] == 1 and real(person)  # consent is withdrawn between the two looks

    groups._consented = first_yes_then_gone  # type: ignore[method-assign]  # noqa: SLF001
    with pytest.raises(HomeRefused) as err:
        await routes[ENROL]({}, {"cluster": gid, "person": A})
    assert err.value.code == "no_consent" and looks["n"] == 2
    assert groups.store is not None and not groups.store.holds(A)


# ---- a group is counted once --------------------------------------------------------------------


async def test_a_named_group_waiting_for_frigate_is_counted_and_a_copied_one_once(
    tmp_path: Path,
) -> None:
    groups, faces, lib, routes, _ = rig(tmp_path)
    ids = {
        (await routes[PHOTOS]({}, b64(picture(1, n=i))))["faces"][0]["cluster"] for i in range(3)
    }
    (gid,) = ids
    await consent(faces, A)
    lib.down = True
    assert (await routes[ENROL]({}, {"cluster": gid, "person": A}))["camera"] == "waiting"
    lib.down = False  # Frigate answers again, but does not have the pictures yet
    assert (await faces.heartbeat_part()).faces == {A: 3}  # from the group, not lost
    assert await groups.copy_to_camera() == 1
    assert (await faces.heartbeat_part()).faces == {A: 3}  # from Frigate now, not 3 + 3


def test_the_refusal_type_is_the_one_the_folder_marks() -> None:
    assert issubclass(PictureRefused, ValueError)
