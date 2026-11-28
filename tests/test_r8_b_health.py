# tests/test_r8_b_health.py -- R8 builder B, row 217 (docs/plans/r8-vision.md v8.0.4 sections 4.5,
# 4.8): each camera's health for Vitals.
#   - a live device's report (frames a second, a look's ms) is kept sealed under `vision`, only for
#     his registered device cameras, on the server's clock, at most every 30 s per camera
#   - Vitals shows each camera's last-seen time and frame rate; a switched-on camera unseen for a
#     day is amber; a switched-off camera says so; a home camera's line comes from the home kit
#   - the route takes three numbers and an id, nothing else; GET /v1/camera/spots carries health
#   - Privacy's row for the setup and the health: count, export (no picture), delete
from __future__ import annotations

import json
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from jarvis.api.auth import require_auth
from jarvis.api.camera_spots import build_camera_setup, router
from jarvis.api.identity import current_user
from jarvis.camera.health import HealthStore, UnknownCamera, camera_setup_privacy
from jarvis.camera.spots import Camera, Room, Spots, SpotsStore
from jarvis.keyring import Keyring
from jarvis.storage.docs import MemoryDocs
from jarvis.vitals.own import camera_item

KEY = bytes(range(51, 83))  # a made-up token key
UID = "u_0123456789abcdef"
NOW = 1_764_300_000.0
DESK = Camera(id="desk_cam", kind="device", source="browser", label="Desk camera", room="study")
PHONE = Camera(id="tripod", kind="device", source="phone", label="Workout phone")
HOME = Camera(id="home_cam", kind="home", source="home", label="Home camera", room="study")
SET = Spots(cameras=(DESK, PHONE, HOME), rooms=(Room(id="study", label="Study"),))


class Clock:
    def __init__(self, t: float = NOW) -> None:
        self.t = t

    def __call__(self) -> float:
        return self.t


async def _stores(
    clock: Clock, home: dict[str, float] | None = None, spots: Spots = SET
) -> tuple[MemoryDocs, SpotsStore, HealthStore]:
    docs = MemoryDocs()
    ring = Keyring(KEY)
    store = SpotsStore(docs, ring, prefix="t_")
    await store.put(UID, spots, base_rev=0)

    async def seen(uid: str) -> dict[str, float]:
        return dict(home or {})

    health = HealthStore(docs, ring, store, prefix="t_", home_seen=seen, clock=clock)
    return docs, store, health


def _line(lines: list[Any], cid: str) -> Any:
    return next(x for x in lines if x.camera == cid)


async def test_a_report_is_sealed_and_shown_as_the_cameras_line() -> None:
    clock = Clock()
    docs, _, health = await _stores(clock, home={"home_cam": NOW - 120})
    await health.report(UID, "desk_cam", fps=0.96667, ms=42, at=NOW - 30)
    raw = json.dumps(await docs.get(f"t_camera_health/{UID}"))
    assert "desk_cam" not in raw and "blob" in raw  # sealed
    lines = await health.lines(UID)
    assert [x.camera for x in lines] == ["desk_cam", "tripod", "home_cam"]
    desk = _line(lines, "desk_cam")
    assert (desk.last_seen, desk.fps, desk.ms, desk.on) == (NOW - 30, 1.0, 42, True)
    item = camera_item(desk, NOW)
    assert item is not None and item.base == ("ok", "")
    assert item.provider.note == "Seen just now, 1 frame a second."
    never = camera_item(_line(lines, "tripod"), NOW)
    assert never is not None and never.provider.note == "Not seen yet: run its setup test."
    home = _line(lines, "home_cam")
    assert home.last_seen == NOW - 120 and home.fps is None and home.source == "home"


async def test_unseen_for_a_day_is_amber_and_switched_off_says_so() -> None:
    clock = Clock()
    _, store, health = await _stores(clock)
    await health.report(UID, "desk_cam", fps=15, ms=30, at=NOW)
    clock.t = NOW + 25 * 3600
    item = camera_item(_line(await health.lines(UID), "desk_cam"), clock.t)
    assert item is not None and item.base[0] == "amber"
    off = SET.model_copy(update={"rooms": (Room(id="study", label="Study", on=False),)})
    await store.put(UID, off, base_rev=1)
    line = _line(await health.lines(UID), "desk_cam")
    assert line.on is False
    item = camera_item(line, clock.t)
    assert item is not None and item.base == ("ok", "is switched off")


