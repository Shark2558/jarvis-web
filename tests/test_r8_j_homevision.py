# tests/test_r8_j_homevision.py -- R8 builder J (docs/plans/r8-vision.md v8.0.4 section 4.5a; the
# owner's D3, D4, D6, D11; ADR-49; row 216's home leg): the home camera's vision on the home laptop.
# Row 216's check for this leg: "the home vision plugin reads the home camera's RTSP sub-stream,
# runs pose on the laptop (full model if it keeps >= 15 frames a second, else lite: D4) and sends
# only views and tallies; a CI test proves no frame, point or box leaves it". Every case runs on a
# synthetic RTSP source (scripted scenes of synthetic bodies) or a recorded synthetic stream; the
# camera itself arrives on 3 Dec 2026.
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
import sqlite3
import types
from pathlib import Path
from typing import Any

import pytest
import r8_j_fakes as F

from jarvis.coach.home import engines as E
from jarvis.coach.home import identify as I
from jarvis.coach.home import runtime as R
from jarvis.home.ports import BridgeState, CoachReport, CoachState, parse_event
from jarvis.homebridge import homevision as HV
from jarvis.homebridge.plugins import BridgeContext

ROOT = Path(__file__).resolve().parents[1]
HOME = ROOT / "deploy" / "home"
CAM = "desk_cam"
ANA, BOB = "fp_aaaaaaaaaaaa", "fp_bbbbbbbbbbbb"


def make(scenes: list[list[list[dict[str, float]]]], *, uses: tuple[str, ...] = ("posture",),
         fps: float = 1.0, leak: str = "", hint: float | None = None, faces: Any = None,
         objects: Any = None, target: str = "all", person: str | None = None,
         loop: bool = True, away_s: float = R.AWAY_KEEP_S) -> Any:  # fmt: skip
    clock = F.FakeClock()
    src = F.FakeSource(scenes, clock, fps=fps, loop=loop)
    pose = F.FakePose(src)
    sink = F.Sink()
    recs = {u: F.Recorder(u, ("pose", "objects") if u in ("activity", "bp-posture") else ("pose",),
                          leak=leak, hint=hint) for u in uses}  # fmt: skip
    registry = {u: (lambda r=r: r) for u, r in recs.items()}
    rt = R.HomeRuntime(CAM, src, pose, sink, objects=objects, identifier=faces,
                       registry=registry, wall=clock.wall, mono=clock.mono,
                       idle_s=0.01, retry_s=0.01, away_s=away_s)  # fmt: skip
    rt.apply(CoachState(rev=1, uses={CAM: uses}, target=target, person=person))  # type: ignore[arg-type]
    return types.SimpleNamespace(rt=rt, src=src, pose=pose, sink=sink, recs=recs, clock=clock)


async def steps(world: Any, n: int) -> None:
    for _ in range(n):
        await world.rt.step()


def wire(event: CoachReport) -> str:
    return event.model_dump_json(exclude_none=True)


# ---- what leaves the laptop: views and tallies, never a frame, a point or a box -----------------


async def test_no_frame_point_or_box_leaves_in_any_report() -> None:
    a, b = F.body(0.3, seed=3), F.body(0.7, seed=11)
    scenes = [[F.body(0.3 + i * 0.002, seed=3 + i), F.body(0.7, seed=11 + i)] for i in range(30)]
    w = make(scenes, uses=("posture", "activity"), objects=F.FakeObjects("cell_phone"), loop=False)
    await steps(w, 30)
    await steps(w, 1)  # the stream ends: retried, nothing lost
    w.rt.apply(CoachState(rev=2, all_off=True))
    await steps(w, 1)  # "cameras off": every session's tally goes up
    seen = [s for r in w.recs.values() for s in r.seen]
    assert any(s.points == 33 for s in seen) and any(s.things == 1 for s in seen)  # they had them
    needles = F.coordinates(scenes + [[a, b]]) | {v for v in F.BOX.values()}
    assert w.sink.events and w.sink.tallies()
    for event in w.sink.events:
        text = wire(event)
        kind: str = parse_event(text.encode()).type
        assert kind == "coach"  # the cloud's own parser takes it
        assert len(text) < 4096
        for key in ("points", "box", '"x"', '"y"', "landmark", "image", "frame", "jpeg"):
            assert key not in text, key
        numbers = {float(n) for n in re.findall(r"-?\d+\.\d+", text)}
        assert not numbers & needles
        assert event.camera == CAM and re.fullmatch(r"cs_[0-9a-f]{12}", event.session)


@pytest.mark.parametrize("leak", ["points", "box", "copy", "bad_tally"])
async def test_a_use_case_that_tries_to_send_geometry_or_a_bad_tally_is_refused(leak: str) -> None:
    scenes = [[F.body(0.5, seed=5 + i)] for i in range(5)]
    w = make(scenes, leak=leak)
    await steps(w, 5)
    w.rt.apply(CoachState(rev=2, uses={}))
    await steps(w, 1)
    assert w.rt.refused >= 1
    needles = F.coordinates(scenes) | set(F.BOX.values())
    for event in w.sink.events:
        text = wire(event)
        assert "points" not in text and "box" not in text and "9000" not in text
        assert not {float(n) for n in re.findall(r"-?\d+\.\d+", text)} & needles
    if leak in ("box", "bad_tally"):
        assert not w.sink.tallies() and w.sink.views()  # only the tally's report is dropped
    else:
        assert not w.sink.events  # every view held the leak


