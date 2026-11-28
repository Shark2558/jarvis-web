# evals/r8/home.py
"""R8 eval, builder J (`home`, BUILT): the home camera's vision on the home laptop (docs/plans/
r8-vision.md v8.0.4 section 4.5a; the owner's D3, D4, D6, D11; ADR-49; row 216's home leg: "sends
only views and tallies; a CI test proves no frame, point or box leaves it"). Every case drives the
real runtime (`jarvis.coach.home.runtime.HomeRuntime`) on a synthetic RTSP source of synthetic
bodies (tests/r8_j_fakes.py), or the real pose adapter on a fake MediaPipe; nothing here is a real
person's data and no camera is needed (the camera arrives on 3 Dec 2026).

    no_geometry_leaves  two bodies and a phone for 40 looks, the stream dropping once, then
                        "cameras off": every report the cloud's parser takes, and none holds a
                        coordinate, a box value or a geometry key (the use cases did get them)
    leaks_refused       a use case that puts points in its view, a box in its tally or copies a
                        coordinate: each such report refused, the honest ones still sent
    one_body_at_a_time  two bodies: two tracks that follow them, a consented id for one, a guest
                        for the other; the target "me" and "person" feed only that body
    cameras_off         "cameras off" stops a waiting read at once, closes the stream and the
                        model, ends every session with its tally; an older push undoes nothing
    pacing              31 minutes at 1 a second: at most 20 views a minute, 2 s apart per body,
                        a posture tally at minutes 15 and 30; seated asks for 15 a second
    d4_model            the full model kept while the laptop keeps 15 frames a second, the lite
                        one otherwise; an unpinned or changed file never loaded
    not_medical         no view the runtime sends carries diagnosis or dose words (the S21 scan)

Negative control (`guard_off`): the runtime's three output checks replaced by pass-throughs
(`clean_view`, `clean_tally`, `needles`). `no_geometry_leaves` must then fail on the leaky use
case planted in it, and `leaks_refused` must fail, or this suite proves nothing.

    python evals/r8/home.py --mock
"""

from __future__ import annotations

import argparse
import asyncio
import functools
import hashlib
import re
import sys
import types
from collections.abc import Callable, Coroutine, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Literal

ROOT = Path(__file__).resolve().parents[2]
for extra in (ROOT / "src", ROOT / "tests", ROOT / "evals"):
    if str(extra) not in sys.path:
        sys.path.insert(0, str(extra))

import r8_j_fakes as F  # noqa: E402

from jarvis.coach.home import engines as E  # noqa: E402
from jarvis.coach.home import runtime as R  # noqa: E402
from jarvis.coach.words import medical_hits  # noqa: E402
from jarvis.home.ports import CoachState, parse_event  # noqa: E402

PART = "home"
BUILT = True
CAM = "desk_cam"
ANA = "fp_aaaaaaaaaaaa"
NUMBER = re.compile(r"-?\d+\.\d+")
WORDS = ("points", "box", '"x"', '"y"', "landmark", "image", "frame", "jpeg", "crop")


Target = Literal["all", "me", "person"]


def _world(scenes: list[Any], uses: tuple[str, ...] = ("posture",), *, leak: dict[str, str]
           | None = None, faces: Any = None, objects: Any = None, target: Target = "all",
           person: str | None = None, loop: bool = True, fps: float = 1.0) -> Any:  # fmt: skip
    clock = F.FakeClock()
    src = F.FakeSource(scenes, clock, fps=fps, loop=loop)
    pose = F.FakePose(src)
    sink = F.Sink()
    tasks = {"activity": ("pose", "objects"), "bp-posture": ("pose", "objects")}
    recs = {u: F.Recorder(u, tasks.get(u, ("pose",)), leak=(leak or {}).get(u, "")) for u in uses}
    rt = R.HomeRuntime(
        CAM, src, pose, sink, objects=objects, identifier=faces,
        registry={u: (lambda r=r: r) for u, r in recs.items()},
        wall=clock.wall, mono=clock.mono, idle_s=0.001, retry_s=0.001,
    )  # fmt: skip
    rt.apply(CoachState(rev=1, uses={CAM: uses}, target=target, person=person))
    return types.SimpleNamespace(rt=rt, src=src, pose=pose, sink=sink, recs=recs, clock=clock)


async def _steps(w: Any, n: int) -> None:
    for _ in range(n):
        await w.rt.step()


def _leaks(w: Any, scenes: list[Any]) -> list[str]:
    """What, in the reports sent, is a frame, a point or a box."""
    needles = F.coordinates(scenes) | set(F.BOX.values())
    found: list[str] = []
    for event in w.sink.events:
        text = event.model_dump_json(exclude_none=True)
        kind: str = parse_event(text.encode()).type
        if kind != "coach":
            found.append("not a coach event")
        found += [f"{event.use}: {k}" for k in WORDS if k in text]
        if {float(n) for n in NUMBER.findall(text)} & needles:
            found.append(f"{event.use}: a coordinate")
    return found


def _case(cid: str, failures: list[str]) -> dict[str, Any]:
    return {"id": f"{PART}:{cid}", "passed": not failures, "failures": failures}


