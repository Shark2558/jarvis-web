# tests/test_r8_b_spots.py -- R8 builder B, rows 217 and 184 (docs/plans/r8-vision.md v8.0.4
# sections 4.5, 6; D11, ADR-54): his cameras, spots and rooms and their off switches.
#   - a camera, a room switched off, a "never" room and "cameras off" each stop looking; a "never"
#     room can't be chosen for any coach; the bridge's coach state keeps only the home cameras
#     that may look (the alarm is never in it)
#   - the store is sealed under `vision`, changed whole with its rev (a stale change is refused),
#     tells I1's push of every change and keeps working when that push fails
#   - the routes: 501 before I1 wires them, 404 with no token key, the view with `allowed`, `why`
#     and `coach`; "cameras off" says whether the alarm is still armed and never arms or disarms
#   - the camera's door (console-camera.js, in R7's Node DOM): the server's switches stop a look
#     and refuse a start in plain words; "cameras off" by voice locks this device at once, sets
#     every camera off on the server and says the alarm is still armed when it is
from __future__ import annotations

import json
import re
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError
from r7_fakes_b import STATIC, run_dom

from jarvis.api.auth import require_auth
from jarvis.api.camera_spots import build_camera_setup, router
from jarvis.api.identity import current_user
from jarvis.camera.ports import CameraUnavailable
from jarvis.camera.spots import (
    ALL_OFF,
    Camera,
    Room,
    Spots,
    SpotsStore,
    StaleSpots,
    coach_allowed,
    home_uses,
    looking_allowed,
    view_of,
    why_off,
)
from jarvis.home.ports import ArmView
from jarvis.keyring import Keyring
from jarvis.storage.docs import MemoryDocs
from jarvis.voice.commands import CAMERAS_OFF_REPLY

KEY = bytes(range(41, 73))  # a made-up token key
UID = "u_0123456789abcdef"
DESK = Camera(id="desk_cam", kind="device", source="browser", label="Desk camera", spot="desk",
              room="study")  # fmt: skip
PHONE = Camera(id="tripod", kind="device", source="phone", label="Workout phone", spot="workout",
               room="living")  # fmt: skip
HOME = Camera(id="home_cam", kind="home", source="home", label="Home camera", spot="desk",
              room="study")  # fmt: skip
ROOMS = (Room(id="study", label="Study"), Room(id="living", label="Living room"),
         Room(id="bed", label="Bedroom", never=True))  # fmt: skip
SET = Spots(cameras=(DESK, PHONE, HOME), rooms=ROOMS)


def _with(spots: Spots, **over: Any) -> Spots:
    return spots.model_copy(update=over)


def _cam(spots: Spots, cid: str, **over: Any) -> Spots:
    cams = tuple(c.model_copy(update=over) if c.id == cid else c for c in spots.cameras)
    return _with(spots, cameras=cams)


def _room(spots: Spots, rid: str, **over: Any) -> Spots:
    rooms = tuple(r.model_copy(update=over) if r.id == rid else r for r in spots.rooms)
    return _with(spots, rooms=rooms)


# ---- the switches (rows 217, 184) ----------------------------------------------------------------
def test_every_camera_may_look_until_a_switch_says_otherwise() -> None:
    assert all(looking_allowed(SET, c.id) for c in SET.cameras)
    assert not looking_allowed(SET, "nobody") and why_off(SET, "nobody")


def test_a_camera_switched_off_stops_only_itself() -> None:
    off = _cam(SET, "desk_cam", on=False)
    assert not looking_allowed(off, "desk_cam") and looking_allowed(off, "tripod")
    assert why_off(off, "desk_cam").startswith("Desk camera is switched off.")


def test_a_room_switched_off_stops_every_camera_in_it() -> None:
    off = _room(SET, "study", on=False)
    assert not looking_allowed(off, "desk_cam") and not looking_allowed(off, "home_cam")
    assert looking_allowed(off, "tripod")
    assert why_off(off, "home_cam") == (
        "Study is switched off, so Home camera is too. Tap Allow in Camera, Cameras."
    )


