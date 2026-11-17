# scripts/mannequin/measure.py
#
# Copyright (C) 2025 NAVER Corp. (the waist vertex loop WAIST_LOOP below)
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may not use this file except
# in compliance with the License. You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software distributed under the License
# is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express
# or implied. See the License for the specific language governing permissions and limitations under
# the License.
#
# NOTICE: WAIST_LOOP is the waist vertex loop of naver/anny's src/anny/anthropometry.py (Apache-2.0,
# NAVER Corp.), copied unchanged; everything else in this file is JARVIS's (changed: new code).
"""R13.1 Part B (docs/plans/r13-1-try-on.md D3, H3): the mannequin's six measurements (cm) on the
posed body, the Newton solve that finds the shape for six wanted measurements, and the small
"measure rig" (points and torso edges) that lets a test measure a built file without this module."""

from __future__ import annotations

from typing import Any

import numpy as np
from scipy.spatial import ConvexHull

from .core import NBODY, Human
from .mesh import Arr
from .pose import Head, pose

MEASURES = ("height", "shoulders", "chest", "waist", "hips", "inseam")
MORPHS = (*MEASURES, "waist_down")
SAMPLE = {"height": 172, "shoulders": 44, "chest": 96, "waist": 82, "hips": 96, "inseam": 79}
RANGES = {
    "height": (150, 195),
    "shoulders": (36, 54),
    "chest": (76, 124),
    "waist": (62, 120),
    "hips": (78, 126),
    "inseam": (66, 92),
}
CHEST_AT, HIPS_AT = 0.53, 0.36  # the tape levels: waist -> shoulders, crotch -> waist
WAIST_LOOP = [
    4121,
    10763,
    10760,
    10757,
    10777,
    10776,
    10779,
    10780,
    10778,
    10781,
    10771,
    10773,
    10772,
    10775,
    10774,
    10814,
    10834,
    10816,
    10817,
    10818,
    10819,
    10820,
    10821,
    4181,
    4180,
    4179,
    4178,
    4177,
    4176,
    4175,
    4196,
    4173,
    4131,
    4132,
    4129,
    4130,
    4128,
    4138,
    4135,
    4137,
    4136,
    4133,
    4134,
    4108,
    4113,
    4118,
]


def hull_girth(pts: Arr) -> float:
    """The perimeter of the convex hull of 2-D points (a tape pulled round them)."""
    return float(ConvexHull(pts).area)  # a 2-D hull's "area" is its perimeter


def cut_points(p: Arr, edges: Arr, y: float) -> Arr:
    """Where the edges cross height y, as (x, z) points."""
    a, b = p[edges[:, 0]], p[edges[:, 1]]
    m = (a[:, 1] - y) * (b[:, 1] - y) < 0
    a, b = a[m], b[m]
    t = ((y - a[:, 1]) / (b[:, 1] - a[:, 1]))[:, None]
    return (a + t * (b - a))[:, [0, 2]]


def loop_length(p: Arr) -> float:
    """The length of a closed loop through the points, in order."""
    return float(np.linalg.norm(np.roll(p, 1, 0) - p, axis=1).sum())


def six(top: float, floor: float, sh: Arr, waist: Arr, mid: Arr, p: Arr, edges: Arr) -> Arr:
    """The six measurements (cm) from the rig's points: the head's top and the floor, the two
    shoulder landmarks, the waist loop, the mid-line points and the torso's edges."""
    wy = float(waist[:, 1].mean())
    crotch = float(mid[mid[:, 1] < wy][:, 1].min())
    shy = float(sh[:, 1].mean())
    chest = hull_girth(cut_points(p, edges, wy + CHEST_AT * (shy - wy)))
    hips = hull_girth(cut_points(p, edges, crotch + HIPS_AT * (wy - crotch)))
    shw = float(np.linalg.norm(sh[0] - sh[1]))
    return np.array([top - floor, shw, chest, loop_length(waist), hips, crotch - floor]) * 100


class Measurer:
    """Measures a shape as it is DRAWN (posed, the head softened: `drawn`). `torso` are the body's
    edges away from the arms; the shoulder landmarks are the top surface points just outside each
    shoulder joint."""

    def __init__(self, h: Human) -> None:
        self.h = h
        self.head = Head(h)
        arm = h.wsum(h.subtree("upperarm01.L") + h.subtree("upperarm01.R"))
        q = h.Q[h.G == "body"]
        quad_e = np.concatenate([q[:, [0, 1]], q[:, [1, 2]], q[:, [2, 3]], q[:, [3, 0]]])
        e = np.unique(np.sort(quad_e, 1), axis=0)
        self.torso = e[(arm[e] < 0.35).all(1)]
        vn = h.rest(np.zeros(6))
        self.sh = np.array([self._landmark(vn, sd, s) for sd, s in (("L", 1), ("R", -1))])
        mid = h.gidx("Mid")
        self.mid = mid[mid < NBODY]

    def _landmark(self, vn: Arr, side: str, s: int) -> int:
        j = self.h.head(vn, "upperarm01." + side)
        b = vn[:NBODY]
        m = (np.abs(b[:, 0] - (j[0] + 0.012 * s)) < 0.012) & (np.abs(b[:, 2] - j[2]) < 0.03)
        cand = np.where(m & (b[:, 1] > j[1]))[0]
        return int(cand[np.argmax(b[cand, 1])])

    def levels(self, p: Arr) -> tuple[float, float, float]:
        """Crotch, waist and shoulder heights (m) of a posed shape."""
        wy = float(p[WAIST_LOOP, 1].mean())
        mb = p[self.mid]
        return float(mb[mb[:, 1] < wy][:, 1].min()), wy, float(p[self.sh, 1].mean())

    def measure(self, p: Arr) -> Arr:
        """The six measurements (cm) of posed points (any floor: the body's lowest point)."""
        b = p[:NBODY, 1]
        return six(
            float(b.max()), float(b.min()), p[self.sh], p[WAIST_LOOP], p[self.mid], p, self.torso
        )

    def drawn(self, a: Arr) -> Arr:
        """The points of shape `a` that are drawn: posed, then the head softened."""
        return self.head.body(pose(self.h, self.h.rest(a)).P)

    def of_shape(self, a: Arr) -> Arr:
        return self.measure(self.drawn(a))