async def _no_geometry_leaves() -> dict[str, Any]:
    scenes = [[F.body(0.3 + 0.002 * i, seed=3 + i), F.body(0.7, seed=60 + i)] for i in range(40)]
    w = _world(scenes, ("posture", "activity", "seated"), leak={"seated": "copy"},
               objects=F.FakeObjects("cell_phone"), loop=False)  # fmt: skip
    await _steps(w, 41)  # 40 looks, then the stream ends (retried)
    w.rt.apply(CoachState(rev=2, all_off=True))
    await _steps(w, 1)
    failures = _leaks(w, scenes)
    seen = [s for r in w.recs.values() for s in r.seen]
    if not any(s.points == 33 for s in seen) or not any(s.things for s in seen):
        failures.append("the use cases never got the points and things (the case proves nothing)")
    if not w.sink.tallies() or not [e for e in w.sink.events if e.use == "activity"]:
        failures.append("the honest use cases' reports did not go up")
    return _case("no_geometry_leaves", failures)


async def _leaks_refused() -> dict[str, Any]:
    failures: list[str] = []
    for leak in ("points", "box", "copy"):
        scenes = [[F.body(0.5, seed=5 + i)] for i in range(6)]
        w = _world(scenes, ("posture", "activity"), leak={"posture": leak})
        await _steps(w, 6)
        w.rt.apply(CoachState(rev=2, uses={}))
        await _steps(w, 1)
        failures += [f"{leak}: {x}" for x in _leaks(w, scenes)]
        if w.rt.refused < 1:
            failures.append(f"{leak}: nothing was refused")
        if not [e for e in w.sink.events if e.use == "activity" and e.tally is not None]:
            failures.append(f"{leak}: the honest use case's tally was lost")
    return _case("leaks_refused", failures)


async def _one_body_at_a_time() -> dict[str, Any]:
    failures: list[str] = []
    scenes = [[F.body(0.3 + 0.01 * i, seed=i), F.body(0.7 - 0.01 * i, seed=50 + i)]
              for i in range(8)]  # fmt: skip
    w = _world(scenes, faces=F.FakeFaces({0.3: ANA}), loop=False)
    await _steps(w, 8)
    seen = w.recs["posture"].seen
    tracks = {s.track for s in seen}
    whos = sorted(sorted({s.who for s in seen if s.track == t}) for t in tracks)
    if len(tracks) != 2 or whos != [[""], [ANA]]:
        failures.append(f"tracks {sorted(tracks)} and who {whos}: want two, one named, one guest")
    cases: tuple[tuple[Literal["me", "person"], str | None, set[str]], ...] = (
        ("me", None, {"me"}),
        ("person", ANA, {ANA}),
    )
    for target, person, want in cases:
        lone = [[F.body(0.5, seed=i)] for i in range(2)]
        three = [[F.body(0.5, seed=9 + i), F.body(0.2, seed=20 + i), F.body(0.85, seed=30 + i)]
                 for i in range(3)]  # fmt: skip
        t = _world(lone + three, faces=F.FakeFaces({0.85: ANA}), target=target, person=person,
                   loop=False)  # fmt: skip
        await _steps(t, 5)
        fed = {s.who for s in t.recs["posture"].seen}
        if fed != want:
            failures.append(f"target {target}: fed {sorted(fed)}")
    return _case("one_body_at_a_time", failures)


async def _cameras_off() -> dict[str, Any]:
    failures: list[str] = []
    w = _world([[F.body(0.5, seed=i)] for i in range(4)])
    await _steps(w, 3)
    w.rt.apply(CoachState(rev=2, uses={CAM: ("posture",)}, all_off=True))
    if not w.rt._stop.is_set():  # noqa: SLF001 - a waiting read returns within one frame
        failures.append("the waiting read was not told to stop")
    reads = w.src.reads
    await _steps(w, 2)
    if w.src.reads != reads or not w.src.closed or not w.pose.closed:
        failures.append("the stream or the model stayed open")
    if w.rt.part().running or len(w.sink.tallies()) != 1:
        failures.append("the session did not end with its tally")
    w.rt.apply(CoachState(rev=1, uses={CAM: ("posture",)}))
    await _steps(w, 1)
    if w.src.reads != reads:
        failures.append("an older push switched the camera back on")
    return _case("cameras_off", failures)


