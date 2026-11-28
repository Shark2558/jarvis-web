# evals/r8/cameras.py
"""R8 eval, builder B (`cameras`): camera setup, the off switches, camera health and the no-cloud
camera check (docs/plans/r8-vision.md v8.0.4 sections 4.5, 4.6, 8; rows 217, 184, 377). Mock
only: the real models, stores and routes on MemoryDocs; the console's real camera door in R7's
Node DOM (tests/fixtures/r7/b_dom.js); the real probe and bridge plugin against the fake RTSP and
ONVIF camera of tests/test_r8_b_camcheck.py (standard library, on 127.0.0.1).

    switch_stops               a camera, a room switched off, a "never" room and "cameras off" each
                               stop looking, with plain words why
    never_room_no_coach        no coach can be chosen in a "never" room; the bridge's coach state
                               keeps only home cameras that may look
    cameras_off_never_disarms  "cameras off" reads the alarm's state and never arms or disarms it;
                               the reply says it is still armed
    door_obeys_the_server      the camera's door refuses a start while the server says every camera
                               is off; "cameras off" by voice locks this device and says so
    probe_refuses_public       only an RFC 1918 IPv4 address is checked; nothing else is dialed
    no_cloud_two_stages        a local-only camera passes after its internet is blocked; one that
                               needs its cloud fails, and an H.265 one fails naming H.264
    password_stays_home        no reply the cloud gets carries the password, a stream address or
                               the camera's maker
    health_in_vitals           a switched-on camera unseen for a day is amber; switched off says so

Four negative controls; each must fail the cases named in EXPECTED (a suite that cannot fail
proves nothing):
    never_ignored    a "never" room is treated as an ordinary room
    public_allowed   the private-range check lets every address through
    offline_skipped  the offline stage passes without looking at the camera again
    alarm_touched    "cameras off" disarms the alarm on its way
"""

from __future__ import annotations

import asyncio
import json
import sys
import tempfile
from collections.abc import Awaitable, Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
for extra in (ROOT / "tests", ROOT / "src"):
    if str(extra) not in sys.path:
        sys.path.insert(0, str(extra))

import httpx  # noqa: E402
from fastapi import FastAPI  # noqa: E402
from r7_fakes_b import run_dom  # noqa: E402
from test_r8_b_camcheck import IP, LOGIN, MAKER, PASSWORD, Sink, camera  # noqa: E402

import jarvis.api.camera_spots as routes  # noqa: E402
from jarvis.api.auth import require_auth  # noqa: E402
from jarvis.api.camera_spots import build_camera_setup, router  # noqa: E402
from jarvis.api.identity import current_user  # noqa: E402
from jarvis.camera import spots as spots_mod  # noqa: E402
from jarvis.camera.health import HealthStore  # noqa: E402
from jarvis.camera.spots import Camera, Room, Spots, SpotsStore  # noqa: E402
from jarvis.home.ports import ArmView  # noqa: E402
from jarvis.homebridge import camcheck  # noqa: E402
from jarvis.homebridge.camcheck import CamCheck, LoginBook, Probe  # noqa: E402
from jarvis.homebridge.plugins import BridgeContext  # noqa: E402
from jarvis.keyring import Keyring  # noqa: E402
from jarvis.storage.docs import MemoryDocs  # noqa: E402
from jarvis.vitals.own import camera_item  # noqa: E402
from jarvis.voice.commands import CAMERAS_OFF_REPLY  # noqa: E402

PART = "cameras"
BUILT = True
KEY = bytes(range(81, 113))  # a made-up token key
UID = "u_0123456789abcdef"
NOW = 1_764_300_000.0
CONTROLS = ("never_ignored", "public_allowed", "offline_skipped", "alarm_touched")
EXPECTED: dict[str, tuple[str, ...]] = {
    "never_ignored": ("switch_stops", "never_room_no_coach"),
    "public_allowed": ("probe_refuses_public",),
    "offline_skipped": ("no_cloud_two_stages",),
    "alarm_touched": ("cameras_off_never_disarms",),
}
DESK = Camera(id="desk_cam", kind="device", source="browser", label="Desk camera", room="study")
HOME = Camera(id="home_cam", kind="home", source="home", label="Home camera", spot="desk",
              room="study")  # fmt: skip