def test_the_cleaners_keep_the_fixed_widgets_and_scalars_only() -> None:
    raw = [{"kind": "big", "value": 3, "word": "reps"}, {"kind": "html", "value": 1},
           {"kind": "line", "text": "x" * 121}, {"kind": "bar", "value": float("nan")},
           "nope", {"kind": "tip", "text": "Sit back"}]  # fmt: skip
    assert R.clean_view(raw) == ({"kind": "big", "value": 3, "word": "reps"},
                                 {"kind": "tip", "text": "Sit back"})  # fmt: skip
    assert R.clean_view([{"kind": "line", "Box": 1}]) is None
    assert R.clean_view(None) == ()
    good = F.posture_tally(10, 20)
    assert R.clean_tally("posture", good) == good
    assert R.clean_tally("posture", {**good, "upright": 101}) is None
    assert R.clean_tally("posture", {**good, "landmarks": []}) is None
    assert R.clean_tally("nope", good) is None


# ---- one body at a time: tracks, who, the target ------------------------------------------------


async def test_each_body_gets_its_own_state_track_and_who() -> None:
    faces = F.FakeFaces({0.3: ANA})
    scenes = [[F.body(0.3 + 0.01 * i, seed=i), F.body(0.7 - 0.01 * i, seed=50 + i)]
              for i in range(8)]  # fmt: skip
    w = make(scenes, faces=faces, loop=False)
    await steps(w, 8)
    seen = w.recs["posture"].seen
    tracks = {s.track for s in seen}
    assert len(tracks) == 2  # two bodies, two tracks, kept as they move
    by_track = {t: {s.who for s in seen if s.track == t} for t in tracks}
    assert sorted(map(sorted, by_track.values())) == [[""], [ANA]]  # named, and a guest
    assert all(s.points == 33 for s in seen)
    assert len(w.rt._uses["posture"].states) == 2  # noqa: SLF001
    assert faces.calls < 2 * 8  # a named body's face is not looked at every frame


async def test_a_body_alone_in_view_is_me_while_its_track_lasts() -> None:
    me = [[F.body(0.5, seed=i)] for i in range(3)]
    both = [[F.body(0.5, seed=10 + i), F.body(0.85, seed=40 + i)] for i in range(3)]
    w = make(me + both, loop=False)
    await steps(w, 6)
    seen = w.recs["posture"].seen
    first = seen[0].track
    assert {s.who for s in seen if s.track == first} == {"me"}
    assert {s.who for s in seen if s.track != first} == {""}  # who came later is a guest


@pytest.mark.parametrize(("target", "person", "fed"), [("all", None, {"me", "", ANA}),
                                                       ("me", None, {"me"}),
                                                       ("person", ANA, {ANA})])  # fmt: skip
async def test_the_tracking_target_picks_the_bodies(target: str, person: str | None,
                                                     fed: set[str]) -> None:  # fmt: skip
    first = [[F.body(0.5, seed=i)] for i in range(2)]  # "me": alone when it appeared
    then = [[F.body(0.5, seed=9 + i), F.body(0.2, seed=20 + i), F.body(0.85, seed=30 + i)]
            for i in range(4)]  # fmt: skip
    w = make(first + then, faces=F.FakeFaces({0.85: ANA}), target=target, person=person,
             loop=False)  # fmt: skip
    await steps(w, 6)
    assert {s.who for s in w.recs["posture"].seen} == fed


# ---- off switches, sessions and pacing ----------------------------------------------------------


async def test_cameras_off_stops_the_stream_at_once_and_ends_every_session() -> None:
    w = make([[F.body(0.5, seed=i)] for i in range(4)])
    await steps(w, 3)
    assert w.rt.part().running and w.rt.part().uses == ("posture",)
    w.rt.apply(CoachState(rev=2, uses={CAM: ("posture",)}, all_off=True))
    assert w.rt._stop.is_set()  # noqa: SLF001 - a waiting read returns within one frame
    reads = w.src.reads
    await steps(w, 2)
    assert w.src.reads == reads and w.src.closed >= 1 and w.pose.closed >= 1
    assert not w.rt.part().running
    (final,) = w.sink.tallies()
    assert final.tally is not None and final.tally["started_at"] <= final.tally["ended_at"]
    w.rt.apply(CoachState(rev=1, uses={CAM: ("posture",)}))  # an older push changes nothing
    await steps(w, 1)
    assert w.src.reads == reads
    w.rt.apply(CoachState(rev=3, uses={CAM: ("posture",)}))
    await steps(w, 1)
    assert w.src.reads == reads + 1 and w.sink.events[-1].session != final.session  # a new look


async def test_only_this_cameras_home_use_cases_run() -> None:
    w = make([[F.body(0.5)]])
    w.rt.apply(CoachState(rev=2, uses={"other_cam": ("posture",), CAM: ("water",)}))
    assert w.rt.wanted() == ()  # water is a webcam coach (browser), another camera isn't this one
    await steps(w, 1)
    assert w.src.reads == 0