def solve(f: Any, target: Arr, a0: Arr, iters: int = 5, step: float = 0.02) -> Arr:
    """Newton steps on the six shape numbers until f(a) is the target (each within 0.02)."""
    a = np.array(a0, float)
    n = len(a)
    for _ in range(iters):
        m = f(a)
        if np.abs(m - target).max() < 0.02:
            break
        jac = np.zeros((n, n))
        for j in range(n):
            d = np.zeros(n)
            d[j] = step
            jac[:, j] = (f(a + d) - m) / step
        a = a + np.linalg.solve(jac, target - m)
    return a


def weights_of(values: dict[str, float]) -> dict[str, float]:
    """The seven morph weights for six measurements (the server's `morph_weights`, the one rule:
    (v - sample) / (top - sample); a waist below the sample uses `waist_down` alone)."""
    out = {m: (values[m] - SAMPLE[m]) / (RANGES[m][1] - SAMPLE[m]) for m in MEASURES}
    out["waist_down"] = 0.0
    if values["waist"] < SAMPLE["waist"]:
        out["waist_down"] = (SAMPLE["waist"] - values["waist"]) / (
            SAMPLE["waist"] - RANGES["waist"][0]
        )
        out["waist"] = 0.0
    return out


def table_cases() -> list[tuple[str, dict[str, float]]]:
    """The measure table's rows: the sample, 12 slider ends, 4 mid points, 2 mixed cases."""
    rows: list[tuple[str, dict[str, float]]] = [("sample", dict(SAMPLE))]
    for k in MEASURES:
        rows.append((f"{k} min", {**SAMPLE, k: RANGES[k][0]}))
        rows.append((f"{k} max", {**SAMPLE, k: RANGES[k][1]}))
    for k, v in (("height", 161), ("chest", 110), ("waist", 72), ("waist", 101)):
        rows.append((f"{k} {v}", {**SAMPLE, k: v}))
    rows.append(
        ("tall + heavy", dict(height=190, shoulders=48, chest=108, waist=110, hips=110, inseam=86))
    )
    rows.append(
        ("short + slim", dict(height=158, shoulders=40, chest=84, waist=68, hips=86, inseam=72))
    )
    return rows


def rig_of(ms: Measurer, shapes: list[Arr], margin: float = 0.05) -> dict[str, Arr]:
    """The measure rig: the body vertices a file needs so a test can measure it (the shoulder
    landmarks, the waist loop in order, the mid-line below the waist, and the torso edges that can
    cross the chest or hips tape in any of `shapes`, with a margin)."""
    keep = np.zeros(len(ms.torso), bool)
    for p in shapes:
        crotch, wy, shy = ms.levels(p)
        lo, hi = p[ms.torso[:, 0], 1], p[ms.torso[:, 1], 1]
        for y in (wy + CHEST_AT * (shy - wy), crotch + HIPS_AT * (wy - crotch)):
            keep |= (np.minimum(lo, hi) < y + margin) & (np.maximum(lo, hi) > y - margin)
    wy0 = float(shapes[0][WAIST_LOOP, 1].mean())
    mid = ms.mid[shapes[0][ms.mid, 1] < wy0 + 0.02]
    return {"shoulders": ms.sh, "waist": np.array(WAIST_LOOP), "mid": mid, "edges": ms.torso[keep]}


RIG_PARTS = ("ends", "shoulders", "waist", "mid")


def rig_ids(ms: Measurer, shapes: list[Arr]) -> tuple[Arr, Arr, dict[str, list[int]]]:
    """The rig as (body vertex ids, line pairs into them, each section's [first, count]); the
    `ends` are the body's highest and lowest points in any of `shapes`."""
    rig = rig_of(ms, shapes)
    ends = np.unique([f(p[:NBODY, 1]) for p in shapes for f in (np.argmax, np.argmin)])
    parts = dict(ends=ends, shoulders=rig["shoulders"], waist=rig["waist"], mid=rig["mid"])
    sections, ids = {}, []
    for k in RIG_PARTS:
        sections[k] = [sum(len(i) for i in ids), len(parts[k])]
        ids.append(np.asarray(parts[k]))
    ev = np.unique(rig["edges"])
    re = np.full(int(ev.max()) + 1, -1)
    re[ev] = np.arange(len(ev)) + sum(len(i) for i in ids)
    return np.concatenate([*ids, ev]), re[rig["edges"]], sections


def rig_measure(mesh: dict[str, Any], weights: dict[str, float]) -> Arr:
    """The six measurements (cm) of a rig mesh (as glb.read_glb gives it) under morph weights."""
    p = np.array(mesh["x"], float)
    for name, d in mesh["targets"].items():
        p = p + weights.get(name, 0.0) * d
    sec = {k: p[a : a + n] for k, (a, n) in mesh["extras"]["sections"].items()}
    ends = sec["ends"][:, 1]
    edges = np.asarray(mesh["index"]).reshape(-1, 2)
    return six(
        float(ends.max()), float(ends.min()), sec["shoulders"], sec["waist"], sec["mid"], p, edges
    )
