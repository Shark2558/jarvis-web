# src/jarvis/coach/home/seated.py
"""R8 builder D, row 227 (docs/plans/r8-vision.md v8.0.4 section 2.1, the owner's D3): the adaptive
seated movement coach, a home rule run on the home laptop by the home vision plugin (J's runtime)
on the home camera's pose, one body at a time. Kit-safe: the standard library only.

The home camera sees him side-on at the desk (owner step 4a). Six seated moves, each watched on one
number from the body's points (the side nearer the camera, the one it sees better):

| move          | the number                                              | a rep                |
|---------------|---------------------------------------------------------|----------------------|
| arm_raise     | the angle at the shoulder, hip to wrist (degrees)       | up and back down     |
| shoulder_roll | the shoulders' height over the hips, of the torso       | a lift and back      |
| torso_twist   | the two shoulders' spread across the picture, of torso  | a turn and back      |
| knee_lift     | the thigh's rise above level (degrees)                  | up and back down     |
| ankle_pump    | the angle at the ankle, knee to toe (degrees)           | toes up and down     |
| neck_turn     | the nose's lead over the ears, of the torso             | a turn and back      |

Each number is smoothed a little (`SMOOTH`, against the camera's jitter); its middle is the midpoint
of its range over the last `WINDOW_S`; a rep is one swing past
`+swing` and back past `-swing` around it, so a rep counts the same from any starting place. The
move he is doing is the one whose range, against its own `full` range, is the largest (at least
`ACTIVE`); only its reps count, so the small sway the other numbers show never adds a rep.

Sets adapt (the row's check): a set ends when no rep comes for `REST_S` (or he changes move); it is
finished when it reached
its target (it starts at `TARGET0`). After an unfinished set the move's next target is `STEP`
fewer (never below `TARGET_MIN`); a finished set is easy when its last reps were no slower than its
first (`EASY_SLOWER`); after two easy sets in a row the target is `STEP` more (at most
`TARGET_MAX`). Its tally is `jarvis.coach.usecases`' SeatedTally (the move, its sets, its reps,
the next target, whether the last set was finished); its view holds the fixed widgets with plain
scalars only (`jarvis.home.ports.CoachReport`). Never a point, a picture or a box.

A Result here is the home runtime's: {"task": "pose", "data": {"points": 33 x {x, y, z,
visibility}}, "at": unix seconds, "t": seconds (optional, finer), "track", "who"}.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from typing import Any

from jarvis.coach.home import Summary, aspect_of

USE = "seated"
TASKS: tuple[str, ...] = ("pose",)
WINDOW_S = 8.0
ACTIVE = 0.5  # a move is being done once its range is this share of its full range
IDLE = 0.3  # and is not, below this share
REST_S = 8.0  # no rep for this long: the set is over
TORSO_SLOW = 0.002  # the torso length (the numbers' scale) follows him over about half a minute
SMOOTH = 0.35  # each number's smoothing weight a frame (at up to 15 a second)
TARGET0 = 10
TARGET_MIN = 4
TARGET_MAX = 20
STEP = 2
EASY_SLOWER = 1.25  # the last three reps' pace may be this much slower than the first three's
VIS_MIN = 0.5
STOP = "Stop if anything hurts."
PRACTICE = "Practice only, not medical advice."
WORDS: Mapping[str, str] = {
    "arm_raise": "Raise both arms in front of you, then lower them.",
    "shoulder_roll": "Lift your shoulders up and back, then let them drop.",
    "torso_twist": "Sit tall and turn your upper body to one side, then back.",
    "knee_lift": "Lift one knee a little, then put the foot down.",
    "ankle_pump": "Point your toes up, then down.",
    "neck_turn": "Turn your head slowly to one side, then back to the front.",
}
NAMES: Mapping[str, str] = {
    "arm_raise": "Arm raises",
    "shoulder_roll": "Shoulder rolls",
    "torso_twist": "Torso twists",
    "knee_lift": "Knee lifts",
    "ankle_pump": "Ankle pumps",
    "neck_turn": "Neck turns",
}
START = "Do any of the six seated moves; JARVIS counts it."
RESTING = "Rest. Start the next set when you are ready."
UNSEEN = "Sit where the home camera sees all of you, side-on."


@dataclass(frozen=True)
class Move:
    id: str
    swing: float  # half a rep's swing that counts
    full: float  # a usual rep's whole range
    signal: Callable[[Mapping[int, tuple[float, float]], float], float | None]


Point = tuple[float, float]


def _angle(a: Point, b: Point, c: Point) -> float | None:
    ux, uy, vx, vy = a[0] - b[0], a[1] - b[1], c[0] - b[0], c[1] - b[1]
    nu, nv = math.hypot(ux, uy), math.hypot(vx, vy)
    if not nu or not nv:
        return None
    return math.degrees(math.acos(max(-1.0, min(1.0, (ux * vx + uy * vy) / (nu * nv)))))


def _arm(p: Mapping[int, Point], torso: float) -> float | None:
    return _angle(p[23], p[11], p[15]) if {23, 11, 15} <= p.keys() else None


def _shrug(p: Mapping[int, Point], torso: float) -> float | None:
    return (p[23][1] - p[11][1]) / torso if {23, 11} <= p.keys() else None


def _twist(p: Mapping[int, Point], torso: float) -> float | None:
    return abs(p[11][0] - p[12][0]) / torso if {11, 12} <= p.keys() else None


def _knee(p: Mapping[int, Point], torso: float) -> float | None:
    if not {23, 25} <= p.keys():
        return None
    (hx, hy), (kx, ky) = p[23], p[25]
    return math.degrees(math.atan2(hy - ky, abs(kx - hx) or 1e-9))


def _ankle(p: Mapping[int, Point], torso: float) -> float | None:
    return _angle(p[25], p[27], p[31]) if {25, 27, 31} <= p.keys() else None


def _neck(p: Mapping[int, Point], torso: float) -> float | None:
    return abs(p[0][0] - p[7][0]) / torso if {0, 7} <= p.keys() else None


MOVES: tuple[Move, ...] = (
    Move("arm_raise", 30.0, 100.0, _arm),
    Move("shoulder_roll", 0.035, 0.1, _shrug),
    Move("torso_twist", 0.08, 0.25, _twist),
    Move("knee_lift", 7.0, 22.0, _knee),
    Move("ankle_pump", 7.0, 25.0, _ankle),
    Move("neck_turn", 0.04, 0.12, _neck),
)
_PAIRS = ((11, 12), (13, 14), (15, 16), (23, 24), (25, 26), (27, 28), (29, 30), (31, 32), (7, 8))


def near_side(points: Sequence[Mapping[str, Any]], aspect: float = 1.0) -> dict[int, Point]:
    """The body's points on the side the camera sees better, under the left side's numbers (11,
    13, 15, 23, 25, 27, 29, 31, 7); the far shoulder stays 12 (the twist needs both). R8 I1: x is
    scaled by the frame's `aspect` (width / height), so every angle and length is in one unit."""

    def seen(i: int) -> tuple[float, float, float] | None:
        if i >= len(points):
            return None
        q = points[i]
        try:
            x, y, v = float(q["x"]), float(q["y"]), float(q.get("visibility", 1.0))
        except (KeyError, TypeError, ValueError):
            return None
        ok = v >= VIS_MIN and math.isfinite(x) and math.isfinite(y)
        return (x * aspect, y, v) if ok else None

    left = [seen(a) for a, _ in _PAIRS]
    right = [seen(b) for _, b in _PAIRS]
    score = sum(q[2] for q in left if q) - sum(q[2] for q in right if q)
    near, far = (left, right) if score >= 0 else (right, left)
    out: dict[int, Point] = {}
    for (a, _), q in zip(_PAIRS, near, strict=True):
        if q:
            out[a] = (q[0], q[1])
    if far[0]:
        out[12] = (far[0][0], far[0][1])
    nose = seen(0)
    if nose:
        out[0] = (nose[0], nose[1])
    return out