def test_a_never_room_cannot_be_chosen_for_any_coach() -> None:
    moved = _cam(SET, "tripod", room="bed")
    assert not coach_allowed(moved, "tripod") and not looking_allowed(moved, "tripod")
    assert "marked never for cameras" in why_off(moved, "tripod")
    assert view_of(moved)["coach"]["tripod"] is False
    assert home_uses(_cam(moved, "home_cam", room="bed"), {"home_cam": ["posture"]}) == {}


def test_cameras_off_stops_every_camera_and_leaves_the_coaches_nothing() -> None:
    off = _with(SET, all_off=True)
    assert not any(looking_allowed(off, c.id) for c in off.cameras)
    assert why_off(off, "tripod") == ALL_OFF
    assert home_uses(off, {"home_cam": ["posture", "activity"]}) == {}


def test_the_bridge_hears_only_home_cameras_that_may_look() -> None:
    wanted = {"home_cam": ["posture"], "desk_cam": ["water"], "ghost": ["posture"]}
    assert home_uses(SET, wanted) == {"home_cam": ("posture",)}  # a device camera never goes
    assert home_uses(_cam(SET, "home_cam", on=False), wanted) == {}


def test_the_view_says_why_and_which_cameras_a_coach_may_use() -> None:
    v = view_of(_room(SET, "study", on=False))
    assert v["allowed"] == {"desk_cam": False, "tripod": True, "home_cam": False}
    assert set(v["why"]) == {"desk_cam", "home_cam"} and v["recheck_s"] == 60
    assert v["coach"] == {"desk_cam": False, "tripod": True, "home_cam": False}


