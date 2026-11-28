# src/jarvis/coach/home/posture.py
"""R8 row 181 (docs/plans/r8-vision.md 4.7, the owner's D3; builder C): posture checks from the
home camera, run on the home laptop by the home vision plugin (`jarvis.homebridge.homevision`).

Kit-safe: the standard library only (it ships in the home kit; `jarvis.coach.home`'s contract).
One `PostureCoach` per body (the runtime keeps a state per track, as the console's driver does).
It reads one body's pose Result at a time and keeps only angles, never a point:

- **Calibration:** the first `CALIB_S` (10) seconds he is judged are his upright: the median of
  his torso lean and neck angle is his own baseline (capped, so a slouch can't become it). A
  baseline he saved earlier can be given to the factory (`PostureCoach(baseline=...)`).
- **A slouch:** the torso leans more than `TORSO_DELTA` past his baseline, or the head is pushed
  forward more than `NECK_DELTA` (smoothed). It is held while it lasts, with `GOOD_END_S` of good
  posture needed to end it (a glance up doesn't). Held `HOLD_S` (60 s), it is one slouch span and
  asks for **one** nudge (the view's `tip` widget, with the span's start as `since`), at most
  `PER_HOUR` (3) an hour. The cloud (`jarvis.helpers.nudges.posture`) sends it, inside his window
  and the gate's caps.
- **Frames:** about 1 a second; `wanted_rate(state)` asks for 2 while a slouch is suspected.
  Frames whose shoulder, ear and hip are not visible enough are not judged (dark, turned away).
- **The tally** (`PostureTally`): slouch spans, seconds slouched in them, nudges asked, and the
  share of judged time upright (0..100), with the session's start and end. Counts and times only.

Angles are in degrees from the vertical, measured side-on (the owner's step 4a: the camera sees
the whole of him from the side). `aspect` is the stream's width / height (the points are 0..1 of
each side), so an angle is the same on a wide or a square picture.
"""

from __future__ import annotations

import math
import statistics
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from typing import Any

from jarvis.coach.home import Summary, aspect_of

ID = "posture"
TASKS: tuple[str, ...] = ("pose",)
CALIB_S = 10.0
TORSO_DELTA = 12.0  # degrees past his upright: leaning towards the screen
NECK_DELTA = 15.0  # degrees past his upright: the head pushed forward
BASE_MAX_TORSO = 18.0  # a calibration can't make a slouch his upright
BASE_MAX_NECK = 26.0
DEFAULT_BASE = (6.0, 12.0)  # used only until he has calibrated (torso, neck)
HOLD_S = 60.0  # a slouch held this long is one span: one nudge
GOOD_END_S = 6.0  # good posture this long ends a span
LOST_S = 15.0  # no judged frame this long: whatever was suspected is forgotten
MAX_DT = 5.0  # a gap longer than this is not credited to any total
PER_HOUR = 3  # nudges a span may ask for in any hour (the cloud caps them again)
HOUR_S = 3600.0
SMOOTH = 0.4  # the share of a new frame in the smoothed angles
MIN_VIS = 0.5
RATE, SUSPECT_RATE = 1.0, 2.0
# its fixed words (the same as jarvis.coach.words.COACH_WORDS["posture"]; this module is kit-safe)
NUDGE = "Sit back and lift your head, Sir."
CALIBRATE = "Sit up straight for 10 seconds."
CALIBRATED = "Calibrated."
UPRIGHT = "Upright. Head over your shoulders."
SLOUCHING = "Leaning towards the screen."
NOT_SEEN = "Not in view of the home camera."
WORDS: tuple[str, ...] = (NUDGE, CALIBRATE, CALIBRATED, UPRIGHT, SLOUCHING, NOT_SEEN)

_EAR, _SHOULDER, _HIP = (7, 8), (11, 12), (23, 24)


@dataclass(frozen=True)
class PostureState:
    """One body's posture so far: angles and times only (never a point)."""

    first: float | None = None
    last: float | None = None
    judged_last: float | None = None
    samples: tuple[tuple[float, float], ...] = ()  # (torso, neck) while calibrating
    calib_from: float | None = None
    base: tuple[float, float] | None = None
    smooth: tuple[float, float] | None = None
    since: float | None = None  # a slouch's first frame (suspected or held)
    good_since: float | None = None  # good posture inside a slouch, since
    nudged: bool = False  # this span asked for its nudge
    counted: bool = False  # this span reached HOLD_S
    spans: int = 0
    slouch_s: float = 0.0
    judged_s: float = 0.0
    upright_s: float = 0.0
    nudges: int = 0
    asked: tuple[float, ...] = ()  # when each nudge was asked (the last hour's)
    seen: bool = False