async def test_a_body_that_leaves_ends_its_session_with_a_tally() -> None:
    """A session coach (seated) ends a body's session once it has left (LOST_S)."""
    there = [[F.body(0.5, seed=i)] for i in range(3)]
    gone: list[list[list[dict[str, float]]]] = [[] for _ in range(int(R.LOST_S) + 3)]
    w = make(there + gone, uses=("seated",), loop=False)
    await steps(w, len(there) + len(gone))
    (final,) = w.sink.tallies()
    assert final.who == "me" and final.use == "seated"
    assert not w.rt._uses["seated"].states  # noqa: SLF001


async def test_an_all_day_coach_keeps_his_state_while_he_is_out_of_view() -> None:
    """R8 I1 (C's ask): posture keeps his state (his calibration) while he is away; no view goes
    up meanwhile; back in view (a new track) the same state goes on; away too long, it ends."""
    there = [[F.body(0.5, seed=i)] for i in range(3)]
    gone: list[list[list[dict[str, float]]]] = [[] for _ in range(int(R.LOST_S) + 20)]
    back = [[F.body(0.5, seed=50 + i)] for i in range(3)]
    w = make(there + gone + back, loop=False, away_s=60.0)
    await steps(w, len(there) + int(R.LOST_S) + 2)
    states = w.rt._uses["posture"].states  # noqa: SLF001
    assert len(states) == 1 and next(iter(states.values())).who == "me"  # parked, not ended
    assert w.sink.tallies() == []
    sent = len(w.sink.views())
    await steps(w, len(gone) - int(R.LOST_S) - 2)
    assert len(w.sink.views()) == sent  # no view while he is away
    first = next(iter(states.values()))
    await steps(w, len(back))
    assert list(states.values()) == [first]  # back: the same state, under whatever track
    assert w.sink.tallies() == []
    w2 = make(there + [[] for _ in range(80)], loop=False, away_s=60.0)
    await steps(w2, 3 + 80)
    (final,) = w2.sink.tallies()  # away longer than away_s: the session ends with its tally
    assert final.who == "me" and final.use == "posture"
    assert not w2.rt._uses["posture"].states  # noqa: SLF001


async def test_a_guest_who_leaves_ends_at_once_even_on_an_all_day_coach() -> None:
    two = [[F.body(0.3, seed=i), F.body(0.7, seed=9 + i)] for i in range(3)]  # nobody is "me"
    gone: list[list[list[dict[str, float]]]] = [[] for _ in range(int(R.LOST_S) + 3)]
    w = make(two + gone, loop=False)
    await steps(w, len(two) + len(gone))
    assert sorted(e.who for e in w.sink.tallies()) == ["", ""]
    assert not w.rt._uses["posture"].states  # noqa: SLF001


async def test_a_thing_in_view_never_keeps_a_body_that_left_in_its_session() -> None:
    """Things keep coming to a parked state (activity counts those minutes as away), but only
    until it has been away for `away_s`: a thing never makes a body that left seen."""
    there = [[F.body(0.5, seed=i)] for i in range(3)]
    gone: list[list[list[dict[str, float]]]] = [[] for _ in range(80)]
    w = make(there + gone, uses=("activity",), objects=F.FakeObjects("cup"), loop=False,
             away_s=60.0)  # fmt: skip
    await steps(w, len(there) + len(gone))
    assert any(s.things for s in w.recs["activity"].seen)  # the cup kept coming
    assert [e.use for e in w.sink.tallies()] == ["activity"]  # and the session still ended
    assert not w.rt._uses["activity"].states  # noqa: SLF001


async def test_cameras_off_while_the_models_load_means_no_frame_is_read() -> None:
    w = make([[F.body(0.5)]])
    real = w.pose.status

    def slow_status() -> str:
        w.rt._coach = CoachState(rev=9, all_off=True)  # noqa: SLF001 - lands mid-step
        return str(real())

    w.pose.status = slow_status
    await steps(w, 1)
    assert w.src.reads == 0


async def test_a_decoder_or_model_fault_is_one_skipped_frame_never_the_loop() -> None:
    w = make([[F.body(0.5)]])

    def broken(until: float, stop: Any) -> Any:
        raise ValueError("cv2.error: something native")

    real_read = w.src.read
    w.src.read = broken
    await steps(w, 1)
    assert w.rt.why == "the home camera's stream: unreadable" and w.src.closed == 1
    w.src.read = real_read
    real_bodies = w.pose.bodies
    w.pose.bodies = lambda frame: (_ for _ in ()).throw(RuntimeError("model fault"))
    await steps(w, 1)
    assert w.src.reads == 1 and not w.sink.events
    w.pose.bodies = real_bodies
    await steps(w, 1)
    assert w.src.reads == 2 and w.sink.events


