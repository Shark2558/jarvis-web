# src/jarvis/coach/home/activity.py
"""R8 row 182 (docs/plans/r8-vision.md 4.7, the owner's D3; builder C): the activity timeline from
the home camera, run on the home laptop by the home vision plugin, about 1 frame a second.

Kit-safe: the standard library only. One `ActivityCoach` per body. Each minute is labelled:

- **desk:** he is in view (his pose is seen in at least `SEEN_SHARE` of the minute's frames);
- **phone:** in view, with a phone (`cell_phone`) in his hands' reach in `VOTE_SHARE` of them;
- **eating:** in view, with food or a bowl or cutlery in reach in `VOTE_SHARE` of them (a cup
  alone is a sip at the desk, not a meal);
- **away:** frames came (the objects task keeps looking) but his pose did not.

Consecutive minutes of one kind are one segment; a gap of more than `GAP_FILL_S` with no frame at
all is left uncovered (the coach wasn't looking: the day strip shows it as "off"). **Only kind,
start and end are kept** (the `ActivityTally`'s segments, at most `MAX_SEGMENTS`: the shortest
merge into a neighbour). In memory, between frames, it keeps the box his body filled in the last
frame (to tell whether a phone is in his reach), never a point; nothing of it is reported.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from typing import Any

from jarvis.coach.home import Summary

ID = "activity"
TASKS: tuple[str, ...] = ("pose", "objects")
KINDS: tuple[str, ...] = ("desk", "away", "phone", "eating")
MINUTE = 60
SEEN_SHARE = 0.25  # in view for a quarter of the minute's frames: at the desk
VOTE_SHARE = 0.3  # a phone (or food) in reach for this share of the in-view frames
GAP_FILL_S = 120  # a gap with no frame up to this long is still looked at (missed frames)
MAX_SEGMENTS = 200  # the ActivityTally's own cap
MIN_VIS = 0.5
REACH = 0.08  # how far past his body's box a thing still counts as in reach (0..1 of the frame)
PHONE: frozenset[str] = frozenset({"cell_phone"})
FOOD: frozenset[str] = frozenset(
    {
        "bowl",
        "fork",
        "spoon",
        "knife",
        "sandwich",
        "pizza",
        "banana",
        "apple",
        "orange",
        "donut",
        "cake",
        "hot_dog",
        "carrot",
        "broccoli",
    }  # fmt: skip
)
WORDS: dict[str, str] = {
    "desk": "At the desk.",
    "away": "Away from the desk.",
    "phone": "On the phone.",
    "eating": "Eating.",
}

Box = tuple[float, float, float, float]  # x0, y0, x1, y1


@dataclass(frozen=True)
class Minute:
    """The current minute's counts: seconds that had any frame, his pose, a phone, food."""

    index: int
    frames: frozenset[int] = frozenset()
    seen: frozenset[int] = frozenset()
    phone: frozenset[int] = frozenset()
    food: frozenset[int] = frozenset()


@dataclass(frozen=True)
class ActivityState:
    first: int | None = None
    last: int | None = None
    minute: Minute | None = None
    segments: tuple[tuple[str, int, int], ...] = ()  # (kind, start, end), closed minutes
    reach: Box | None = None  # his body's box in the last frame (memory only, never reported)
    reach_at: int | None = None


def _num(v: object) -> float | None:
    return float(v) if isinstance(v, int | float) and not isinstance(v, bool) else None


def body_box(points: Sequence[Mapping[str, Any]]) -> Box | None:
    xs, ys = [], []
    for p in points:
        if not isinstance(p, Mapping):
            continue
        x, y, vis = _num(p.get("x")), _num(p.get("y")), _num(p.get("visibility"))
        if x is None or y is None or (vis if vis is not None else 1.0) < MIN_VIS:
            continue
        xs.append(x)
        ys.append(y)
    if len(xs) < 8:  # too little of him to say he is there
        return None
    return min(xs), min(ys), max(xs), max(ys)


def _thing_box(thing: Mapping[str, Any]) -> Box | None:
    b = thing.get("box")
    if not isinstance(b, Mapping):
        return None
    x, y, w, h = (_num(b.get(k)) for k in ("x", "y", "w", "h"))
    if x is None or y is None or w is None or h is None:
        return None
    return x, y, x + w, y + h


def in_reach(body: Box, thing: Box) -> bool:
    return not (
        thing[2] < body[0] - REACH
        or thing[0] > body[2] + REACH
        or thing[3] < body[1] - REACH
        or thing[1] > body[3] + REACH
    )


def label(m: Minute) -> str | None:
    """A closed minute's kind (None: no frame at all in it)."""
    if not m.frames:
        return None
    if len(m.seen) < SEEN_SHARE * len(m.frames):
        return "away"
    if len(m.phone) >= VOTE_SHARE * len(m.seen):
        return "phone"
    if len(m.food) >= VOTE_SHARE * len(m.seen):
        return "eating"
    return "desk"


def _add(segments: tuple[tuple[str, int, int], ...], kind: str, start: int, end: int) -> tuple[
    tuple[str, int, int], ...
]:  # fmt: skip
    if segments and segments[-1][0] == kind and segments[-1][2] >= start:
        last = segments[-1]
        return (*segments[:-1], (kind, last[1], max(last[2], end)))
    return (*segments, (kind, start, end))


