# src/jarvis/coach/home/bp_posture.py
"""R8 builder D, row 262's checklist (docs/plans/r8-vision.md v8.0.4 section 2.1, the owner's D3):
the home blood-pressure posture coach, a home rule run on the home laptop by the home vision plugin
(J's runtime) on the home camera's pose and objects (`dining_table`, `chair`), one body at a time,
about twice a second. Kit-safe: the standard library only. The reading itself is the webcam's
(console-coach-bp.js, D7); this rule only helps him sit the way a reading is taken.

The six items, judged on the side the camera sees better (the camera is side-on, owner step 4a),
with the torso's length (shoulder to hip) as the scale:

| item   | judged right when                                                                     |
|--------|---------------------------------------------------------------------------------------|
| back   | the torso is upright or leaning back a little (`LEAN_BACK` to `LEAN_FORWARD` degrees) |
| feet   | the shin is near upright (`SHIN_MAX`) and the foot near level (`FOOT_MAX`)            |
| legs   | the two knees and ankles are at one height (`CROSS_KNEE`, `CROSS_ANKLE`)              |
| arm    | the forearm lies level (`FOREARM`) and the middle of the upper arm, where the cuff   |
|        | goes, sits `HEART_FROM` to `HEART_TO` of the torso below the shoulder; when the      |
|        | object model sees a table, the forearm also rests near its top                        |
| still  | over the last `STILL_S`, no body point moved more than `STILL_MAX` of the torso       |
| rested | he has sat with the first four right, without moving much, for `REST_S` (five        |
|        | minutes); standing up or moving a lot starts the five minutes again                   |

The view: one `checklist` widget an item ({item, text, state ok | warn | wait, word, hint}, plain
scalars: `jarvis.home.ports.CoachReport`), a `bar` with the score (items right, of 100) and the
practice line. Its tally is `jarvis.coach.usecases`' BpPostureTally (six yes/no and the score). A
checklist, never a measurement and never a word about health: the no-diagnosis test reads these
strings too.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from typing import Any

from jarvis.coach.home import Summary
from jarvis.coach.home.seated import near_side

USE = "bp-posture"
TASKS: tuple[str, ...] = ("pose", "objects")
LEAN_BACK = -25.0
LEAN_FORWARD = 12.0
SHIN_MAX = 25.0
FOOT_MAX = 20.0
CROSS_KNEE = 0.12
CROSS_ANKLE = 0.15
FOREARM = 0.15  # the wrist within this share of the torso of the elbow's height
HEART_FROM = 0.08
HEART_TO = 0.29
TABLE_NEAR = 0.15
STILL_S = 5.0
STILL_MAX = 0.06
MOVED_MAX = 0.2  # moving more than this share of the torso starts the rest again
REST_S = 300.0
LOST_S = 10.0  # unseen for longer than this starts the rest again
SCORE_MIN = 0.4
ITEMS: tuple[str, ...] = ("back", "feet", "legs", "arm", "rested", "still")
TEXT: Mapping[str, str] = {
    "back": "Back against the chair",
    "feet": "Both feet flat on the floor",
    "legs": "Legs not crossed",
    "arm": "Cuff arm at heart level",
    "rested": "Sit quietly for 5 minutes",
    "still": "Sit still and quiet",
}
HINT: Mapping[str, str] = {
    "back": "Sit back so the chair holds your back.",
    "feet": "Put both feet flat on the floor in front of you.",
    "legs": "Uncross your legs.",
    "arm": "Rest the arm on a cushion so the cuff sits level with your heart.",
    "rested": "",
    "still": "Keep still and don't talk while you wait.",
}
READY = "When every line says Yes, measure the usual way."
PRACTICE = "Practice only, not medical advice."
UNSEEN = "Sit side-on to the home camera, where it sees all of you."

Point = tuple[float, float]


@dataclass(frozen=True)
class BpPostureState:
    began: int
    at: int
    t: float
    checks: Mapping[str, bool]  # the five judged items (rested apart), the latest frame's
    seen: bool = False
    window: tuple[tuple[float, tuple[Point, ...]], ...] = ()  # (t, a few points) for stillness
    rest_since: float | None = None  # when the five items were last all right, unbroken
    table: tuple[float, float] | None = None  # the table box's top and when it was seen
    lost_at: float | None = None  # since when he has not been seen

    @property
    def rested(self) -> bool:
        return self.rest_since is not None and self.t - self.rest_since >= REST_S


def _lean(p: Mapping[int, Point]) -> float:
    """The torso's lean forward from upright, degrees (the face's side is forward)."""
    (hx, hy), (sx, sy) = p[23], p[11]
    facing = 1.0 if 0 not in p or 7 not in p else (1.0 if p[0][0] >= p[7][0] else -1.0)
    return math.degrees(math.atan2((sx - hx) * facing, hy - sy))


def _feet(p: Mapping[int, Point]) -> bool:
    if not {25, 27, 31} <= p.keys():
        return False
    (kx, ky), (ax, ay), (tx, ty) = p[25], p[27], p[31]
    shin = abs(math.degrees(math.atan2(ax - kx, ay - ky)))
    foot = abs(math.degrees(math.atan2(ay - ty, abs(tx - ax) or 1e-9)))
    return shin <= SHIN_MAX and foot <= FOOT_MAX


def _legs(points: Sequence[Mapping[str, Any]], torso: float) -> bool:
    try:
        ys = {i: float(points[i]["y"]) for i in (25, 26, 27, 28)}
    except (IndexError, KeyError, TypeError, ValueError):
        return False
    return (
        abs(ys[25] - ys[26]) <= CROSS_KNEE * torso and abs(ys[27] - ys[28]) <= CROSS_ANKLE * torso
    )


def _arm(p: Mapping[int, Point], torso: float, table_y: float | None) -> bool:
    if not {11, 13, 15} <= p.keys():
        return False
    sy, ey, wy = p[11][1], p[13][1], p[15][1]
    level = abs(wy - ey) <= FOREARM * torso
    cuff = ((sy + ey) / 2 - sy) / torso
    rests = table_y is None or abs(table_y - max(ey, wy)) <= TABLE_NEAR
    return level and HEART_FROM <= cuff <= HEART_TO and rests


def _still(window: Sequence[tuple[float, tuple[Point, ...]]], torso: float) -> bool:
    if len(window) < 2 or window[-1][0] - window[0][0] < STILL_S - 0.6:
        return False
    return _moved(window) <= STILL_MAX * torso


def _moved(window: Sequence[tuple[float, tuple[Point, ...]]]) -> float:
    spans = [
        max(math.dist(a, b) for a in pts for b in pts) if len(pts) > 1 else 0.0
        for pts in zip(*(w[1] for w in window), strict=False)
    ]
    return max(spans, default=0.0)


def _times(result: Mapping[str, Any]) -> tuple[float, int]:
    at = result.get("at")
    at_i = int(at) if isinstance(at, (int, float)) and math.isfinite(at) and at >= 0 else 0
    t = result.get("t")
    return (float(t) if isinstance(t, (int, float)) and math.isfinite(t) else float(at_i)), at_i


def _table(result: Mapping[str, Any]) -> float | None:
    data = result.get("data")
    things = data.get("objects") if isinstance(data, Mapping) else None
    tops = [
        float(o["box"]["y"])
        for o in (things if isinstance(things, Sequence) else ())
        if isinstance(o, Mapping)
        and o.get("label") == "dining_table"
        and float(o.get("score", 0)) >= SCORE_MIN
    ]
    return min(tops) if tops else None


NONE_RIGHT: Mapping[str, bool] = {k: False for k in ITEMS if k != "rested"}


class BpPostureCoach:
    """The `bp-posture` home use case (`jarvis.coach.home.HomeUseCase`)."""

    id = USE
    tasks = TASKS

    def on_result(self, result: Mapping[str, Any], state: BpPostureState | None) -> BpPostureState:
        t, at = _times(result)
        s = state or BpPostureState(began=at, at=at, t=t, checks=NONE_RIGHT)
        s = replace(s, at=max(s.at, at), t=t)
        if result.get("task") == "objects":
            top = _table(result)
            return replace(s, table=(top, t)) if top is not None else s
        data = result.get("data") if result.get("task") == "pose" else None
        points = data.get("points") if isinstance(data, Mapping) else None
        p = near_side(points) if isinstance(points, Sequence) else {}
        if (
            not isinstance(points, Sequence)
            or not {11, 23} <= p.keys()
            or math.dist(p[11], p[23]) < 0.05
        ):
            lost = s.lost_at if s.lost_at is not None else t
            kept = (
                s.rest_since if t - lost <= LOST_S else None
            )  # a moment unseen keeps the five minutes
            return replace(
                s, seen=False, checks=NONE_RIGHT, rest_since=kept, window=(), lost_at=lost
            )
        torso = math.dist(p[11], p[23])
        keep = tuple(p[i] for i in (0, 11, 15, 23) if i in p)
        window = (
            *(w for w in s.window if w[0] > t - STILL_S and len(w[1]) == len(keep)),
            (t, keep),
        )
        table_y = s.table[0] if s.table is not None and t - s.table[1] <= 10 else None
        checks = {
            "back": LEAN_BACK <= _lean(p) <= LEAN_FORWARD,
            "feet": _feet(p),
            "legs": _legs(points, torso),
            "arm": _arm(p, torso, table_y),
            "still": _still(window, torso),
        }
        sat = all(checks[k] for k in ("back", "feet", "legs", "arm"))
        broke = not sat or _moved(window) > MOVED_MAX * torso
        rest_since = None if broke else (s.rest_since if s.rest_since is not None else t)
        return replace(
            s, seen=True, checks=checks, window=window, rest_since=rest_since, lost_at=None
        )

    def summary(self, state: BpPostureState | None) -> Summary:
        if state is None:
            return {
                "view": [{"kind": "line", "text": UNSEEN}, {"kind": "line", "text": PRACTICE}],
                "tally": None,
            }
        return {"view": _view(state), "tally": _tally(state)}


def _right(s: BpPostureState) -> dict[str, bool]:
    return {**{k: bool(s.checks.get(k)) for k in ITEMS if k != "rested"}, "rested": s.rested}


def _tally(s: BpPostureState) -> dict[str, Any]:
    right = _right(s)
    return {
        "started_at": s.began,
        "ended_at": max(s.began, s.at),
        **right,
        "score": round(100 * sum(right.values()) / len(ITEMS)),
    }


def _left(s: BpPostureState) -> str:
    gone = 0.0 if s.rest_since is None else s.t - s.rest_since
    left = max(0, math.ceil(REST_S - gone))
    return f"{left // 60}:{left % 60:02d} left"


def _view(s: BpPostureState) -> list[dict[str, Any]]:
    right = _right(s)
    view: list[dict[str, Any]] = []
    for item in ITEMS:
        ok = right[item]
        waiting = item == "rested" and not ok
        state = "ok" if ok else ("wait" if waiting else "warn")
        word = "Yes" if ok else ("Waiting" if waiting else "Not yet")
        hint = _left(s) if waiting else ("" if ok else HINT[item])
        view.append(
            {
                "kind": "checklist",
                "item": item,
                "text": TEXT[item],
                "state": state,
                "word": word,
                "hint": hint,
            }
        )
    done = sum(right.values())
    if s.seen:
        view.append(
            {
                "kind": "bar",
                "n": round(100 * done / len(ITEMS)),
                "word": f"{done} of {len(ITEMS)} ready",
            }
        )
    else:
        view.append({"kind": "paused", "why": UNSEEN})
    view.append({"kind": "line", "text": READY if done == len(ITEMS) else PRACTICE})
    return view


def make() -> BpPostureCoach:
    return BpPostureCoach()


__all__ = ["ITEMS", "TASKS", "USE", "BpPostureCoach", "BpPostureState", "make"]
