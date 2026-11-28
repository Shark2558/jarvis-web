# tests/fixtures/r8/desk_home.py -- R8 builder D (docs/plans/r8-vision.md v8.0.4 sections 2.1, 8):
# synthetic side-on bodies for the home camera's desk rules (jarvis.coach.home.seated, bp_posture),
# for tests/test_r8_d_coaches.py and evals/r8/coaches.py. Never a real person's data: each body is
# the pose model's 33 points made from a few joint angles, seen from the side (facing +x), with
# noise. Loaded by path (`load()`), so it needs no package. Standard library only.
#
#   seated_body(**pose)                  33 points {x, y, z, visibility} for one frame
#   seated_session(move, sets, ...)      a seated exercise session as home Results, and its truth
#   bp_body(**faults)                    a body before a blood-pressure reading, with chosen faults
#   bp_frames(seconds, faults, ...)      home Results (pose and objects) at 2 a second
from __future__ import annotations

import math
import random
from collections.abc import Iterator, Mapping, Sequence
from typing import Any

BASE_AT = 1764300000
T = 0.25  # the torso's length, frame units


def _at(o: tuple[float, float], length: float, deg: float) -> tuple[float, float]:
    """`length` from `o` at `deg` degrees from straight down, turning towards +x (forward)."""
    r = math.radians(deg)
    return (o[0] + length * math.sin(r), o[1] + length * math.cos(r))


def seated_body(
    *,
    lean: float = 0.0,  # the torso's lean forward from upright, degrees
    shrug: float = 0.0,  # the shoulders lifted, a share of the torso
    twist: float = 0.0,  # the upper body turned, degrees
    arm: float = 10.0,  # the shoulder's raise, degrees from hanging (both arms)
    elbow: float = 0.0,  # the elbow's bend, degrees
    thigh: float = 0.0,  # the near thigh's rise above level, degrees
    thigh_far: float | None = None,
    knee: float = 90.0,  # the angle at the knee (90: the shin straight down from a level thigh)
    toes: float = 0.0,  # the foot's tilt, toes up positive, degrees
    turn: float = 0.0,  # the head turned, degrees
    far_knee_up: float = 0.0,  # the far leg crossed over: its knee this share of the torso higher
    far_ankle_up: float = 0.0,
    cx: float = 0.45,
    cy: float = 0.6,
    noise: float = 0.0,
    rng: random.Random | None = None,
) -> list[dict[str, float]]:
    r = rng or random.Random(1)
    hip = (cx, cy)
    up = 180.0 - lean  # straight up, leaning forward
    sh = _at(hip, T, up)
    sh = (sh[0], sh[1] - shrug * T)
    spread = 0.4 * T * math.sin(math.radians(twist))
    near_sh, far_sh = (sh[0] + spread, sh[1]), (sh[0] - spread, sh[1])
    head = _at(sh, 0.33 * T, up)
    nose = (head[0] + 0.2 * T * math.cos(math.radians(turn)), head[1] + 0.01 * T)
    ear = (head[0] - 0.03 * T, head[1] - 0.01 * T)
    elb = _at(near_sh, 0.65 * T, arm)
    wri = _at(elb, 0.55 * T, arm + elbow)

    def leg(rise: float, lift_k: float, lift_a: float) -> list[tuple[float, float]]:
        kn = (
            hip[0] + 0.95 * T * math.cos(math.radians(rise)),
            hip[1] - 0.95 * T * math.sin(math.radians(rise)),
        )
        shin = rise + (knee - 90.0)  # degrees from straight down, forward positive
        an = _at(kn, 0.9 * T, shin)
        kn = (kn[0], kn[1] - lift_k * T)
        an = (an[0], an[1] - lift_a * T)
        foot = math.radians(toes + shin)  # the foot's rise above level (the ankle keeps its angle)
        heel = (an[0] - 0.06 * T, an[1] + 0.03 * T)
        toe = (an[0] + 0.38 * T * math.cos(foot), an[1] - 0.38 * T * math.sin(foot))
        return [kn, an, heel, toe]

    near_leg = leg(thigh, 0.0, 0.0)
    far_leg = leg(thigh if thigh_far is None else thigh_far, far_knee_up, far_ankle_up)
    pts: list[tuple[float, float] | None] = [None] * 33
    pts[0] = nose
    for i in (1, 2, 3, 4, 5, 6):
        pts[i] = (nose[0] - 0.03 * T, nose[1] - 0.04 * T)
    pts[7], pts[8] = ear, (ear[0] + 0.005, ear[1])
    pts[9], pts[10] = (nose[0] - 0.01, nose[1] + 0.04 * T), (nose[0] - 0.01, nose[1] + 0.04 * T)
    pts[11], pts[12] = near_sh, far_sh
    pts[13], pts[14] = elb, (elb[0] - 0.005, elb[1])
    pts[15], pts[16] = wri, (wri[0] - 0.005, wri[1])
    for i in (17, 19, 21):
        pts[i] = wri
    for i in (18, 20, 22):
        pts[i] = (wri[0] - 0.005, wri[1])
    pts[23], pts[24] = hip, (hip[0] - 0.005, hip[1])
    for k, (a, b) in enumerate(((25, 26), (27, 28), (29, 30), (31, 32))):
        pts[a], pts[b] = near_leg[k], (far_leg[k][0] - 0.005, far_leg[k][1])

    def jitter() -> float:
        return (r.random() - 0.5) * 2 * noise

    out = []
    for i, p in enumerate(pts):
        assert p is not None
        vis = 0.95 if i % 2 or i == 0 else 0.65  # the near (left: odd) side is seen better
        out.append({"x": p[0] + jitter(), "y": p[1] + jitter(), "z": 0.0, "visibility": vis})
    return out


