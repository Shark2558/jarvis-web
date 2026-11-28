# tests/r8_j_fakes.py -- R8 builder J (docs/plans/r8-vision.md v8.0.4 4.5a): fakes for the home
# camera's vision on the laptop. A synthetic RTSP source (scripted scenes of synthetic bodies, the
# Python twin of tests/fixtures/r8/poses.mjs `body()`), a fake pose engine and object detector, a
# fake face library, scripted home use cases (honest and leaky) and a recording event sink. A fake
# clock drives the frames, so a 20-minute session runs in a moment. Never a real person's data.
from __future__ import annotations

import math
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from jarvis.coach.home.engines import READY, Frame, SourceDown
from jarvis.home.ports import CoachReport

WALL0 = 1_764_300_000.0  # 28 Nov 2025-ish: any fixed epoch
RAD = math.pi / 180
SECRET_URL = "rtsp://admin:S3cretCode@192.168.1.50:554/cam/realmonitor?channel=1&subtype=1"


def _rng(seed: int) -> Callable[[], float]:
    s = (seed & 0xFFFFFFFF) or 1

    def nxt() -> float:
        nonlocal s
        s = (s * 1664525 + 1013904223) & 0xFFFFFFFF
        return s / 4294967296

    return nxt


def body(
    cx: float = 0.5,
    cy: float = 0.55,
    *,
    scale: float = 0.35,
    torso: float = 0.0,
    neck: float = 0.0,
    seed: int = 7,
    noise: float = 0.004,
    visibility: float = 0.95,
) -> list[dict[str, float]]:
    """33 pose points from a few angles (degrees, 180 straight), as poses.mjs builds them. The
    noise gives every coordinate many decimals, so a copied one can be found in a report."""
    r = _rng(seed)

    def n() -> float:
        return (r() - 0.5) * 2 * noise

    def at(o: tuple[float, float], length: float, deg: float) -> tuple[float, float]:
        return (o[0] + length * math.sin(deg * RAD), o[1] + length * math.cos(deg * RAD))

    k = scale
    hip = (cx, cy)
    up = 180 + torso
    shoulder = at(hip, 0.5 * k, up)
    head = at(shoulder, 0.18 * k, up + neck)
    knee = at(hip, 0.45 * k, 90 + torso)
    ankle = at(knee, 0.45 * k, 0)
    elbow = at(shoulder, 0.3 * k, 10)
    wrist = at(elbow, 0.28 * k, 10)
    where = [head] * 11 + [shoulder] * 2 + [elbow] * 2 + [wrist] * 8 + [hip] * 2
    where += [knee] * 2 + [ankle] * 6
    return [{"x": x + n(), "y": y + n(), "z": 0.0, "visibility": visibility} for x, y in where]


def coordinates(scenes: Sequence[Sequence[Sequence[Mapping[str, float]]]]) -> set[float]:
    """Every x and y of every body of every scene."""
    return {p[k] for scene in scenes for b in scene for p in b for k in ("x", "y")}


@dataclass
class FakeClock:
    t: float = 0.0

    def mono(self) -> float:
        return self.t

    def wall(self) -> float:
        return WALL0 + self.t


@dataclass(frozen=True)
class FakeImage:
    """Stands for a decoded picture: a scene number, nothing else."""

    index: int
    shape: tuple[int, int, int] = (360, 640, 3)


class FakeSource:
    """A synthetic RTSP sub-stream: one scene (the bodies in view) a frame, at `fps`."""

    def __init__(self, scenes: Sequence[Sequence[list[dict[str, float]]]], clock: FakeClock,
                 *, fps: float = 15.0, loop: bool = False) -> None:  # fmt: skip
        self.scenes = list(scenes)
        self.clock = clock
        self.fps = fps
        self.loop = loop
        self.index = 0
        self.opened = 0
        self.closed = 0
        self.reads = 0
        self.down: str | None = None

    def open(self) -> None:
        if self.down:
            raise SourceDown(self.down)
        self.opened += 1

    def read(self, until: float, stop: Any) -> Frame | None:
        if stop.is_set():
            return None
        if self.down:
            raise SourceDown(self.down)
        if self.index >= len(self.scenes):
            if not self.loop:
                raise SourceDown("ended")
            self.index = 0
        self.clock.t = max(self.clock.t + 1.0 / self.fps, until)
        self.reads += 1
        frame = Frame(FakeImage(self.index), self.clock.wall(), int(self.clock.t * 1000), 640, 360)
        self.index += 1
        return frame

    def close(self) -> None:
        self.closed += 1


class FakePose:
    def __init__(self, source: FakeSource, *, model: str = "lite", ready: str = READY,
                 ms: float = 0.0) -> None:  # fmt: skip
        self.source = source
        self.model: Any = None
        self._kind = model
        self._ready = ready
        self.closed = 0
        self.ms = ms

    def status(self) -> str:
        if self._ready == READY:
            self.model = self._kind
        return self._ready

    def bodies(self, frame: Frame) -> list[list[dict[str, float]]]:
        return [list(b) for b in self.source.scenes[frame.image.index]]

    def close(self) -> None:
        self.closed += 1
        self.model = None


BOX = {"x": 0.412345678, "y": 0.523456789, "w": 0.101234567, "h": 0.134567891}