async def _pacing() -> dict[str, Any]:
    failures: list[str] = []
    w = _world([[F.body(0.5, seed=7)]], ("posture", "bp-posture"))
    await _steps(w, 31 * 60)
    per: dict[int, int] = {}
    for e in w.sink.views():
        minute = int((e.at - F.WALL0) // 60)
        per[minute] = per.get(minute, 0) + 1
    if max(per.values()) > R.VIEWS_PER_MIN:
        failures.append(f"{max(per.values())} views in a minute")
    posture = [e for e in w.sink.views() if e.use == "posture"]
    if min(b.at - a.at for a, b in zip(posture, posture[1:], strict=False)) < R.VIEW_EVERY_S:
        failures.append("a body's views closer than 2 s")
    if len([e for e in w.sink.tallies() if e.use == "posture"]) != 2:
        failures.append("the all-day posture coach did not keep a tally every 15 minutes")
    s = _world([[F.body(0.5)]], ("seated",), fps=15.0)
    await _steps(s, 16)
    if s.rt._rate() != 15.0:  # noqa: SLF001
        failures.append("the seated coach did not get 15 a second")
    return _case("pacing", failures)


async def _d4_model(tmp: Path) -> dict[str, Any]:
    failures: list[str] = []
    for per_frame, want in ((0.01, "full"), (0.2, "lite")):
        pins = {}
        for kind, pin in E.POSE_MODELS.items():
            data = f"eval {kind} {per_frame}".encode()
            (tmp / pin.name).write_bytes(data)
            pins[kind] = type(pin)(pin.name, hashlib.sha256(data).hexdigest(), len(data),
                                   pin.licence, pin.source)  # fmt: skip
        ticks = iter(i * per_frame for i in range(10_000))
        pose = E.MediaPipePose(
            tmp, load=_fake_mediapipe, pins=pins, clock=functools.partial(next, ticks)
        )
        if pose.status() != E.READY or pose.model != "full":
            failures.append("the full model was not tried first")
        for _ in range(E.BENCH_FRAMES + 1):
            pose.bodies(E.Frame(object(), F.WALL0, 1, 640, 360))
        if pose.model != want:
            failures.append(f"{1 / per_frame:.0f} frames a second kept {pose.model}, want {want}")
    (tmp / E.POSE_MODELS["full"].name).write_bytes(b"changed!")
    changed = E.MediaPipePose(tmp, load=_fake_mediapipe, pins=pins)
    if changed.status() != E.READY or changed.model != "lite":
        failures.append("a changed full model file was loaded (or the good lite one was not)")
    if E.MediaPipePose(tmp, load=_never).status() != E.NOT_PINNED:
        failures.append("a model with no pin was loaded")
    return _case("d4_model", failures)


def _never() -> Any:
    raise AssertionError("a model that isn't the pinned one was loaded")


def _fake_mediapipe() -> Any:
    pts = [types.SimpleNamespace(x=0.5, y=0.5, z=0.0, visibility=0.9)] * 33
    task = types.SimpleNamespace(
        detect_for_video=lambda image, stamp: types.SimpleNamespace(pose_landmarks=[pts]),
        close=lambda: None,
    )
    vision = types.SimpleNamespace(
        PoseLandmarkerOptions=lambda **kw: types.SimpleNamespace(**kw),
        RunningMode=types.SimpleNamespace(VIDEO="VIDEO"),
        PoseLandmarker=types.SimpleNamespace(create_from_options=lambda opts: task),
    )
    mp = types.SimpleNamespace(Image=lambda **kw: kw, ImageFormat=types.SimpleNamespace(SRGB=1))
    return types.SimpleNamespace(mp=mp, vision=vision,
                                 BaseOptions=lambda **kw: types.SimpleNamespace(**kw))  # fmt: skip


async def _not_medical() -> dict[str, Any]:
    w = _world([[F.body(0.5, seed=i)] for i in range(8)], ("posture", "seated"))
    await _steps(w, 8)
    words = [str(v) for e in w.sink.events for widget in e.view for v in widget.values()]
    hits = [f"{t}: {h}" for t in words if (h := medical_hits(t))]
    return _case("not_medical", hits)


async def _all() -> list[dict[str, Any]]:
    import tempfile

    out = [await c() for c in (_no_geometry_leaves, _leaks_refused, _one_body_at_a_time,
                               _cameras_off, _pacing, _not_medical)]  # fmt: skip
    with tempfile.TemporaryDirectory() as tmp:
        out.append(await _d4_model(Path(tmp)))
    return out


async def cases() -> list[dict[str, Any]]:
    return await _all()


@contextmanager
def _guard_off() -> Iterator[None]:
    saved = (R.clean_view, R.clean_tally, R.needles)
    R.clean_view = lambda raw: tuple(dict(w) for w in raw or ())
    R.clean_tally = lambda use, raw: raw
    R.needles = lambda *a: frozenset()
    try:
        yield
    finally:
        R.clean_view, R.clean_tally, R.needles = saved


async def control() -> dict[str, Any]:
    with _guard_off():
        results = await _all()
    failed = [r["id"] for r in results if not r["passed"]]
    must = {f"{PART}:no_geometry_leaves", f"{PART}:leaks_refused"}
    return {"name": "guard_off", "suite_failed": must <= set(failed), "failed_cases": failed}


def _run(fn: Callable[[], Coroutine[Any, Any, Any]]) -> Any:
    return asyncio.run(fn())


def main() -> int:
    from r1d_common import finish

    ap = argparse.ArgumentParser()
    ap.add_argument("--mock", action="store_true", help="the only mode (CI)")
    ap.parse_args()
    return int(finish(Path(__file__).parent, "r8 home", _run(cases), _run(control)))


if __name__ == "__main__":
    sys.exit(main())