SET = Spots(cameras=(DESK, HOME), rooms=(Room(id="study", label="Study"),))
_active: set[str] = set()
Case = Callable[[], Awaitable[list[str]]]


def _rooms(**over: Any) -> Spots:
    return SET.model_copy(update={"rooms": (Room(id="study", label="Study", **over),)})


# ---- the controls -------------------------------------------------------------------------
_real_why = spots_mod.why_off
_real_private = camcheck.private_ip
_real_offline = CamCheck._offline
_real_armed = routes._armed


def _why_without_never(spots: Spots, camera: str) -> str:
    cleared = spots.model_copy(
        update={"rooms": tuple(r.model_copy(update={"never": False}) for r in spots.rooms)}
    )
    return _real_why(cleared, camera)


async def _offline_blind(self: CamCheck, job: camcheck.Job, req: camcheck.CheckRequest) -> None:
    job.pieces = (camcheck.Piece("offline", True, camcheck.W_OFF_OK),)
    job.verdict, job.missing, job.rounds_done = "pass", "", job.rounds


async def _armed_and_disarmed(arm: Any, uid: str) -> bool | None:
    if arm is not None:
        await arm.disarm(uid)
    return await _real_armed(arm, uid)


@contextmanager
def server_controls() -> Iterator[None]:
    patches: list[tuple[Any, str, Any]] = []
    if "never_ignored" in _active:
        patches.append((spots_mod, "why_off", _why_without_never))
    if "public_allowed" in _active:
        patches += [(camcheck, "private_ip", lambda t: t), (routes, "private_ip", lambda t: t)]
    if "offline_skipped" in _active:
        patches.append((CamCheck, "_offline", _offline_blind))
    if "alarm_touched" in _active:
        patches.append((routes, "_armed", _armed_and_disarmed))
    saved = [(obj, name, getattr(obj, name)) for obj, name, _ in patches]
    try:
        for obj, name, value in patches:
            setattr(obj, name, value)
        yield
    finally:
        for obj, name, value in saved:
            setattr(obj, name, value)


# ---- the cases ----------------------------------------------------------------------------
async def switch_stops() -> list[str]:
    fails = []
    for what, spots, cam in (
        (
            "camera off",
            SET.model_copy(update={"cameras": (DESK.model_copy(update={"on": False}), HOME)}),
            "desk_cam",
        ),
        ("room off", _rooms(on=False), "home_cam"),
        ("never room", _rooms(never=True), "desk_cam"),
        ("cameras off", SET.model_copy(update={"all_off": True}), "home_cam"),
    ):
        if spots_mod.looking_allowed(spots, cam) or not spots_mod.why_off(spots, cam):
            fails.append(f"{what}: {cam} may still look")
    if not spots_mod.looking_allowed(SET, "desk_cam"):
        fails.append("an ordinary camera may not look")
    return fails


async def never_room_no_coach() -> list[str]:
    never = _rooms(never=True)
    fails = []
    if spots_mod.coach_allowed(never, "home_cam"):
        fails.append("a coach may be chosen in a never room")
    if spots_mod.home_uses(never, {"home_cam": ["posture"]}):
        fails.append("the bridge would run a coach in a never room")
    if spots_mod.home_uses(SET.model_copy(update={"all_off": True}), {"home_cam": ["posture"]}):
        fails.append("the bridge would run a coach while every camera is off")
    if spots_mod.home_uses(SET, {"home_cam": ["posture"]}) != {"home_cam": ("posture",)}:
        fails.append("an allowed home camera lost its coach")
    return fails


class Arm:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def view(self, uid: str) -> ArmView:
        self.calls.append("view")
        return ArmView(armed=True, mode="night", rev=2, confirmed=True)

    async def disarm(self, uid: str) -> None:
        self.calls.append("disarm")