@dataclass(frozen=True)
class Swing:
    """One move's number over the window, and its rep count."""

    window: tuple[tuple[float, float], ...] = ()  # (t, smoothed value)
    phase: str = ""  # "" | "high" | "low"
    first: str = ""  # the side a rep goes to first: coming back to the other side completes it
    count: int = 0
    smooth: float | None = None

    def step(self, t: float, raw: float, move: Move) -> Swing:
        v = raw if self.smooth is None else self.smooth + SMOOTH * (raw - self.smooth)
        window = (*(w for w in self.window if w[0] > t - WINDOW_S), (t, v))
        values = [w[1] for w in window]
        x = v - (max(values) + min(values)) / 2
        side = "high" if x > move.swing else ("low" if x < -move.swing else "")
        if not side or side == self.phase:
            return replace(self, window=window, smooth=v)
        first = self.first or side
        return Swing(window, side, first, self.count + (1 if side != first else 0), v)

    def reach(self, move: Move) -> float:
        values = [w[1] for w in self.window]
        return (max(values) - min(values)) / move.full if len(values) > 1 else 0.0


@dataclass(frozen=True)
class Block:
    """One move's sets this session."""

    sets: int = 0
    reps: int = 0
    target: int = TARGET0
    easy_run: int = 0
    finished: bool = False


@dataclass(frozen=True)
class SeatedState:
    began: int
    at: int
    t: float
    torso: float = 0.0
    swings: Mapping[str, Swing] = field(default_factory=dict)
    blocks: Mapping[str, Block] = field(default_factory=dict)
    credited: Mapping[str, int] = field(default_factory=dict)  # each move's reps already counted
    move: str = ""  # the move of the set under way (or the last one)
    reps: int = 0  # this set's reps so far
    times: tuple[float, ...] = ()  # when each of this set's reps counted
    last_rep: float = 0.0
    seen: bool = False