@pytest.mark.parametrize(
    "bad",
    [
        {"cameras": [{"id": "x", "kind": "home", "source": "browser", "label": "x"}]},
        {"cameras": [{"id": "Bad Id", "kind": "device", "source": "phone", "label": "x"}]},
        {"cameras": [{"id": "x", "kind": "device", "source": "phone", "label": "<b>"}]},
        {"cameras": [{"id": "x", "kind": "device", "source": "phone", "label": "x", "room": "r"}]},
        {"rooms": [{"id": "r", "label": "R"}, {"id": "r", "label": "S"}]},
        {"cameras": [{"id": "x", "kind": "device", "source": "phone", "label": "x", "url": "/"}]},
    ],
)
def test_a_set_that_does_not_fit_is_refused(bad: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        Spots.model_validate(bad)


# ---- the store -----------------------------------------------------------------------------------
def _store(docs: MemoryDocs, **kw: Any) -> SpotsStore:
    return SpotsStore(docs, Keyring(KEY), prefix="t_", **kw)


async def test_the_set_is_sealed_and_changed_whole_with_its_rev() -> None:
    docs, told = MemoryDocs(), []

    async def push(uid: str, spots: Spots) -> None:
        told.append(spots.rev)

    store = _store(docs, on_change=push)
    saved = await store.put(UID, SET, base_rev=0)
    assert saved.rev == 1 and told == [1]
    raw = json.dumps(await docs.get(f"t_camera_spots/{UID}"))
    assert "Desk camera" not in raw and "study" not in raw and "blob" in raw  # sealed
    with pytest.raises(StaleSpots):
        await store.put(UID, _cam(SET, "desk_cam", on=False), base_rev=0)  # read before rev 1
    assert (await store.get(UID)).camera("desk_cam").on is True  # type: ignore[union-attr]
    again = await store.put(UID, _cam(SET, "desk_cam", on=False), base_rev=1)
    assert again.rev == 2 and not await store.looking_allowed(UID, "desk_cam")
    assert await store.put(UID, _cam(SET, "desk_cam", on=False), base_rev=2) == again  # no change
    assert told == [1, 2]


async def test_cameras_off_is_saved_once_and_pushed_even_if_the_push_fails() -> None:
    async def broken(uid: str, spots: Spots) -> None:
        raise RuntimeError("laptop asleep")

    store = _store(MemoryDocs(), on_change=broken)
    await store.put(UID, SET, base_rev=0)
    await store.all_off(UID, by="voice")
    got = await store.get(UID)
    assert got.all_off and got.rev == 2
    await store.all_off(UID, by="button")
    assert (await store.get(UID)).rev == 2  # already off: nothing written
    with pytest.raises(ValueError):
        await store.all_off(UID, by="a webpage")


async def test_a_set_that_wont_open_is_never_overwritten() -> None:
    docs = MemoryDocs()
    await _store(docs).put(UID, SET, base_rev=0)
    other = SpotsStore(docs, Keyring(bytes(range(1, 33))), prefix="t_")
    with pytest.raises(CameraUnavailable):
        await other.get(UID)
    with pytest.raises(CameraUnavailable):
        await other.all_off(UID, by="voice")
    assert (await _store(docs).get(UID)).all_off is False


async def test_the_home_kit_cameras_not_set_up_yet_are_offered() -> None:
    async def kit(uid: str) -> dict[str, str]:
        return {"home_cam": "Hall", "gate": "Gate camera"}

    store = _store(MemoryDocs(), home_cameras=kit)
    await store.put(UID, SET, base_rev=0)
    assert (await store.view(UID))["home"] == [{"id": "gate", "label": "Gate camera"}]


# ---- the routes ----------------------------------------------------------------------------------
class Arm:
    """A burglar alarm that records every call: "cameras off" may only read it."""

    def __init__(self, armed: bool) -> None:
        self.armed, self.calls = armed, []

    async def view(self, uid: str) -> ArmView:
        self.calls.append("view")
        return ArmView(armed=self.armed, mode="away", rev=3, confirmed=True)


def _client(wired: bool = True, keyed: bool = True, arm: Arm | None = None) -> TestClient:
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[require_auth] = lambda: None
    app.dependency_overrides[current_user] = lambda: UID
    if wired:
        app.state.camera_setup = build_camera_setup(
            MemoryDocs(), Keyring(KEY) if keyed else None, prefix="t_", arm=arm
        )
    return TestClient(app)


def _put(c: TestClient, spots: Spots, rev: int) -> Any:
    return c.put("/v1/camera/spots", json={**spots.model_dump(mode="json"), "rev": rev})


def test_before_the_join_501_and_without_a_key_404() -> None:
    assert _client(wired=False).get("/v1/camera/spots").status_code == 501
    off = _client(keyed=False).get("/v1/camera/spots")
    assert off.status_code == 404 and off.json()["error"] == "cameras_off"


def test_get_put_and_a_stale_put_answers_the_newest() -> None:
    c = _client()
    first = c.get("/v1/camera/spots")
    assert first.status_code == 200 and first.json()["cameras"] == []
    assert first.headers["cache-control"] == "no-store"
    r = _put(c, SET, 0)
    assert r.status_code == 200 and r.json()["rev"] == 1 and r.json()["allowed"]["desk_cam"]
    stale = _put(c, _cam(SET, "desk_cam", on=False), 0)
    assert stale.status_code == 409 and stale.json()["spots"]["rev"] == 1
    assert "another device" in stale.json()["detail"]
    for bad in ({"rev": -1}, {"rev": "1"}, {"cameras": []}, [1, 2]):
        r = c.put("/v1/camera/spots", json=bad)
        assert r.status_code == 422 and r.json()["detail"] == "That request isn't one JARVIS takes."


def test_cameras_off_says_the_alarm_is_still_armed_and_never_touches_it() -> None:
    arm = Arm(armed=True)
    c = _client(arm=arm)
    _put(c, SET, 0)
    r = c.post("/v1/camera/off", json={"by": "voice"})
    assert r.status_code == 200 and r.json() == {"all_off": True, "alarm_armed": True}
    assert arm.calls == ["view"]  # read, never armed or disarmed
    v = c.get("/v1/camera/spots").json()
    assert v["all_off"] is True and not any(v["allowed"].values())
    assert c.post("/v1/camera/off", json={"by": "a tool"}).status_code == 422
    assert _client().post("/v1/camera/off", json={}).json()["alarm_armed"] is None  # unwired


# ---- the reply words, the same in the console --------------------------------------------------
def _between(text: str, begin: str, end: str) -> str:
    return text[text.index(begin) + len(begin) : text.index(end)]


def test_the_cameras_off_words_are_the_servers_and_r7s_stay() -> None:
    js = (STATIC / "console-camera.js").read_text(encoding="utf-8")
    got = dict(
        re.findall(
            r"(\w+): '([^']*)'",
            _between(js, "/*CAMERAS-OFF-SAY-BEGIN*/", "/*CAMERAS-OFF-SAY-END*/"),
        )
    )
    assert got == CAMERAS_OFF_REPLY
    assert CAMERAS_OFF_REPLY["local"] == "The camera on this device is off, {h}."  # R7's words
    assert "Disarm" in CAMERAS_OFF_REPLY["armed"] and "disarmed" not in CAMERAS_OFF_REPLY["all"]
    assert (
        "jarvis_cam_spot_v1" in js and "'/v1/camera/off'" in js and "RECHECK_MS = 60 * 1000" in js
    )


# ---- the camera's door, in R7's Node DOM ---------------------------------------------------------
def _steps(out: dict[str, Any]) -> list[dict[str, Any]]:
    return list(out["steps"])


def test_the_servers_cameras_off_refuses_a_start_and_stops_the_look() -> None:
    answers = {"/v1/camera/spots": {"all_off": True, "allowed": {}, "rev": 4}}
    out = run_dom("camera", answers=answers, steps=[
        {"op": "start", "tap": True}, {"op": "start", "tap": True},
    ])  # fmt: skip
    first, second = _steps(out)
    assert first["ok"] is False and first["code"] == "switched_off"
    assert not first["live"] and first["liveTracks"] == 0 and not first["chip"]
    assert second["code"] == "switched_off" and second["asked"] == first["asked"]  # not asked again
    assert not second["locked"]  # the server's switch is not this device's own lock


def test_with_every_camera_allowed_a_start_goes_ahead() -> None:
    answers = {"/v1/camera/spots": {"all_off": False, "allowed": {"desk_cam": False}, "rev": 4}}
    out = run_dom("camera", answers=answers, steps=[{"op": "start", "tap": True}])
    assert _steps(out)[0]["ok"] is True and _steps(out)[0]["live"]  # this device is no spot


@pytest.mark.parametrize(
    ("answer", "said"),
    [
        ({}, "The camera on this device is off, Sir."),  # the server didn't confirm: R7's words
        ({"all_off": True, "alarm_armed": False},
         "Every camera is off, Sir: this device now, your other devices within a minute."),
        ({"all_off": True, "alarm_armed": True},
         "Every camera is off, Sir: this device now, your other devices within a minute. "
         "The burglar alarm is still armed and its camera keeps watching; Disarm is in Home."),
    ],
)  # fmt: skip
def test_cameras_off_by_voice_locks_here_and_switches_every_camera_off(
    answer: dict[str, Any], said: str
) -> None:
    out = run_dom("camera", answers={"/v1/camera/off": answer}, steps=[
        {"op": "start", "tap": True}, {"op": "voice", "text": "Jarvis, cameras off"},
    ])  # fmt: skip
    step = _steps(out)[1]
    assert step["ok"] is True and step["locked"] and not step["live"] and step["code"] == said