class FakeObjects:
    def __init__(self, label: str = "cup") -> None:
        self.label = label
        self.closed = 0

    def status(self) -> str:
        return READY

    def objects(self, frame: Frame) -> list[dict[str, Any]]:
        return [{"label": self.label, "score": 0.9, "box": dict(BOX)}]

    def close(self) -> None:
        self.closed += 1


class FakeFaces:
    """Names a body by where its head is: {head x: fp id}."""

    def __init__(self, by_x: Mapping[float, str]) -> None:
        self.by_x = dict(by_x)
        self.calls = 0

    def status(self) -> str:
        return READY

    def who(self, frame: Frame, points: Sequence[Mapping[str, float]]) -> str:
        self.calls += 1
        x = points[0]["x"]
        for cx, person in self.by_x.items():
            if abs(x - cx) < 0.06:
                return person
        return ""


@dataclass
class Seen:
    use: str
    track: Any
    who: str
    task: str
    points: int
    things: int


def posture_tally(started: int, ended: int, spans: int = 0) -> dict[str, Any]:
    return {"started_at": started, "ended_at": ended, "slouch_spans": spans,
            "slouch_seconds": 0.0, "nudges": 0, "upright": 100}  # fmt: skip


def activity_tally(started: int, ended: int) -> dict[str, Any]:
    return {"started_at": started, "ended_at": ended,
            "segments": [{"kind": "desk", "start": started, "end": ended}]}  # fmt: skip


def seated_tally(started: int, ended: int, reps: int) -> dict[str, Any]:
    return {"started_at": started, "ended_at": ended, "move": "arm_raise", "sets": 1,
            "reps": reps, "target": 10, "finished": reps >= 10}  # fmt: skip


TALLY_OF: dict[str, Callable[[int, int, int], dict[str, Any]]] = {
    "posture": lambda a, b, n: posture_tally(a, b, n % 500),
    "activity": lambda a, b, n: activity_tally(a, b),
    "seated": lambda a, b, n: seated_tally(a, b, n % 500),
    "bp-posture": lambda a, b, n: {
        "started_at": a,
        "ended_at": b,
        "back": True,
        "feet": True,
        "legs": True,
        "arm": True,
        "rested": n > 3,
        "still": True,
        "score": min(100, n),
    },  # fmt: skip
}


@dataclass
class Recorder:
    """An honest home use case: counts the looks of its body, shows the count, keeps a tally."""

    id: str
    tasks: tuple[str, ...] = ("pose",)
    seen: list[Seen] = field(default_factory=list)
    leak: str = ""  # "", "points", "box", "copy", "bad_tally", "raises"
    hint: float | None = None
    kept_calls: int = 0

    def on_result(self, result: Mapping[str, Any], state: Any) -> Any:
        if self.leak == "raises":
            raise RuntimeError("a broken rule")
        st = dict(state or {"n": 0, "first": int(result["at"]), "x": 0.0, "things": 0})
        data = result["data"]
        pts = data.get("points") or []
        things = data.get("objects") or []
        self.seen.append(Seen(self.id, result.get("track"), str(result.get("who", "")),
                              str(result["task"]), len(pts), len(things)))  # fmt: skip
        if result["task"] == "pose":
            st["n"] += 1
            st["x"] = pts[0]["x"] if pts else 0.0
        else:
            st["things"] += len(things)
        st["last"] = int(result["at"])
        return st

    def summary(self, state: Any) -> dict[str, Any]:
        st = state or {"n": 0, "first": 0, "last": 0, "x": 0.0}
        view: list[dict[str, Any]] = [{"kind": "big", "value": st["n"], "word": "looks"}]
        tally: dict[str, Any] | None = TALLY_OF[self.id](st["first"], st.get("last", st["first"]),
                                                         st["n"])  # fmt: skip
        if self.leak == "points":
            view.append({"kind": "line", "text": "hi", "points": [{"x": st["x"], "y": 0.5}]})
        elif self.leak == "box":
            assert tally is not None
            tally = {**tally, "box": dict(BOX)}
        elif self.leak == "copy":
            view.append({"kind": "big", "value": st["x"], "word": "x"})
        elif self.leak == "bad_tally":
            assert tally is not None
            tally = {**tally, "upright": 9000}
        return {"view": view, "tally": tally}

    def wanted_rate(self, state: Any) -> float | None:  # R8 I1: the hook's one name (C's)
        return self.hint

    def kept(self, state: Any) -> Any:
        self.kept_calls += 1
        st = dict(state or {})
        st["first"] = st.get("last", st.get("first", 0))
        return st


class Sink:
    def __init__(self, ok: bool = True) -> None:
        self.events: list[CoachReport] = []
        self.ok = ok

    async def __call__(self, event: CoachReport) -> bool:
        self.events.append(event)
        return self.ok

    post_event = __call__  # the bridge's EventSink

    def views(self) -> list[CoachReport]:
        return [e for e in self.events if e.tally is None]

    def tallies(self) -> list[CoachReport]:
        return [e for e in self.events if e.tally is not None]


__all__ = [
    "BOX",
    "SECRET_URL",
    "WALL0",
    "FakeClock",
    "FakeFaces",
    "FakeImage",
    "FakeObjects",
    "FakePose",
    "FakeSource",
    "Recorder",
    "Seen",
    "Sink",
    "body",
    "coordinates",
]