class ActivityCoach:
    id = ID
    tasks = TASKS

    def on_result(self, result: Mapping[str, Any], state: ActivityState | None) -> ActivityState:
        s = state or ActivityState()
        at_f = _num(result.get("at"))
        if at_f is None or not result.get("ok", True):
            return s
        at = int(at_f)
        if s.last is not None and at < s.last:
            return s  # a frame from the past changes nothing
        s = self._roll(s, at)
        m = s.minute or Minute(at // MINUTE)
        m = replace(m, frames=m.frames | {at})
        task = result.get("task")
        raw = result.get("data")
        data: Mapping[str, Any] = raw if isinstance(raw, Mapping) else {}
        if task == "pose":
            pts = data.get("points")
            box = body_box(pts) if isinstance(pts, Sequence) else None
            if box is not None:
                m = replace(m, seen=m.seen | {at})
                s = replace(s, reach=box, reach_at=at)
        elif task == "objects" and s.reach is not None and s.reach_at is not None:
            if at - s.reach_at <= 2:  # his box from this frame or the one before
                m = self._things(m, at, data, s.reach)
        first = s.first if s.first is not None else at
        return replace(s, first=first, last=at, minute=m)

    @staticmethod
    def _things(m: Minute, at: int, data: Mapping[str, Any], reach: Box) -> Minute:
        things = data.get("objects")
        if not isinstance(things, Sequence):
            return m
        for t in things:
            if not isinstance(t, Mapping):
                continue
            box = _thing_box(t)
            if box is None or not in_reach(reach, box):
                continue
            if t.get("label") in PHONE:
                m = replace(m, phone=m.phone | {at})
            elif t.get("label") in FOOD:
                m = replace(m, food=m.food | {at})
        return m

    @staticmethod
    def _roll(s: ActivityState, at: int) -> ActivityState:
        """Close the minute `at` has left, and fill a short gap after it as that minute's away."""
        m = s.minute
        if m is None or at // MINUTE == m.index:
            return s
        segments = s.segments
        kind = label(m)
        if kind is not None:
            segments = _add(segments, kind, m.index * MINUTE, (m.index + 1) * MINUTE)
        gap_from = (m.index + 1) * MINUTE
        gap_to = (at // MINUTE) * MINUTE
        if gap_to > gap_from and s.last is not None and at - s.last <= GAP_FILL_S:
            segments = _add(segments, "away", gap_from, gap_to)  # frames went missing
        return replace(s, minute=None, segments=_capped(segments))

    def summary(self, state: ActivityState | None) -> Summary:
        s = state or ActivityState()
        segments = s.segments
        if s.minute is not None and (kind := label(s.minute)) is not None and s.last is not None:
            segments = _add(segments, kind, s.minute.index * MINUTE, s.last + 1)
        segments = _capped(segments)
        return {"view": _view(segments), "tally": _tally(s, segments)}


def _capped(segments: tuple[tuple[str, int, int], ...]) -> tuple[tuple[str, int, int], ...]:
    """At most MAX_SEGMENTS: the shortest stretch takes its longer neighbour's kind."""
    out = list(segments)
    while len(out) > MAX_SEGMENTS:
        i = min(range(len(out)), key=lambda k: out[k][2] - out[k][1])
        if i == 0:
            j = 1
        elif i == len(out) - 1:
            j = i - 1
        else:
            j = i - 1 if out[i - 1][2] - out[i - 1][1] >= out[i + 1][2] - out[i + 1][1] else i + 1
        kind = out[j][0]
        merged = (kind, min(out[i][1], out[j][1]), max(out[i][2], out[j][2]))
        lo, hi = min(i, j), max(i, j)
        out[lo : hi + 1] = [merged]
        if lo > 0 and out[lo - 1][0] == kind and out[lo - 1][2] >= merged[1]:
            out[lo - 1 : lo + 1] = [(kind, out[lo - 1][1], merged[2])]
    return tuple(out)


def _view(segments: tuple[tuple[str, int, int], ...]) -> list[dict[str, Any]]:
    if not segments:
        return [{"kind": "paused", "why": "Not looking yet."}]
    kind, start, end = segments[-1]
    desk = sum(e - s for k, s, e in segments if k != "away")
    return [
        {"kind": "line", "text": WORDS[kind]},
        {"kind": "timer", "s": end - start, "word": kind},
        {"kind": "big", "n": round(desk / 60), "word": "minutes at the desk"},
    ]


def _tally(s: ActivityState, segments: tuple[tuple[str, int, int], ...]) -> dict[str, Any] | None:
    if s.first is None or s.last is None or not segments:
        return None
    return {
        "started_at": s.first,
        "ended_at": max(s.last, segments[-1][2]),
        "segments": [{"kind": k, "start": a, "end": b} for k, a, b in segments],
    }


def create() -> ActivityCoach:
    """The registry's factory (`jarvis.coach.home.REGISTRY["activity"]`, wired at the I1 join)."""
    return ActivityCoach()


__all__ = [
    "FOOD",
    "ID",
    "KINDS",
    "MAX_SEGMENTS",
    "PHONE",
    "TASKS",
    "WORDS",
    "ActivityCoach",
    "ActivityState",
    "body_box",
    "create",
    "in_reach",
    "label",
]