async def cameras_off_never_disarms() -> list[str]:
    arm = Arm()
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[require_auth] = lambda: None
    app.dependency_overrides[current_user] = lambda: UID
    app.state.camera_setup = build_camera_setup(MemoryDocs(), Keyring(KEY), arm=arm)  # type: ignore[arg-type]
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        await c.put("/v1/camera/spots", json={**SET.model_dump(mode="json"), "rev": 0})
        r = await c.post("/v1/camera/off", json={"by": "voice"})
        v = (await c.get("/v1/camera/spots")).json()
    fails = []
    if r.status_code != 200 or r.json() != {"all_off": True, "alarm_armed": True}:
        fails.append(f"cameras off answered {r.status_code} {r.text[:120]}")
    if arm.calls != ["view"]:
        fails.append(f"the alarm was touched: {arm.calls}")
    if any(v["allowed"].values()):
        fails.append("a camera may still look after cameras off")
    if any(
        "disarm" in w.lower() and "is in home" not in w.lower() for w in CAMERAS_OFF_REPLY.values()
    ):
        fails.append("the reply suggests the alarm was disarmed")
    return fails


async def door_obeys_the_server() -> list[str]:
    fails = []
    off = {"/v1/camera/spots": {"all_off": True, "allowed": {}}}
    out = await asyncio.to_thread(
        run_dom, "camera", answers=off, steps=[{"op": "start", "tap": True}]
    )
    step = out["steps"][0]
    if step["ok"] or step["code"] != "switched_off" or step["live"] or step["chip"]:
        fails.append(f"a start while every camera is off: {step}")
    said = {"/v1/camera/off": {"all_off": True, "alarm_armed": True}}
    steps = [{"op": "start", "tap": True}, {"op": "voice", "text": "Jarvis, cameras off"}]
    out = await asyncio.to_thread(run_dom, "camera", answers=said, steps=steps)
    v = out["steps"][1]
    if not (v["ok"] and v["locked"] and not v["live"]) or "still armed" not in v["code"]:
        fails.append(f"cameras off by voice: {v}")
    return fails


async def probe_refuses_public() -> list[str]:
    public = ("8.8.8.8", "127.0.0.1", "169.254.1.1", "::1", "nas.local")
    fails = [f"{ip} would be checked" for ip in public if camcheck.private_ip(ip) is not None]
    if routes.private_ip("172.32.0.1") is not None:
        fails.append("the cloud would ask the laptop about a public address")
    async with camera() as cam:
        try:
            await Probe(dial=cam.dial, timeout_s=1.0).run("8.8.8.8", LOGIN)
            fails.append("the probe looked at a public address")
        except ValueError:
            pass
        if cam.dialed:
            fails.append(f"dialed {cam.dialed}")
    return fails


async def _two_stages(tmp: Path, **kw: Any) -> dict[str, Any]:
    async with camera(**kw) as cam:
        book = LoginBook(tmp)
        book.save(IP, LOGIN.user, LOGIN.password)
        ctx = BridgeContext(env={}, data_dir=tmp, events=Sink(), now=lambda: NOW)
        p = CamCheck(
            ctx, probe=Probe(dial=cam.dial, timeout_s=1.0), logins=book, rounds=2, gap_s=0.01
        )
        first = await p.handle({}, {"action": "start", "ip": IP, "stage": "first"})
        if first["verdict"] != "half":
            return first
        cam.restart(internet=False)
        got = await p.handle({}, {"action": "start", "ip": IP, "stage": "offline"})
        for _ in range(200):
            if got["state"] == "done":
                return got
            await asyncio.sleep(0.02)
            got = await p.handle({}, {"action": "status", "ip": IP, "stage": "offline"})
        return got


