# scripts/mannequin/carry.py
"""R13.1 Part B (docs/plans/r13-1-try-on.md D3, D6; review B-1, finding 6): how a garment moves
when the body changes shape. It is not made again at each shape: the body CARRIES it."""

from __future__ import annotations

from typing import Any

import numpy as np
from scipy.spatial import cKDTree

from .mesh import Arr, tri_of, vnormals
from .pose import rot_between

CARRY_K, CARRY_REACH = 12, 0.015  # the nearest of 12 triangles carries a point; its reach (m)


class Carrier:
    """How a garment moves when the body changes shape (review B-1, finding 6). A garment made
    afresh at each solved shape is a non-linear function of the body, so between and beyond the
    solved shapes (a morph weight below 0: the low end of every slider) an inner layer could
    come through its cover. Instead every garment point is CARRIED by the body and helper points
    it lies on at the sample: it takes their displacement, and its small offset from them turns
    with their surface. Two layers that are nested at the sample move together and stay nested
    at every mix of the seven morphs."""

    def __init__(self, fig: Any, sample: Arr) -> None:
        self.tris = tri_of(fig.Qt)  # the helper mesh every garment is cut from (neck to toe)
        self.ids = np.unique(self.tris)
        self.sample = sample
        self.normal = vnormals(sample, self.tris)
        self.tree = cKDTree(sample[self.tris].mean(1))  # the carrying triangles, by their middles
        self._w: dict[str, tuple[Arr, Arr]] = {}
        self._turn: dict[int, Arr] = {}

    def weights(self, name: str, x: Arr, ride: Arr | None) -> tuple[Arr, Arr]:
        """For each point of a part: the three points that carry it and their shares: the
        corners of the body or helper triangle it lies nearest to, by where it lies on it (so a
        stretch of the body stretches the cloth evenly). The first len(ride) points are a shell
        cut from the helper mesh: each rides its OWN vertex alone (the nearest triangle could be
        the arm's beside the ribs, or the other leg's), unless the making moved it away from
        that vertex (a tail folded up)."""
        if name not in self._w:
            _, cand = self.tree.query(x, k=CARRY_K)
            corners = self.sample[self.tris[cand]]  # (points, candidates, 3 corners, xyz)
            a = corners[:, :, 0]
            v0, v1 = corners[:, :, 1] - a, corners[:, :, 2] - a
            v2 = x[:, None, :] - a
            d00, d01, d11 = (v0 * v0).sum(-1), (v0 * v1).sum(-1), (v1 * v1).sum(-1)
            d20, d21 = (v2 * v0).sum(-1), (v2 * v1).sum(-1)
            den = np.maximum(d00 * d11 - d01 * d01, 1e-18)
            v, w = (d11 * d20 - d01 * d21) / den, (d00 * d21 - d01 * d20) / den
            bc = np.clip(np.stack([1 - v - w, v, w], -1), 0, None)
            bc = bc / bc.sum(-1, keepdims=True)  # the nearest place ON each triangle, nearly
            gap = np.linalg.norm(x[:, None, :] - (bc[..., None] * corners).sum(-2), axis=-1)
            rows, best = np.arange(len(x)), gap.argmin(1)
            idx, share = self.tris[cand[rows, best]].copy(), bc[rows, best].copy()
            if ride is not None:
                src = np.asarray(ride)
                own = np.linalg.norm(x[: len(src)] - self.sample[src], axis=1) < CARRY_REACH
                idx[: len(src)][own] = src[own, None]
                share[: len(src)][own] = 1.0 / 3
            self._w[name] = (idx, share)
        return self._w[name]

    def turn(self, shape: Arr) -> Arr:
        """Each carrying point's own frame from the sample to `shape`: its surface normal's
        rotation, times how much the surface round it grew (the root of its area's ratio)."""
        key = id(shape)
        if key not in self._turn:
            n1 = vnormals(shape, self.tris)
            grow = np.sqrt(self.area(shape) / np.maximum(self.area(self.sample), 1e-12))
            r = np.tile(np.eye(3), (len(shape), 1, 1))
            for i in self.ids:
                r[i] = grow[i] * rot_between(self.normal[i], n1[i])
            self._turn[key] = r
        return self._turn[key]

    def area(self, p: Arr) -> Arr:
        """The area of the carrying triangles round each point."""
        t = self.tris
        a = 0.5 * np.linalg.norm(np.cross(p[t[:, 1]] - p[t[:, 0]], p[t[:, 2]] - p[t[:, 0]]), axis=1)
        out = np.zeros(len(p))
        for k in range(3):
            np.add.at(out, t[:, k], a)
        return out

    def carried(self, name: str, x: Arr, shape: Arr, ride: Arr | None = None) -> Arr:
        """The displacement of part `name` (its sample points `x`) when the body is at `shape`:
        the carrying points' own, plus what their frames do to the point's offset from each (an
        offset over CARRY_REACH is cloth hanging free of the body: its turning fades out by twice
        the reach, and only the growing is left)."""
        idx, w = self.weights(name, x, ride)
        off = x[:, None, :] - self.sample[idx]
        near = np.clip(2 - np.linalg.norm(off, axis=2) / CARRY_REACH, 0, 1)[:, :, None]
        frames = self.turn(shape)[idx]
        grown = np.cbrt(np.abs(np.linalg.det(frames)))[:, :, None] * off
        framed = np.einsum("nkij,nkj->nki", frames, off)
        moved = (shape - self.sample)[idx] + near * framed + (1 - near) * grown - off
        return np.einsum("nk,nkc->nc", w, moved)