def _num(v: object) -> float | None:
    return float(v) if isinstance(v, int | float) and not isinstance(v, bool) else None


def _mean_point(
    points: Sequence[Mapping[str, Any]], ids: tuple[int, int]
) -> tuple[float, float] | None:
    got = []
    for i in ids:
        p = points[i] if i < len(points) else None
        if not isinstance(p, Mapping):
            continue
        x, y, vis = _num(p.get("x")), _num(p.get("y")), _num(p.get("visibility"))
        if x is None or y is None or (vis if vis is not None else 1.0) < MIN_VIS:
            continue
        got.append((x, y))
    if not got:
        return None
    return sum(g[0] for g in got) / len(got), sum(g[1] for g in got) / len(got)


def _from_vertical(low: tuple[float, float], high: tuple[float, float], aspect: float) -> float:
    """The angle (degrees, 0 = straight up) of the segment from `low` up to `high`."""
    dx = (high[0] - low[0]) * aspect
    dy = low[1] - high[1]  # the picture's y grows downwards
    return abs(math.degrees(math.atan2(dx, dy)))


def angles(points: Sequence[Mapping[str, Any]], aspect: float = 1.0) -> tuple[float, float] | None:
    """(torso lean, neck angle) in degrees from the vertical, or None when not visible enough."""
    ear, shoulder, hip = (_mean_point(points, ids) for ids in (_EAR, _SHOULDER, _HIP))
    if ear is None or shoulder is None or hip is None:
        return None
    if hip[1] - shoulder[1] <= 0.02:  # shoulders not above the hips: not a seated body
        return None
    return _from_vertical(hip, shoulder, aspect), _from_vertical(shoulder, ear, aspect)


def _result_points(result: Mapping[str, Any]) -> Sequence[Mapping[str, Any]] | None:
    if result.get("task") != "pose" or not result.get("ok", True):
        return None
    data = result.get("data")
    pts = data.get("points") if isinstance(data, Mapping) else None
    return pts if isinstance(pts, Sequence) and len(pts) >= 25 else None


class PostureCoach:
    """The posture rule for one body. `baseline` (torso, neck): a calibration he saved earlier."""

    id = ID
    tasks = TASKS

    def __init__(
        self, *, aspect: float = 16 / 9, baseline: tuple[float, float] | None = None
    ) -> None:
        self.aspect = aspect if 0.2 <= aspect <= 5.0 else 16 / 9
        self.baseline = _capped(baseline) if baseline else None

    # ---- frames in ----------------------------------------------------------------------------
    def on_result(self, result: Mapping[str, Any], state: PostureState | None) -> PostureState:
        s = state or PostureState(base=self.baseline)
        at = _num(result.get("at"))
        if at is None:
            return s
        s = replace(s, first=at if s.first is None else s.first, last=at)
        pts = _result_points(result)
        found = angles(pts, aspect_of(result, self.aspect)) if pts is not None else None  # I1
        if found is None:
            return self._unjudged(s, at)
        return self._judge(s, at, found)

    def _unjudged(self, s: PostureState, at: float) -> PostureState:
        if s.judged_last is not None and at - s.judged_last > LOST_S:
            return _closed(replace(s, seen=False, smooth=None), s.judged_last)
        return s

    def _judge(self, s: PostureState, at: float, found: tuple[float, float]) -> PostureState:
        dt = min(MAX_DT, at - s.judged_last) if s.judged_last is not None else 0.0
        dt = max(0.0, dt)
        if s.judged_last is not None and at - s.judged_last > LOST_S:
            s = _closed(replace(s, smooth=None), s.judged_last)
            dt = 0.0
        s = replace(s, judged_last=at, seen=True)
        base = s.base
        if base is None:
            return self._calibrate(s, at, found)
        prev = s.smooth or found
        smooth = (
            prev[0] + SMOOTH * (found[0] - prev[0]),
            prev[1] + SMOOTH * (found[1] - prev[1]),
        )
        s = replace(s, smooth=smooth, judged_s=s.judged_s + dt)
        bad = smooth[0] - base[0] > TORSO_DELTA or smooth[1] - base[1] > NECK_DELTA
        return _slouch(s, at, dt) if bad else _good(s, at, dt)

    def _calibrate(self, s: PostureState, at: float, found: tuple[float, float]) -> PostureState:
        start = s.calib_from if s.calib_from is not None else at
        samples = (*s.samples, found)
        if at - start < CALIB_S:
            return replace(s, calib_from=start, samples=samples)
        base = _capped(
            (
                statistics.median(a for a, _ in samples),
                statistics.median(b for _, b in samples),
            )
        )
        return replace(s, calib_from=start, samples=(), base=base, smooth=base)

    # ---- what it says -------------------------------------------------------------------------
    def wanted_rate(self, state: PostureState | None) -> float:
        """Frames a second it wants: 2 while a slouch is suspected, else 1 (the runtime's hint)."""
        return SUSPECT_RATE if state is not None and state.since is not None else RATE

    def summary(self, state: PostureState | None) -> Summary:
        s = state or PostureState(base=self.baseline)
        return {"view": _view(s), "tally": _tally(s)}