async def test_only_his_device_cameras_report_on_the_servers_clock() -> None:
    clock = Clock()
    _, _, health = await _stores(clock)
    for cid in ("home_cam", "nobody"):  # a home camera's line comes from the home kit
        with pytest.raises(UnknownCamera):
            await health.report(UID, cid, fps=1, ms=10, at=NOW)
    await health.report(UID, "tripod", fps=14.6, ms=60, at=NOW + 3600)  # a clock from the future
    assert _line(await health.lines(UID), "tripod").last_seen == NOW
    clock.t = NOW + 10
    await health.report(UID, "tripod", fps=2, ms=5, at=clock.t)  # within 30 s: not written
    assert _line(await health.lines(UID), "tripod").fps == 15.0
    clock.t = NOW + 40
    await health.report(UID, "tripod", fps=2, ms=5, at=clock.t)
    assert _line(await health.lines(UID), "tripod").fps == 2.0


async def test_a_failing_home_kit_leaves_the_home_line_unseen() -> None:
    docs = MemoryDocs()
    ring = Keyring(KEY)
    store = SpotsStore(docs, ring, prefix="t_")
    await store.put(UID, SET, base_rev=0)

    async def broken(uid: str) -> dict[str, float]:
        raise RuntimeError("kit offline")

    health = HealthStore(docs, ring, store, prefix="t_", home_seen=broken, clock=Clock())
    assert _line(await health.lines(UID), "home_cam").last_seen is None


async def test_privacy_counts_exports_and_deletes_the_setup() -> None:
    clock = Clock()
    _, store, health = await _stores(clock)
    await health.report(UID, "desk_cam", fps=1, ms=10, at=NOW)
    row = camera_setup_privacy(store, health)
    view = await row.describe(UID)
    assert view.count == 5 and view.delete == "confirm" and view.export  # 3 cameras, 1 room, 1 line
    assert "alarm" in view.note and view.encrypted_by_jarvis
    out = await row.export_fn(UID)  # type: ignore[misc]
    assert [c["id"] for c in out["cameras"]] == ["desk_cam", "tripod", "home_cam"]
    assert set(out["health"]) == {"desk_cam"} and "blob" not in json.dumps(out)
    assert await row.delete_fn(UID) == 5  # type: ignore[misc]
    assert (await store.get(UID)).cameras == () and await health.count(UID) == 0


# ---- the route -----------------------------------------------------------------------------------
def _client() -> TestClient:
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[require_auth] = lambda: None
    app.dependency_overrides[current_user] = lambda: UID
    app.state.camera_setup = build_camera_setup(MemoryDocs(), Keyring(KEY), prefix="t_")
    return TestClient(app)


def test_the_route_takes_three_numbers_and_the_view_shows_them() -> None:
    c = _client()
    c.put("/v1/camera/spots", json={**SET.model_dump(mode="json"), "rev": 0})
    r = c.post("/v1/camera/health", json={"camera": "desk_cam", "fps": 1.0, "ms": 35})
    assert r.status_code == 200
    v = c.get("/v1/camera/spots").json()
    assert v["health"]["desk_cam"]["fps"] == 1.0 and v["health"]["desk_cam"]["ms"] == 35
    assert v["health"]["tripod"]["last_seen"] is None and isinstance(v["now"], float)
    assert c.post("/v1/camera/health", json={"camera": "nobody", "fps": 1}).status_code == 404
    for bad in (
        {"camera": "desk_cam", "fps": -1},
        {"camera": "desk_cam", "fps": 1, "frame": "data:image/jpeg;base64,/9j/"},
        {"camera": "Desk Cam", "fps": 1},
        {"camera": "desk_cam", "fps": 500},
    ):
        assert c.post("/v1/camera/health", json=bad).status_code == 422, bad
