# scripts/mannequin/pose.py
"""R13.1 Part B (docs/plans/r13-1-try-on.md D3): the mannequin's pose: relaxed standing, arms down
a little away from the hips, feet on the floor (linear blend skinning with the standard rig); and
its head (`Head`): the eye sockets filled and the face softened, which is the body that is DRAWN
and therefore the body that is measured and solved (review B-1, finding 1)."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .core import NBODY, Human
from .mesh import Arr, avg_matrix, smoothstep, tri_of


def rot_axis(k: Arr, ang: float) -> Arr:
    """Rotation by `ang` about the axis k."""
    k = np.asarray(k, float) / np.linalg.norm(k)
    m = np.array([[0, -k[2], k[1]], [k[2], 0, -k[0]], [-k[1], k[0], 0]])
    return np.eye(3) + np.sin(ang) * m + (1 - np.cos(ang)) * m @ m


def rot_between(a: Arr, b: Arr) -> Arr:
    """The smallest rotation taking direction a to direction b."""
    a, b = a / np.linalg.norm(a), b / np.linalg.norm(b)
    v, c = np.cross(a, b), float(a @ b)
    s = float(np.linalg.norm(v))
    if s < 1e-9:
        return np.eye(3)
    return rot_axis(v / s, float(np.arctan2(s, c)))


def part_turn(r: Arr, frac: float) -> Arr:
    """A fraction of the rotation r (about its own axis)."""
    ang = float(np.arccos(np.clip((np.trace(r) - 1) / 2, -1, 1)))
    if ang < 1e-9:
        return np.eye(3)
    k = np.array([r[2, 1] - r[1, 2], r[0, 2] - r[2, 0], r[1, 0] - r[0, 1]]) / (2 * np.sin(ang))
    return rot_axis(k, ang * frac)


@dataclass(frozen=True)
class Posed:
    """A posed shape: its points (feet on y = 0), each bone's (rotation, shift) and the floor."""

    P: Arr
    M: dict[str, tuple[Arr, Arr]]
    floor: float


def wanted(h: Human, v: Arr) -> dict[str, Arr]:
    """The world rotation wanted for the bones that leave the rest pose (children inherit)."""
    want: dict[str, Arr] = {}
    for s, sd in ((1, "L"), (-1, "R")):
        sh, el, wr = (
            h.head(v, "upperarm01." + sd),
            h.head(v, "lowerarm01." + sd),
            h.head(v, "wrist." + sd),
        )
        up = np.array([np.sin(np.radians(12.5)) * s, -np.cos(np.radians(12.5)), 0.03])
        rt = rot_between(el - sh, up)
        want["shoulder01." + sd] = part_turn(rt, 0.22)
        want["upperarm01." + sd] = rt
        fore = np.array([np.sin(np.radians(7)) * s, -np.cos(np.radians(7)), 0.2])
        re = rot_between(rt @ (wr - el), fore) @ rt
        want["lowerarm01." + sd] = re
        f = fore / np.linalg.norm(fore)
        want["lowerarm02." + sd] = rot_axis(f, np.radians(-18 * s)) @ re
        want["wrist." + sd] = rot_axis(f, np.radians(-36 * s)) @ re
        want["upperleg01." + sd] = rot_axis(np.array([0, 0, 1.0]), np.radians(-5.0 * s))
        want["foot." + sd] = np.eye(3)
    return want


def pose(h: Human, v: Arr) -> Posed:
    """Pose the unposed shape v."""
    want = wanted(h, v)
    m: dict[str, tuple[Arr, Arr]] = {}
    rw: dict[str, Arr] = {}
    p = np.zeros_like(v)
    for b in h.order:
        par = h.parent[b]
        rp, mp = (rw[par], m[par]) if par else (np.eye(3), (np.eye(3), np.zeros(3)))
        r = want.get(b, rp)
        rw[b] = r
        hd = h.head(v, b)
        m[b] = (r, mp[0] @ hd + mp[1] - r @ hd)  # the joint stays where its parent put it
        col = h.Wc[:, h.bi[b]]
        if col.nnz:
            idx = col.indices
            p[idx] += col.data[:, None] * (v[idx] @ r.T + m[b][1])
    floor = float(p[:NBODY, 1].min())
    p[:, 1] -= floor
    return Posed(P=p, M=m, floor=floor)


def posed_joint(h: Human, v: Arr, posed: Posed, bone: str) -> Arr:
    """Where a bone's head sits in the posed shape."""
    r, t = posed.M[bone]
    p = r @ h.head(v, bone) + t
    p[1] -= posed.floor
    return p


class Head:
    """The mannequin's head. `body(p)` turns posed points into the points that are drawn: the eye
    sockets filled, the face softened. Softening lowers the crown by about 1.4 cm, so the height
    is measured (and the shape solved) on THESE points, never on the posed ones."""

    def __init__(self, h: Human) -> None:
        self.h = h
        self.w = h.wsum(h.subtree("neck02"))
        self.avg = avg_matrix(len(h.V0), tri_of(h.Q[h.G == "body"]))

    def body(self, p: Arr) -> Arr:
        h, x = self.h, p.copy()
        for g in ("helper-l-eye", "helper-r-eye"):
            e = p[h.gidx(g)]
            c = e.mean(0)
            r = np.linalg.norm(e - c, axis=1).mean() * 1.06
            b = x[:NBODY]
            d2 = (b[:, 0] - c[0]) ** 2 + (b[:, 1] - c[1]) ** 2
            m = (d2 < (0.97 * r) ** 2) & (b[:, 2] > c[2] - 1.6 * r) & (self.w[:NBODY] > 0.5)
            dome = c[2] + np.sqrt(np.maximum(r * r - d2, 0))
            b[m, 2] = np.maximum(b[m, 2], dome[m])
        w = (smoothstep(0.5, 1.0, self.w) * 0.7)[:, None]
        for _ in range(8):
            x[:NBODY] = (x + w * (self.avg @ x - x))[:NBODY]
        return x