def result(task: str, data: Mapping[str, Any], t: float) -> dict[str, Any]:
    return {
        "task": task,
        "data": dict(data),
        "at": BASE_AT + int(t),
        "t": t,
        "track": 0,
        "who": "me",
    }


# each move: the pose key it swings, its rest value and its far end (one rep: rest -> end -> rest)
SWINGS: Mapping[str, tuple[str, float, float]] = {
    "arm_raise": ("arm", 10.0, 150.0),
    "shoulder_roll": ("shrug", 0.0, 0.12),
    "torso_twist": ("twist", 0.0, 35.0),
    "knee_lift": ("thigh", 0.0, 30.0),
    "ankle_pump": ("toes", -10.0, 25.0),
    "neck_turn": ("turn", 0.0, 70.0),
}


def seated_session(
    move: str,
    sets: Sequence[int],
    *,
    period: float = 2.5,
    slow_down: Sequence[float] = (),
    rest_s: float = 8.0,
    fps: float = 15.0,
    noise: float = 0.002,
    seed: int = 3,
) -> Iterator[dict[str, Any]]:
    """`sets` reps per set of `move`, with `rest_s` still between sets; set k's reps slow by
    `slow_down[k]` (the last rep that much longer than the first, evenly) -- a hard set."""
    key, rest, end = SWINGS[move]
    rng = random.Random(seed)
    plan: list[tuple[float, float]] = []  # (start, length) of every rep
    t = 2.0
    for k, n in enumerate(sets):
        slow = slow_down[k] if k < len(slow_down) else 0.0
        for i in range(n):
            length = period * (1 + slow * (i / max(1, n - 1)))
            plan.append((t, length))
            t += length
        t += rest_s
    total = t + 2.0
    for i in range(int(total * fps) + 1):
        now = i / fps
        value = rest
        for start, length in plan:
            if start <= now < start + length:
                value = (
                    rest + (end - rest) * (1 - math.cos(2 * math.pi * (now - start) / length)) / 2
                )
                break
        pts = seated_body(**{key: value}, noise=noise, rng=rng)
        yield result("pose", {"points": pts}, now)


# ---- the blood-pressure checklist ---------------------------------------------------------------
FAULTS = ("lean", "feet", "crossed", "arm_low", "arm_hang", "moving")


def bp_body(
    faults: Sequence[str] = (),
    *,
    noise: float = 0.002,
    rng: random.Random | None = None,
    sway: float = 0.0,
    vary: random.Random | None = None,
) -> list[dict[str, float]]:
    """A body sat for a reading: back upright, feet flat, legs apart, the cuff arm resting on the
    table at heart level; each fault breaks one of those. `vary` moves every angle a little (a
    different person, a different chair) and the body about the picture."""
    v = vary or random.Random(0)
    k = 1.0 if vary is not None else 0.0

    def jig(span: float) -> float:
        return k * (v.random() - 0.5) * 2 * span

    pose: dict[str, Any] = {
        "lean": -5.0 + jig(6),
        "arm": 40.0 + jig(6),
        "elbow": 50.0 + jig(6),
        "thigh": jig(5),
        "knee": 90.0 + jig(8),
        "toes": jig(6),
        "cx": 0.45 + jig(0.08),
        "cy": 0.6 + jig(0.05),
    }
    if "lean" in faults:
        pose["lean"] = 28.0  # hunched forward, off the chair's back (varied below)
    if "feet" in faults:
        pose["knee"], pose["toes"] = 55.0, 0.0  # feet tucked back under the chair, on tiptoe
    if "crossed" in faults:
        pose.update(far_knee_up=0.22, far_ankle_up=0.5, thigh_far=18.0)
    if "arm_low" in faults:
        pose["arm"], pose["elbow"] = 10.0, 80.0  # the forearm on the lap: the cuff below the heart
    if "arm_hang" in faults:
        pose["arm"], pose["elbow"] = 5.0, 0.0  # the arm hanging by the side
    if "lean" in faults:
        pose["lean"] = 26.0 + jig(8)
    if sway:
        pose["cx"] = pose["cx"] + sway
    return seated_body(**pose, noise=noise, rng=rng)


TABLE = {"label": "dining_table", "score": 0.8, "box": {"x": 0.5, "y": 0.5, "w": 0.45, "h": 0.4}}
CHAIR = {"label": "chair", "score": 0.7, "box": {"x": 0.33, "y": 0.4, "w": 0.2, "h": 0.5}}


def bp_frames(
    seconds: float,
    faults: Sequence[str] = (),
    *,
    fps: float = 2.0,
    noise: float = 0.002,
    seed: int = 5,
    moving_until: float = 0.0,
    stand_at: float | None = None,
) -> Iterator[dict[str, Any]]:
    """Pose and objects Results at `fps`; "moving" in faults (or before `moving_until`) shifts him
    about; `stand_at` makes him stand up (he leaves the chair) at that second."""
    rng = random.Random(seed)
    for i in range(int(seconds * fps) + 1):
        t = i / fps
        moving = "moving" in faults or t < moving_until
        sway = 0.04 * math.sin(2.1 * t) if moving else 0.0
        if stand_at is not None and t >= stand_at:
            pts = seated_body(thigh=-60.0, knee=150.0, arm=5.0, noise=noise, rng=rng)
        else:
            pts = bp_body([f for f in faults if f != "moving"], noise=noise, rng=rng, sway=sway)
        yield result("pose", {"points": pts}, t)
        yield result("objects", {"objects": [TABLE, CHAIR]}, t + 0.01)


def load() -> Any:
    """This module (for callers that load it by path)."""
    import sys

    return sys.modules[__name__]