def _easy(times: Sequence[float]) -> bool:
    gaps = [b - a for a, b in zip(times, times[1:], strict=False)]
    if len(gaps) < 4:
        return True
    first, last = sum(gaps[:3]) / 3, sum(gaps[-3:]) / 3
    return last <= EASY_SLOWER * first


def _close_set(s: SeatedState) -> SeatedState:
    """The set under way ends (he rested): the move's block and its next target."""
    if not s.move or not s.reps:
        return replace(s, reps=0, times=())
    b = s.blocks.get(s.move, Block())
    finished = s.reps >= b.target
    easy_run = (b.easy_run + 1 if _easy(s.times) else 0) if finished else 0
    target = b.target
    if not finished:
        target = max(TARGET_MIN, b.target - STEP)
    elif easy_run >= 2:
        target, easy_run = min(TARGET_MAX, b.target + STEP), 0
    block = Block(b.sets + 1, b.reps + s.reps, target, easy_run, finished)
    return replace(s, blocks={**s.blocks, s.move: block}, reps=0, times=())


class SeatedCoach:
    """The `seated` home use case (`jarvis.coach.home.HomeUseCase`)."""

    id = USE
    tasks = TASKS

    def on_result(self, result: Mapping[str, Any], state: SeatedState | None) -> SeatedState:
        t, at = _times(result)
        s = state or SeatedState(began=at, at=at, t=t)
        s = replace(s, at=max(s.at, at), t=t)
        data = result.get("data") if result.get("task") == "pose" else None
        points = data.get("points") if isinstance(data, Mapping) else None
        p = near_side(points, aspect_of(result)) if isinstance(points, Sequence) else {}
        if not {11, 23} <= p.keys():
            return _rested(s, t)
        torso = math.dist(p[11], p[23])
        if torso < 0.05:
            return _rested(s, t)
        torso = torso if not s.torso else s.torso + TORSO_SLOW * (torso - s.torso)
        swings = dict(s.swings)
        for m in MOVES:
            v = m.signal(p, torso)
            if v is not None and math.isfinite(v):
                swings[m.id] = swings.get(m.id, Swing()).step(t, v, m)
        reach = {k: w.reach(next(m for m in MOVES if m.id == k)) for k, w in swings.items()}
        best = max(reach, key=lambda k: reach[k], default="")
        active = best if best and reach[best] >= ACTIVE else ""
        # an idle move's reps are let go; a move warming up keeps them until it is the one he does
        credited = {
            k: (w.count if reach[k] < IDLE else s.credited.get(k, 0)) for k, w in swings.items()
        }
        gained = swings[active].count - credited.get(active, 0) if active else 0
        if active:
            credited[active] = swings[active].count
        s = replace(s, torso=torso, swings=swings, credited=credited, seen=True)
        if gained <= 0:
            return _rested(s, t)
        if s.move and active != s.move and s.reps:
            s = _close_set(s)
        return replace(
            s, move=active, reps=s.reps + gained, times=(*s.times, *([t] * gained)), last_rep=t
        )

    def summary(self, state: SeatedState | None) -> Summary:
        return {"view": _view(state), "tally": _tally(state) if state is not None else None}


def _rested(s: SeatedState, t: float) -> SeatedState:
    if s.reps and t - s.last_rep >= REST_S:
        return _close_set(s)
    return s


def _times(result: Mapping[str, Any]) -> tuple[float, int]:
    at = result.get("at")
    at_i = int(at) if isinstance(at, (int, float)) and math.isfinite(at) and at >= 0 else 0
    t = result.get("t")
    return (float(t) if isinstance(t, (int, float)) and math.isfinite(t) else float(at_i)), at_i


def _tally(s: SeatedState) -> dict[str, Any] | None:
    if not s.move:
        return None
    b = s.blocks.get(s.move, Block())
    return {
        "started_at": s.began,
        "ended_at": max(s.began, s.at),
        "move": s.move,
        "sets": min(500, b.sets),
        "reps": min(500, b.reps + s.reps),
        "target": b.target,
        "finished": b.finished,
    }


def _view(s: SeatedState | None) -> list[dict[str, Any]]:
    safety = {"kind": "line", "text": f"{PRACTICE} {STOP}"}
    if s is None:
        return [{"kind": "line", "text": START}, safety]
    if not s.seen:
        return [{"kind": "paused", "why": UNSEEN}, safety]
    if not s.move:
        return [{"kind": "line", "text": START}, safety]
    b = s.blocks.get(s.move, Block())
    view: list[dict[str, Any]] = [
        {"kind": "big", "n": s.reps, "word": f"of {b.target}"},
        {"kind": "line", "text": f"{NAMES[s.move]}, set {b.sets + 1}"},
        {"kind": "tip", "text": WORDS[s.move] if s.reps else RESTING},
    ]
    if b.sets:
        last = "finished" if b.finished else "stopped early"
        view.append({"kind": "line", "text": f"Last set {last}; this one is {b.target}."})
    view.append(safety)
    return view


def make() -> SeatedCoach:
    return SeatedCoach()


__all__ = ["MOVES", "TASKS", "USE", "SeatedCoach", "SeatedState", "make", "near_side"]