def _capped(base: tuple[float, float]) -> tuple[float, float]:
    return min(float(base[0]), BASE_MAX_TORSO), min(float(base[1]), BASE_MAX_NECK)


def _slouch(s: PostureState, at: float, dt: float) -> PostureState:
    since = s.since if s.since is not None else at
    s = replace(s, since=since, good_since=None)
    held = at - since
    if held < HOLD_S:
        return s
    s = replace(s, slouch_s=s.slouch_s + (dt if s.counted else held), counted=True)
    return s if s.nudged else _ask(s, at)


def _ask(s: PostureState, at: float) -> PostureState:
    recent = tuple(t for t in s.asked if at - t < HOUR_S)
    if len(recent) >= PER_HOUR:
        return replace(s, asked=recent, nudged=True)  # this span stays quiet
    return replace(s, asked=(*recent, at), nudged=True, nudges=s.nudges + 1)


def _good(s: PostureState, at: float, dt: float) -> PostureState:
    s = replace(s, upright_s=s.upright_s + dt)
    if s.since is None:
        return s
    good_since = s.good_since if s.good_since is not None else at
    if at - good_since < GOOD_END_S:
        if s.counted:  # a glance up inside a held span still counts as the span
            s = replace(s, slouch_s=s.slouch_s + dt)
        return replace(s, good_since=good_since)
    return _closed(s, at)


def _closed(s: PostureState, at: float) -> PostureState:
    """The slouch (if any) is over: a held one becomes one more span."""
    del at
    spans = s.spans + (1 if s.counted else 0)
    return replace(s, since=None, good_since=None, nudged=False, counted=False, spans=spans)


def _view(s: PostureState) -> list[dict[str, Any]]:
    if s.base is None:
        left = CALIB_S if s.calib_from is None or s.judged_last is None else (
            max(0.0, CALIB_S - (s.judged_last - s.calib_from))
        )  # fmt: skip
        return [
            {"kind": "line", "text": CALIBRATE},
            {"kind": "timer", "s": round(left), "word": "calibrating"},
        ]
    if not s.seen:
        return [{"kind": "paused", "why": NOT_SEEN}, *_score(s)]
    if s.since is not None and s.last is not None:
        held = max(0, round(s.last - s.since))
        view: list[dict[str, Any]] = [
            {"kind": "line", "text": SLOUCHING},
            {"kind": "timer", "s": held, "word": "slouching"},
        ]
        if s.nudged and s.nudges and s.asked and s.asked[-1] >= s.since:
            view.append({"kind": "tip", "text": NUDGE, "since": int(s.since), "held": held})
        return [*view, *_score(s)]
    return [{"kind": "line", "text": UPRIGHT}, *_score(s)]


def _upright(s: PostureState) -> int:
    return round(100 * s.upright_s / s.judged_s) if s.judged_s > 0 else 100


def _score(s: PostureState) -> list[dict[str, Any]]:
    return [{"kind": "bar", "n": _upright(s), "word": "upright"}]


def _tally(s: PostureState) -> dict[str, Any] | None:
    if s.first is None or s.last is None or s.base is None:
        return None
    return {
        "started_at": int(s.first),
        "ended_at": int(s.last),
        "slouch_spans": min(500, s.spans + (1 if s.counted else 0)),
        "slouch_seconds": round(min(86_400.0, s.slouch_s), 1),
        "nudges": min(500, s.nudges),
        "upright": max(0, min(100, _upright(s))),
    }


def create() -> PostureCoach:
    """The registry's factory (`jarvis.coach.home.REGISTRY["posture"]`, wired at the I1 join)."""
    return PostureCoach()


__all__ = [
    "CALIB_S",
    "HOLD_S",
    "ID",
    "NUDGE",
    "PER_HOUR",
    "TASKS",
    "WORDS",
    "PostureCoach",
    "PostureState",
    "angles",
    "create",
]