async def no_cloud_two_stages() -> list[str]:
    fails = []
    with tempfile.TemporaryDirectory() as d:
        local = await _two_stages(Path(d))
    with tempfile.TemporaryDirectory() as d:
        cloudy = await _two_stages(Path(d), needs_cloud=True)
    with tempfile.TemporaryDirectory() as d:
        h265 = await _two_stages(Path(d), codecs=("H264", "H265"))
    if local["verdict"] != "pass":
        fails.append(f"a local-only camera: {local['verdict']} {local['missing']}")
    if cloudy["verdict"] != "fail" or "needs its cloud service" not in cloudy["missing"]:
        fails.append(f"a camera that needs its cloud: {cloudy['verdict']}")
    if h265["verdict"] != "fail" or "H.264" not in h265["missing"]:
        fails.append(f"an H.265 camera: {h265['verdict']} {h265['missing']}")
    return fails


async def password_stays_home() -> list[str]:
    fails = []
    for kw in ({}, {"codecs": ("H264", "H265")}, {"needs_cloud": True}):
        with tempfile.TemporaryDirectory() as d:
            got = json.dumps(await _two_stages(Path(d), **kw))
        routes.CheckView.model_validate(json.loads(got))
        fails += [f"{kw}: {x}" for x in (PASSWORD, "rtsp://", "realmonitor", MAKER) if x in got]
    return fails


async def health_in_vitals() -> list[str]:
    docs, ring = MemoryDocs(), Keyring(KEY)
    store = SpotsStore(docs, ring)
    await store.put(UID, SET, base_rev=0)
    clock = [NOW]
    health = HealthStore(docs, ring, store, clock=lambda: clock[0])
    await health.report(UID, "desk_cam", fps=1, ms=20, at=NOW)
    fails = []
    clock[0] = NOW + 25 * 3600
    line = next(x for x in await health.lines(UID) if x.camera == "desk_cam")
    item = camera_item(line, clock[0])
    if item is None or item.base[0] != "amber":
        fails.append(f"a day unseen is not amber: {item and item.base}")
    await store.put(UID, _rooms(on=False), base_rev=1)
    line = next(x for x in await health.lines(UID) if x.camera == "desk_cam")
    item = camera_item(line, clock[0])
    if item is None or item.base != ("ok", "is switched off"):
        fails.append(f"switched off does not say so: {item and item.base}")
    return fails


CASES: tuple[Case, ...] = (
    switch_stops,
    never_room_no_coach,
    cameras_off_never_disarms,
    door_obeys_the_server,
    probe_refuses_public,
    no_cloud_two_stages,
    password_stays_home,
    health_in_vitals,
)


async def _run() -> list[dict[str, Any]]:
    out = []
    for case in CASES:
        try:
            with server_controls():
                fails = await case()
        except Exception as exc:  # noqa: BLE001 - a case that crashes fails, with its reason
            fails = [f"crashed: {type(exc).__name__}: {str(exc)[:300]}"]
        out.append({"id": f"{PART}:{case.__name__}", "passed": not fails, "failures": fails})
    return out


async def cases() -> list[dict[str, Any]]:
    _active.clear()
    results = await _run()
    print(f"{PART}: {len(results)} cases; negative controls: {', '.join(CONTROLS)}")
    return results


async def control() -> dict[str, Any]:
    """Each control on its own: the suite fails only when EVERY one broke all it must break."""
    failed: dict[str, list[str]] = {}
    for name in CONTROLS:
        _active.clear()
        _active.add(name)
        try:
            got = await _run()
        finally:
            _active.clear()
        failed[name] = [r["id"] for r in got if not r["passed"]]
    caught = all({f"{PART}:{c}" for c in EXPECTED[name]} <= set(failed[name]) for name in CONTROLS)
    return {"name": " + ".join(CONTROLS), "suite_failed": caught, "failed_cases": failed}


if __name__ == "__main__":  # a quick look: python evals/r8/cameras.py
    res = asyncio.run(cases())
    print(json.dumps(res, indent=1))
    print(json.dumps(asyncio.run(control()), indent=1))

__all__ = ["BUILT", "CASES", "CONTROLS", "EXPECTED", "PART", "cases", "control"]
