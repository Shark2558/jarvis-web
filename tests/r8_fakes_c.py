# tests/r8_fakes_c.py -- R8 builder C (docs/plans/r8-vision.md 4.7, rows 181 and 182): synthetic
# desk bodies and desk days for the home camera's posture and activity rules. A Python twin of
# tests/fixtures/r8/poses.mjs `body()` (the same 33 MediaPipe points from a few joint angles, the
# same layout), so the home rules (Python, on the home laptop) and the console's coaches read one
# synthetic person. Never a real person's data; nothing here is a picture.
#
#   body({torso, neck, ...}, cx=, cy=, scale=, noise=, seed=, visibility=)  -> 33 points
#   pose_result(points, at, track=0, who="me")   one body's Result, as the driver hands it on
#   objects_result(things, at)                   an objects Result: [(label, (x, y, w, h)), ...]
#   desk_day(blocks, start, fps=1, seed=7)       a scripted day: (kind, seconds) blocks ->
#                                                (results, truth): truth = one label a second
from __future__ import annotations

import math
import random
from collections.abc import Iterator, Sequence
from typing import Any

RAD = math.pi / 180
UPRIGHT = {"torso": 3.0, "neck": 6.0}
SLOUCH = {"torso": 24.0, "neck": 34.0}  # leaning towards the screen, head forward
FORWARD_HEAD = {"torso": 4.0, "neck": 30.0}  # the back upright, the head pushed forward
PHONE = {"torso": 8.0, "neck": 28.0, "elbow": 60.0, "shoulder": 40.0}  # looking down at a phone
EATING = {"torso": 10.0, "neck": 14.0, "elbow": 30.0, "shoulder": 20.0}  # the hand near the mouth
SEATED = {"hip": 90.0, "knee": 90.0}  # sitting: thighs forward, shins down
START = 1_795_000_000  # a fixed unix second (Nov 2026); the clock of every synthetic day


def _at(o: tuple[float, float], length: float, deg: float) -> tuple[float, float]:
    return o[0] + length * math.sin(deg * RAD), o[1] + length * math.cos(deg * RAD)


def body(
    angles: dict[str, float] | None = None,
    *,
    cx: float = 0.5,
    cy: float = 0.55,
    scale: float = 0.35,
    noise: float = 0.0,
    seed: int = 7,
    visibility: float = 0.95,
) -> list[dict[str, float]]:
    """33 points (x, y, z, visibility) from joint angles; poses.mjs `body()` in Python."""
    a = {"hip": 180.0, "knee": 180.0, "elbow": 180.0, "shoulder": 10.0, "torso": 0.0, "neck": 0.0}
    a.update(angles or {})
    rnd = random.Random(seed)

    def n() -> float:
        return (rnd.random() - 0.5) * 2 * noise

    k = scale
    hip = (cx, cy)
    torso_up = 180 + a["torso"]
    shoulder = _at(hip, 0.5 * k, torso_up)
    head = _at(shoulder, 0.18 * k, torso_up + a["neck"])
    thigh = 180 - a["hip"] + a["torso"]
    knee = _at(hip, 0.45 * k, thigh)
    ankle = _at(knee, 0.45 * k, thigh + (180 - a["knee"]))
    elbow = _at(shoulder, 0.3 * k, a["shoulder"])
    wrist = _at(elbow, 0.28 * k, a["shoulder"] + (180 - a["elbow"]))
    pts: list[tuple[float, float]] = [head] * 33
    for ids, p in (
        (range(0, 11), head),
        ((11, 12), shoulder),
        ((13, 14), elbow),
        (range(15, 23), wrist),
        ((23, 24), hip),
        ((25, 26), knee),
        (range(27, 33), ankle),
    ):
        for i in ids:
            pts[i] = p
    return [{"x": p[0] + n(), "y": p[1] + n(), "z": 0.0, "visibility": visibility} for p in pts]


def pose_result(
    points: Sequence[dict[str, float]], at: float, *, track: int = 0, who: str = "me"
) -> dict[str, Any]:
    """One body's pose Result, the way the driver hands it to a use case (console-vision.js)."""
    return {
        "task": "pose",
        "v": 2,
        "at": int(at),
        "ms": 40,
        "device": "home",
        "ok": True,
        "data": {"points": list(points)},
        "quality": {"light": 0.8, "sharp": 0.8},
        "track": track,
        "who": who,
    }


def objects_result(
    things: Sequence[tuple[str, tuple[float, float, float, float]]], at: float
) -> dict[str, Any]:
    return {
        "task": "objects",
        "v": 1,
        "at": int(at),
        "ms": 30,
        "device": "home",
        "ok": True,
        "data": {
            "objects": [
                {"label": lab, "score": 0.8, "box": {"x": b[0], "y": b[1], "w": b[2], "h": b[3]}}
                for lab, b in things
            ]
        },
        "quality": {"light": 0.8, "sharp": 0.8},
    }


Box = tuple[float, float, float, float]


def _near(p: dict[str, float], w: float = 0.06, h: float = 0.05) -> Box:
    return (max(0.0, p["x"] - w / 2), max(0.0, p["y"] - h / 2), w, h)


def frames(
    blocks: Sequence[tuple[str, float]], *, start: float = START, fps: float = 1.0, seed: int = 7,
    noise: float = 0.004,
) -> Iterator[tuple[float, str, list[dict[str, Any]]]]:  # fmt: skip
    """(t, truth, results) for each frame of the scripted blocks. Kinds: upright, slouch,
    forward, lean (a short lean, still upright in truth), desk (= upright), phone, eating, away,
    hidden (in view but too dark to judge)."""
    rnd = random.Random(seed)
    t = float(start)
    step = 1.0 / fps
    i = 0
    for kind, seconds in blocks:
        end = t + seconds
        while t < end - 1e-9:
            i += 1
            jitter = {k: (rnd.random() - 0.5) * 4 for k in ("torso", "neck")}
            results: list[dict[str, Any]] = []
            if kind == "away":
                results.append(objects_result([], t))
            else:
                angles = {
                    "upright": UPRIGHT, "desk": UPRIGHT, "slouch": SLOUCH,
                    "forward": FORWARD_HEAD, "phone": PHONE, "eating": EATING,
                    "lean": {"torso": 22.0, "neck": 20.0}, "hidden": UPRIGHT,
                }[kind]  # fmt: skip
                a = {**SEATED, **angles}
                a = {k: v + jitter.get(k, 0.0) for k, v in a.items()}
                vis = 0.2 if kind == "hidden" else 0.95
                pts = body(a, noise=noise, seed=seed + i, visibility=vis)
                things: list[tuple[str, tuple[float, float, float, float]]] = []
                if kind == "phone":
                    things.append(("cell_phone", _near(pts[15])))
                if kind == "eating":
                    things.append(("bowl", (0.55, 0.62, 0.12, 0.06)))
                    things.append(("spoon", _near(pts[15], 0.03, 0.03)))
                if kind in ("upright", "desk") and i % 600 < 30:
                    things.append(("cup", (0.62, 0.6, 0.05, 0.07)))  # a cup on the desk at times
                results.append(pose_result(pts, t))
                results.append(objects_result(things, t))
            truth = {"upright": "desk", "slouch": "desk", "forward": "desk", "lean": "desk",
                     "hidden": "desk"}.get(kind, kind)  # fmt: skip
            yield t, truth, results
            t += step


__all__ = [
    "EATING",
    "FORWARD_HEAD",
    "PHONE",
    "SEATED",
    "SLOUCH",
    "START",
    "UPRIGHT",
    "body",
    "frames",
    "objects_result",
    "pose_result",
]