async def test_views_are_paced_and_all_day_coaches_keep_a_tally_every_15_minutes() -> None:
    minutes = 31
    w = make([[F.body(0.5, seed=7)]], uses=("posture", "bp-posture"), loop=True)
    await steps(w, minutes * 60)  # 1 a second, the posture coach's rate
    views = w.sink.views()
    per_minute: dict[int, int] = {}
    for e in views:
        per_minute[int((e.at - F.WALL0) // 60)] = per_minute.get(int((e.at - F.WALL0) // 60), 0) + 1
    assert max(per_minute.values()) <= R.VIEWS_PER_MIN
    posture = [e for e in views if e.use == "posture"]
    gaps = [b.at - a.at for a, b in zip(posture, posture[1:], strict=False)]
    assert min(gaps) >= R.VIEW_EVERY_S
    tallies = [e for e in w.sink.tallies() if e.use == "posture"]
    assert len(tallies) == 2 and w.recs["posture"].kept_calls == 2  # minute 15 and 30
    assert not [e for e in w.sink.tallies() if e.use == "bp-posture"]  # only at a session's end
    w.rt.apply(CoachState(rev=2, uses={CAM: ("posture",)}))
    await steps(w, 1)
    assert [e.use for e in w.sink.tallies()][-1] == "bp-posture"


async def test_the_rate_follows_the_use_cases_and_a_slow_laptop_slows_itself() -> None:
    w = make([[F.body(0.5)]], uses=("posture",))
    await steps(w, 2)
    assert w.rt._rate() == 1.0  # noqa: SLF001
    w.recs["posture"].hint = 2.0  # a slouch is suspected
    assert w.rt._rate() == 2.0  # noqa: SLF001
    w.recs["posture"].hint = 99.0
    assert w.rt._rate() == R.LIVE_MAX_FPS  # noqa: SLF001
    s = make([[F.body(0.5)]], uses=("seated",), fps=15.0)
    await steps(s, 2)
    assert s.rt._rate() == 15.0  # noqa: SLF001
    t0 = s.clock.t
    await steps(s, 15)
    assert s.clock.t - t0 == pytest.approx(1.0, abs=0.01)  # 15 looks in a second
    assert s.rt.part().model == "lite" and s.rt.part().fps is not None


async def test_a_broken_use_case_never_stops_the_loop() -> None:
    w = make([[F.body(0.5)]], leak="raises")
    await steps(w, 3)
    assert w.src.reads == 3 and w.rt.part().running


async def test_a_stream_that_is_down_is_retried_and_its_address_is_never_logged(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG)
    w = make([[F.body(0.5)]])
    w.src.down = "unreachable"
    await steps(w, 2)
    assert "unreachable" in w.rt.why and w.src.reads == 0
    w.src.down = None
    await steps(w, 1)
    assert w.src.reads == 1 and w.rt.why == ""
    ctx = BridgeContext(env={"HOMEVISION_RTSP_URL": F.SECRET_URL.replace("192.168", "8.8"),
                             "HOMEVISION_CAMERA": CAM}, data_dir=Path("/nonexistent"),
                        events=F.Sink())  # type: ignore[arg-type]  # fmt: skip
    assert HV.HomeVisionPlugin(ctx).why == HV.BAD_ADDRESS
    src = E.OpenCvSource(F.SECRET_URL)
    assert "S3cret" not in repr(src) and "192.168" not in repr(src)
    for record in caplog.records:
        line = record.getMessage() + json.dumps(record.__dict__, default=str)
        assert "S3cret" not in line and "1.50" not in line and "realmonitor" not in line


# ---- the plugin ---------------------------------------------------------------------------------


def _ctx(tmp: Path, **env: str) -> BridgeContext:
    return BridgeContext(env=env, data_dir=tmp, events=F.Sink())  # type: ignore[arg-type]


async def test_the_plugin_runs_nothing_until_the_camera_is_set_up_and_serves_no_route(
    tmp_path: Path,
) -> None:
    off = HV.create_plugin(_ctx(tmp_path))
    assert off.routes() == () and off.tasks() == () and off.why == HV.NOT_SET
    assert (await off.heartbeat_part()).homevision.running is False  # type: ignore[union-attr]
    bad = {"HOMEVISION_RTSP_URL": "http://192.168.1.5/x", "HOMEVISION_CAMERA": CAM}
    assert HV.create_plugin(_ctx(tmp_path, **bad)).tasks() == ()
    wrong = {"HOMEVISION_RTSP_URL": F.SECRET_URL, "HOMEVISION_CAMERA": "Desk Cam"}
    assert HV.create_plugin(_ctx(tmp_path, **wrong)).why == HV.BAD_CAMERA
    on = HV.create_plugin(_ctx(tmp_path, HOMEVISION_RTSP_URL=F.SECRET_URL, HOMEVISION_CAMERA=CAM))
    assert on.routes() == () and len(on.tasks()) == 1 and on.why == ""
    part = (await on.heartbeat_part()).homevision
    assert part is not None and part.running is False and part.uses == ()


async def test_the_coach_part_reaches_the_plugin_through_the_bridge_and_a_restart(
    tmp_path: Path,
) -> None:
    from jarvis.homebridge.heartbeat import HeartbeatLoop
    from jarvis.homebridge.state import BridgeStore

    store = BridgeStore(tmp_path)
    plugin = HV.create_plugin(_ctx(tmp_path, HOMEVISION_RTSP_URL=F.SECRET_URL,
                                   HOMEVISION_CAMERA=CAM))  # fmt: skip
    loop = HeartbeatLoop(store, None, [plugin])  # type: ignore[arg-type]
    coach = CoachState(rev=5, uses={CAM: ("posture",)}, target="me")
    await loop.apply(BridgeState(coach=coach))
    assert store.state.coach == coach  # kept by its own rev, like the other parts
    assert plugin.runtime is not None and plugin.runtime._coach == coach  # noqa: SLF001
    await loop.apply(BridgeState(coach=CoachState(rev=4, all_off=True)))
    assert store.state.coach == coach  # an older push changes nothing
    (tmp_path / "state.json").write_text(store.state.model_dump_json())
    again = HV.create_plugin(_ctx(tmp_path, HOMEVISION_RTSP_URL=F.SECRET_URL,
                                  HOMEVISION_CAMERA=CAM))  # fmt: skip
    assert again.runtime is not None and again.runtime._coach == coach  # noqa: SLF001
    await again.on_reply(BridgeState(coach=CoachState(rev=6, all_off=True)))
    assert again.runtime._coach.all_off  # noqa: SLF001


@pytest.mark.parametrize(
    ("url", "ok"),
    [
        (F.SECRET_URL, True),
        ("rtsp://10.0.0.7/stream1", True),
        ("rtsp://172.20.1.9:8554/sub", True),
        ("rtsp://[fd00::5]/sub", True),
        ("rtsp://8.8.8.8/x", False),
        ("rtsp://127.0.0.1/x", False),
        ("rtsp://169.254.1.1/x", False),
        ("rtsp://camera.local/x", False),
        ("rtsps://192.168.1.5/x", False),
        ("http://192.168.1.5/x", False),
        ("rtsp://192.168.1.5:0/x", False),
        ("", False),
    ],
)
def test_only_an_rtsp_address_on_the_home_network_is_read(url: str, ok: bool) -> None:
    assert E.rtsp_url_ok(url) is ok


# ---- the real decoder on a recorded synthetic stream --------------------------------------------


def test_the_opencv_source_reads_a_recorded_stream_newest_frame_first(tmp_path: Path) -> None:
    cv = pytest.importorskip("cv2")
    np = pytest.importorskip("numpy")
    path = tmp_path / "sub.avi"
    out = cv.VideoWriter(str(path), cv.VideoWriter_fourcc(*"MJPG"), 15.0, (160, 90))
    for i in range(30):
        frame = np.zeros((90, 160, 3), dtype=np.uint8)
        frame[:, : 5 * (i + 1)] = (0, 0, 255)  # red in BGR, wider each frame
        out.write(frame)
    out.release()
    clock = F.FakeClock()
    src = E.OpenCvSource(F.SECRET_URL, opener=lambda c: c.VideoCapture(str(path)),
                         clock=clock.mono, wall=clock.wall)  # fmt: skip
    stop = __import__("threading").Event()
    first = src.read(0.0, stop)
    assert first is not None and (first.height, first.width) == (90, 160)
    assert tuple(int(v) for v in first.image[45, 0]) == (255, 0, 0) or first.image[45, 0][0] > 200
    assert first.image.shape == (90, 160, 3)
    stop.set()
    assert src.read(0.0, stop) is None
    stop.clear()
    with pytest.raises(E.SourceDown) as down:
        src.read(clock.t + 1e9, stop)  # waits for a newer frame: the recording ends
    assert str(down.value) == "no_frames"
    src.close()
    with pytest.raises(E.SourceDown, match="bad_address"):
        E.OpenCvSource("rtsp://8.8.8.8/x").open()


# ---- the pose model (D4) and its pins -----------------------------------------------------------


def _fake_mp(created: list[str]) -> Any:
    class Landmarker:
        def __init__(self, path: str) -> None:
            self.path = path

        def detect_for_video(self, image: Any, stamp: int) -> Any:
            pts = [types.SimpleNamespace(x=0.5, y=0.5, z=0.0, visibility=0.9)] * 33
            return types.SimpleNamespace(pose_landmarks=[pts, pts[:10]])

        def close(self) -> None:
            created.append("closed")

    def create(opts: Any) -> Landmarker:
        created.append(Path(opts.base_options.model_asset_path).name)
        assert opts.num_poses == 4 and opts.running_mode == "VIDEO"
        return Landmarker(opts.base_options.model_asset_path)

    vision = types.SimpleNamespace(
        PoseLandmarkerOptions=lambda **kw: types.SimpleNamespace(**kw),
        RunningMode=types.SimpleNamespace(VIDEO="VIDEO"),
        PoseLandmarker=types.SimpleNamespace(create_from_options=create),
    )
    mp = types.SimpleNamespace(Image=lambda **kw: kw, ImageFormat=types.SimpleNamespace(SRGB=1))
    return types.SimpleNamespace(mp=mp, vision=vision,
                                 BaseOptions=lambda **kw: types.SimpleNamespace(**kw))  # fmt: skip


def _pins(tmp: Path, *kinds: str) -> dict[str, Any]:
    pins = {}
    for kind, pin in E.POSE_MODELS.items():
        data = f"model {kind}".encode()
        if kind in kinds:
            (tmp / pin.name).write_bytes(data)
        pins[kind] = type(pin)(pin.name, hashlib.sha256(data).hexdigest(), len(data), pin.licence,
                               pin.source)  # fmt: skip
    return pins


@pytest.mark.parametrize(("per_frame_s", "model"), [(0.01, "full"), (0.2, "lite")])
def test_the_full_model_stays_only_while_the_laptop_keeps_15_a_second(
    tmp_path: Path, per_frame_s: float, model: str
) -> None:
    created: list[str] = []
    ticks = iter(i * per_frame_s / 2 for i in range(10_000))
    pose = E.MediaPipePose(tmp_path, load=lambda: _fake_mp(created), pins=_pins(tmp_path, "full",
                           "lite"), clock=lambda: next(ticks) * 2)  # fmt: skip
    assert pose.status() == E.READY and pose.model == "full"
    frame = E.Frame(object(), F.WALL0, 1, 640, 360)
    for _ in range(E.BENCH_FRAMES + 2):
        bodies = pose.bodies(frame)
    assert len(bodies) == 1 and len(bodies[0]) == 33  # a body with too few points is left out
    assert pose.model == model and pose.capacity is not None
    assert created[0] == "pose_landmarker_full.task"


def test_a_model_that_is_missing_unpinned_or_changed_is_never_loaded(tmp_path: Path) -> None:
    def never() -> Any:
        raise AssertionError("loaded")

    assert E.MediaPipePose(tmp_path, load=never).status() == E.NOT_PINNED  # the shipped pins
    assert E.MediaPipePose(tmp_path, load=never, pins=_pins(tmp_path)).status() == E.NO_MODELS
    pins = _pins(tmp_path, "full")
    (tmp_path / "pose_landmarker_full.task").write_bytes(b"model fulL")
    assert E.MediaPipePose(tmp_path, load=never, pins=pins).status() == E.CHANGED_MODEL
    created: list[str] = []
    only_lite = E.MediaPipePose(tmp_path, load=lambda: _fake_mp(created),
                                pins=_pins(tmp_path, "lite"))  # fmt: skip
    assert only_lite.status() == E.READY and only_lite.model == "lite"


def test_the_laptop_pose_pins_follow_the_browser_manifests() -> None:
    """The same files as the browser's (D4, ADR-50): once the vision-models workflow pins a
    model in its manifest, the laptop's pin and the kit's model list carry the same SHA-256."""
    vendor = ROOT / "src" / "jarvis" / "api" / "static" / "vendor" / "vision"
    where = {"lite": vendor / "r7-1" / "MANIFEST.json", "full": vendor / "r8-1" / "MANIFEST.json"}
    listed = (HOME / "models" / "MODELS.txt").read_text()
    for kind, manifest in where.items():
        pin = E.POSE_MODELS[kind]
        data = json.loads(manifest.read_text())
        entry = data.get("files", {}).get(pin.name) or data.get("models", {}).get(pin.name, {})
        sha = entry.get("sha256", "")
        assert pin.sha256 == sha, f"{pin.name}: pin it in engines.POSE_MODELS from {manifest.name}"
        if sha:
            assert entry.get("bytes") == pin.size
            assert re.search(rf"^{sha}\s+{pin.size}\s+Apache-2.0\s+{pin.name}\s", listed, re.M)
        assert pin.licence == "Apache-2.0" and pin.source == entry.get("url", pin.source)


def test_mediapipe_is_imported_with_an_inert_matplotlib_that_is_then_taken_away() -> None:
    import sys

    found: dict[str, Any] = {}

    def load(name: str) -> Any:
        found[name] = sys.modules.get("matplotlib.pyplot")
        if name.endswith("base_options"):
            return types.SimpleNamespace(BaseOptions=object)
        return types.SimpleNamespace()

    had = "matplotlib" in sys.modules
    E.load_mediapipe(load)
    if not had and __import__("importlib.util").util.find_spec("matplotlib") is None:
        stand_in = found["mediapipe"]
        assert stand_in is not None and "matplotlib" not in sys.modules
        with pytest.raises(RuntimeError, match="not part of the home kit"):
            stand_in.plot()


# ---- who: the face library, read-only, consent only ---------------------------------------------


def _vec(seed: int) -> tuple[float, ...]:
    import math as m

    raw = [m.sin(seed * m.pi / 2 + i) for i in range(128)]  # alike only to itself
    norm = m.sqrt(sum(v * v for v in raw))
    return tuple(v / norm for v in raw)


def test_a_body_is_named_from_the_named_faces_only_with_consent_and_nothing_is_written(
    tmp_path: Path,
) -> None:
    np = pytest.importorskip("numpy")
    from jarvis.homebridge.face_store import FaceStore
    from jarvis.homebridge.face_types import SeenFace

    store = FaceStore(tmp_path / "facegroups")
    placed = store.place("pic1", [SeenFace(_vec(1), 0.95, 120, b""), SeenFace(_vec(2), 0.95,
                                                                           120, b"")])  # fmt: skip
    store.name(placed[0].group, ANA, consented=lambda p: True)
    store.close()
    db = tmp_path / "facegroups" / "groups.db"
    before = hashlib.sha256(db.read_bytes()).hexdigest()
    assert set(I.named_centres(db)) == {ANA}  # the unnamed group is nobody
    consent = {ANA: True}

    class Det:
        def setInputSize(self, size: Any) -> None:  # noqa: N802 - OpenCV's name
            pass

        def detect(self, crop: Any) -> Any:
            return None, np.array([[10, 10, 60, 60] + [0] * 10 + [0.97]], dtype=np.float32)

    class Rec:
        def __init__(self, v: tuple[float, ...]) -> None:
            self.v = v

        def alignCrop(self, crop: Any, row: Any) -> Any:  # noqa: N802
            return crop

        def feature(self, aligned: Any) -> Any:
            return np.array(self.v, dtype=np.float32)

    faces = I.LaptopFaces(tmp_path, db, lambda p: consent.get(p, False), match=0.42)
    frame = E.Frame(np.zeros((360, 640, 3), dtype=np.uint8), F.WALL0, 1, 640, 360)
    points = F.body(0.5, scale=0.6, noise=0.0)
    for i in range(11):  # spread the face points so the head is big enough to look at
        points[i] = {**points[i], "x": 0.45 + 0.01 * i, "y": 0.2 + 0.005 * i}
    faces.install(object(), Det(), Rec(_vec(1)))
    assert faces.who(frame, points) == ANA
    faces.install(object(), Det(), Rec(_vec(2)))
    assert faces.who(frame, points) == ""  # like an unnamed group: a guest
    faces.install(object(), Det(), Rec(_vec(1)))
    consent[ANA] = False
    faces._centres_at = -1e9  # noqa: SLF001 - the next look reads the groups again
    assert faces.who(frame, points) == "" and faces.status() == I.NO_PEOPLE
    away = [{**p, "visibility": 0.1} for p in points]
    consent[ANA] = True
    assert faces.who(frame, away) == ""  # a face it can't see is nobody
    assert hashlib.sha256(db.read_bytes()).hexdigest() == before  # read-only: nothing written
    with sqlite3.connect(db) as con:
        assert con.execute("SELECT COUNT(*) FROM crops").fetchone()[0] == 0


def test_without_the_face_models_everyone_is_unknown(tmp_path: Path) -> None:
    faces = I.LaptopFaces(tmp_path, tmp_path / "none.db", lambda p: True, match=0.42)
    assert faces.status() in (I.NO_MODELS, I.NO_LIBRARY)
    assert faces.who(E.Frame(None, 0.0, 0, 640, 360), F.body()) == ""


# ---- the image and the kit ----------------------------------------------------------------------


def test_every_runtime_package_is_hash_locked_in_the_bridge_image() -> None:
    reqs = (HOME / "bridge-requirements.txt").read_text()
    for dist in E.RUNTIME_PACKAGES.values():
        hashes = r"((?:\s*\\\n\s*--hash=sha256:[0-9a-f]{64})+)"
        block = re.search(rf"^{re.escape(dist)}==([^\s\\]+)" + hashes, reqs, re.M)
        assert block is not None, dist
        if dist == "mediapipe":
            assert block.group(1) == "1.2.3" and block.group(2).count("--hash=") == 2
    df = (HOME / "bridge.Dockerfile").read_text()
    assert "libegl1 libgles2" in df and "--no-install-recommends" in df
    assert 'OPENCV_FFMPEG_CAPTURE_OPTIONS="rtsp_transport;tcp"' in df
    assert "OPENCV_FFMPEG_LOGLEVEL=-8" in df  # FFmpeg's own lines (which may name the address)
    assert df.index("apt-get install") < df.index("USER 10001")
    assert set(HV.HOME_OBJECTS) <= set(__import__("jarvis.vision.results").vision.results
                                       .OBJECT_LABELS)  # fmt: skip


def test_the_kit_carries_the_home_rules_and_nothing_of_the_cloud() -> None:
    from jarvis.home import kit

    files = kit.bridge_sources(ROOT / "src")
    for rel in ("jarvis/coach/home/runtime.py", "jarvis/coach/home/engines.py",
                "jarvis/coach/home/identify.py", "jarvis/coach/home/__init__.py",
                "jarvis/coach/usecases.py", "jarvis/coach/sources.py"):  # fmt: skip
        assert rel in files, rel
    assert files["jarvis/coach/__init__.py"].startswith(b'"""Part of the JARVIS home kit.')
    assert not any(f.startswith(("jarvis/coach/live", "jarvis/coach/store", "jarvis/api"))
                   for f in files)  # fmt: skip
    assert kit._is_safe_jarvis("jarvis.coach.home.posture")  # noqa: SLF001 - C's and D's rules
    assert not kit._is_safe_jarvis("jarvis.coach.store")  # noqa: SLF001
    assert not kit._is_safe_jarvis("jarvis.coach.homework")  # noqa: SLF001


def test_the_env_example_and_the_setup_step_keep_the_address_on_the_laptop(tmp_path: Path) -> None:
    from test_deploy_home import run_script

    example = (HOME / "bridge.env.example").read_text()
    assert "HOMEVISION_RTSP_URL=\n" in example and "HOMEVISION_CAMERA=\n" in example
    run_script(tmp_path, "configure")
    env_file = tmp_path / "home" / "jarvis-home" / "bridge.env"
    done, calls = run_script(tmp_path, "home-camera", HOME_CAMERA_URL=F.SECRET_URL,
                             HOME_CAMERA_ID=CAM)  # fmt: skip
    assert done.returncode == 0, done.stderr
    text = env_file.read_text()
    assert f"HOMEVISION_RTSP_URL={F.SECRET_URL}\n" in text and f"HOMEVISION_CAMERA={CAM}\n" in text
    assert "S3cret" not in done.stdout + done.stderr + calls
    assert oct(env_file.stat().st_mode & 0o777) == "0o600"
    bad, _ = run_script(tmp_path, "home-camera", HOME_CAMERA_URL="rtsp://a b", HOME_CAMERA_ID=CAM)
    assert bad.returncode != 0 and "rtsp://a b" not in bad.stdout
    off, _ = run_script(tmp_path, "home-camera", HOME_CAMERA_URL="off")
    assert off.returncode == 0 and "HOMEVISION_RTSP_URL=\n" in env_file.read_text()
    ps = (HOME / "setup-windows.ps1").read_text()
    assert "[switch]$HomeCamera" in ps and "$pass = AskSecret 'The camera''s password" in ps


# ---- the cloud's half: live views, everyone's tallies, the coach part ---------------------------


def _report(**kw: Any) -> CoachReport:
    base: dict[str, Any] = {"id": "cr-1", "type": "coach", "at": F.WALL0, "camera": CAM,
                            "use": "posture", "session": "cs_0123456789ab", "track": 0, "who": "me",
                            "view": ({"kind": "big", "value": 3},), "tally": None}  # fmt: skip
    return CoachReport(**{**base, **kw})


def _live(**kw: Any) -> Any:
    from r8_fakes import KEY, NOON_IST

    from jarvis.coach.live import HomeLive
    from jarvis.coach.people import PeopleStore
    from jarvis.coach.store import CoachStore
    from jarvis.keyring import Keyring
    from jarvis.storage.docs import MemoryDocs

    docs, ring = MemoryDocs(), Keyring(KEY)
    t = {"now": F.WALL0}
    store = CoachStore(docs, ring, now=lambda: NOON_IST)
    people = PeopleStore(docs, ring, now=lambda: NOON_IST)
    live = HomeLive(store, people, clock=lambda: t["now"], **kw)
    return live, store, people, t


async def test_the_cloud_keeps_views_in_memory_and_everyones_tallies() -> None:
    live, store, people, t = _live()
    await live.handle("u1", _report())
    await live.handle("u1", _report(track=2, who="", view=({"kind": "tip", "text": "Sit back"},)))
    assert [b["track"] for b in live.live("u1", "posture")] == [0, 2]
    assert live.live("u2", "posture") == [] and live.live("u1", "seated") == []
    tally = F.posture_tally(int(F.WALL0), int(F.WALL0) + 60, 2)
    await live.handle("u1", _report(id="cr-2", tally=tally))
    await live.handle("u1", _report(id="cr-3", track=2, who="", tally=tally))
    await live.handle("u1", _report(id="cr-4", tally={**tally, "upright": 101}))  # doesn't fit
    water = {"started_at": 1, "ended_at": 2, "sips": 1, "glasses": 0}
    await live.handle("u1", _report(id="cr-5", use="water", tally=water))  # a webcam coach
    kept = await store.list("u1")
    whos = sorted(i["who"] for i in kept)
    assert len(kept) == 2 and whos[1] == "me" and whos[0].startswith("gst_")  # a guest (D6)
    assert [g.label for g in await people.guests("u1")] == ["Guest 1"]
    t["now"] += 121
    assert live.live("u1", "posture") == []  # memory only, and only while fresh


async def test_the_coach_part_goes_with_every_reply_and_a_push_with_a_newer_rev() -> None:
    from jarvis.coach.live import Wanted
    from jarvis.coach.target import TrackTarget
    from jarvis.home.ports import HomeOffline, HomeUnavailable

    calls: list[Any] = []

    class Caller:
        offline = False

        async def call(self, uid: str, method: str, path: str, body: Any = None, **kw: Any) -> Any:
            if self.offline:
                raise HomeOffline()
            calls.append((uid, method, path, body))
            return {"ok": True}

    caller = Caller()
    live, _, _, t = _live(caller=caller)
    assert await live.state_part("u1") == BridgeState()  # nothing switched on yet: no coach part
    await live.push("u1", uses={CAM: ["posture", "posture"]}, target=TrackTarget(), all_off=False)
    ((uid, method, path, body),) = calls
    assert (uid, method, path) == ("u1", "POST", "/bridge/v1/state")
    first = CoachState.model_validate(body["coach"])
    assert first.uses == {CAM: ("posture",)} and "arm" not in body  # never the alarm (D11)
    assert (await live.state_part("u1")).coach == first  # same content, same rev
    t["now"] += 0.001
    caller.offline = True
    await live.push("u1", uses={CAM: ["posture"]}, target=TrackTarget(), all_off=True)  # no raise
    off = (await live.state_part("u1")).coach
    assert off is not None and off.all_off and off.rev > first.rev
    await live.handle("u1", _report(tally=F.posture_tally(1, 2)))  # "cameras off": not kept
    assert live.live("u1", "posture") == []

    async def reader(uid: str) -> Wanted | None:
        return Wanted.of({CAM: ["seated"]}, TrackTarget(kind="person", person=ANA), False)

    after, _, _, _ = _live(reader=reader)  # a cloud restart: the switches are read again
    part = (await after.state_part("u1")).coach
    assert part is not None and part.uses == {CAM: ("seated",)} and part.person == ANA
    assert part.rev >= first.rev
    assert isinstance(HomeOffline(), HomeUnavailable)


def test_the_cloud_half_fits_the_ports() -> None:
    from jarvis.coach.live import HomeLive
    from jarvis.home.ports import HomeEventHandler

    live = HomeLive(None, None)
    assert isinstance(live, HomeEventHandler) and live.handles == frozenset({"coach"})
    assert asyncio.iscoroutinefunction(live.state_part) and asyncio.iscoroutinefunction(live.push)
