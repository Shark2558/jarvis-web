# scripts/mannequin/mesh.py
"""R13.1 Part B (docs/plans/r13-1-try-on.md D3): small mesh helpers for the mannequin build:
triangles of quads, normals, smoothing, frames, cross-section radii, lofts through rings, boxes and
discs, cylindrical UVs in metres. Pure numpy/scipy; no file is read here."""

from __future__ import annotations

from typing import Any

import numpy as np
import scipy.sparse as sp
import scipy.sparse.csgraph  # noqa: F401  (sp.csgraph)

Arr = Any  # a numpy array (the build is a dev tool: shapes are said in the docstrings)
Frame = tuple[Arr, Arr, Arr, Arr]  # origin, e1 (side), e2 (axis), e3 (front)
UP = np.array([0.0, 1.0, 0.0])


def tri_of(q: Arr) -> Arr:
    """(n, 4) quads -> (2n, 3) triangles."""
    q = np.asarray(q)
    return np.concatenate([q[:, [0, 1, 2]], q[:, [0, 2, 3]]])


def edges_of(t: Arr) -> tuple[Arr, Arr]:
    """Unique undirected edges of triangles, and how many triangles share each."""
    e = np.concatenate([t[:, [0, 1]], t[:, [1, 2]], t[:, [2, 0]]])
    return np.unique(np.sort(e, 1), axis=0, return_counts=True)


def vnormals(x: Arr, t: Arr) -> Arr:
    """Area-weighted vertex normals."""
    n = np.cross(x[t[:, 1]] - x[t[:, 0]], x[t[:, 2]] - x[t[:, 0]])
    out = np.zeros_like(x)
    for k in range(3):
        np.add.at(out, t[:, k], n)
    return out / np.maximum(np.linalg.norm(out, axis=1, keepdims=True), 1e-12)


def avg_matrix(n: int, t: Arr) -> Arr:
    """Sparse operator: each vertex -> the mean of its edge neighbours."""
    e, _ = edges_of(t)
    a = sp.coo_matrix((np.ones(len(e)), (e[:, 0], e[:, 1])), shape=(n, n))
    a = (a + a.T).tocsr()
    d = np.asarray(a.sum(1)).ravel()
    return sp.diags(1 / np.maximum(d, 1)) @ a


def taubin(x: Arr, a: Arr, iters: int, lam: float = 0.5, mu: float = -0.53) -> Arr:
    """Taubin smoothing (no shrink): `iters` rounds of a lambda and a mu step."""
    for _ in range(iters):
        x = x + lam * (a @ x - x)
        x = x + mu * (a @ x - x)
    return x


def boundary_verts(t: Arr) -> Arr:
    """The vertices on an open edge."""
    e, c = edges_of(t)
    return np.unique(e[c == 1])


def boundary_smoother(n: int, t: Arr) -> Arr:
    """Sparse operator sliding each open-edge vertex halfway to its two neighbours on the edge."""
    e, c = edges_of(t)
    b = e[c == 1]
    a = sp.coo_matrix((np.ones(len(b)), (b[:, 0], b[:, 1])), shape=(n, n))
    a = (a + a.T).tocsr()
    d = np.asarray(a.sum(1)).ravel()
    on = d > 0
    s = sp.diags(np.where(on, 0.5, 1.0)) + sp.diags(np.where(on, 0.5 / np.maximum(d, 1), 0.0)) @ a
    return s.tocsr()


def slide_boundary(x: Arr, t: Arr, s: Arr, iters: int) -> Arr:
    """Smooth the open edges along the surface only (they never dip under it)."""
    n = vnormals(x, t)
    for _ in range(iters):
        d = s @ x - x
        x = x + d - (d * n).sum(1, keepdims=True) * n
    return x


def frame(o: Arr, axis: Arr, front: Arr = (0.0, 0.0, 1.0)) -> Frame:
    """A frame at `o` whose e2 is `axis` and whose e3 is `front` made square to it."""
    e2 = np.asarray(axis, float)
    e2 = e2 / np.linalg.norm(e2)
    f = np.asarray(front, float)
    e3 = f - (f @ e2) * e2
    e3 = e3 / np.linalg.norm(e3)
    return np.asarray(o, float), np.cross(e2, e3), e2, e3


def local(x: Arr, fr: Frame) -> Arr:
    o, e1, e2, e3 = fr
    return (x - o) @ np.stack([e1, e2, e3]).T


def world(loc: Arr, fr: Frame) -> Arr:
    o, e1, e2, e3 = fr
    return o + loc @ np.stack([e1, e2, e3])


def _crossings(loc: Arr, t: Arr, h: float, rmax: float | None) -> tuple[Arr, Arr]:
    """The segments where triangles cross local height h, as 2-D (side, front) end points."""
    s = (loc[:, 1] - h)[t]
    pts, msk = [], []
    for i, j in ((0, 1), (1, 2), (2, 0)):
        si, sj = s[:, i], s[:, j]
        m = si * sj < 0
        w = np.where(m, si / np.where(m, si - sj, 1), 0)[:, None]
        a, b = loc[t[:, i]][:, [0, 2]], loc[t[:, j]][:, [0, 2]]
        pts.append(a + w * (b - a))
        msk.append(m)
    mk, pt = np.stack(msk, 1), np.stack(pts, 1)
    ok = mk.sum(1) == 2
    mk, pt = mk[ok], pt[ok]
    rows = np.arange(len(pt))
    a, b = pt[rows, mk.argmax(1)], pt[rows, 2 - mk[:, ::-1].argmax(1)]
    if rmax is not None:
        k = (np.linalg.norm(a, axis=1) < rmax) & (np.linalg.norm(b, axis=1) < rmax)
        a, b = a[k], b[k]
    return a, b


def slice_r(x: Arr, t: Arr, fr: Frame, h: float, thetas: Arr, rmax: float | None = None) -> Arr:
    """The outer radius of the mesh's cross-section at local height h, for each angle (0 = e3,
    towards +e1). Angles that hit nothing are filled in from their neighbours."""
    a, b = _crossings(local(x, fr), t, h, rmax)
    e = b - a
    out = np.full(len(thetas), np.nan)
    for n, th in enumerate(np.asarray(thetas, float)):
        d = np.array([np.sin(th), np.cos(th)])
        den = d[0] * e[:, 1] - d[1] * e[:, 0]
        den = np.where(np.abs(den) < 1e-12, 1e-12, den)
        r = (a[:, 0] * e[:, 1] - a[:, 1] * e[:, 0]) / den
        u = (a[:, 0] * d[1] - a[:, 1] * d[0]) / den
        v = (u >= -1e-6) & (u <= 1 + 1e-6) & (r > 0)
        if v.any():
            out[n] = r[v].max()
    bad = np.isnan(out)
    if bad.all():
        raise RuntimeError("empty slice")
    if bad.any():
        idx = np.arange(len(out))
        out[bad] = np.interp(idx[bad], idx[~bad], out[~bad], period=len(out))
    return out


def ring_pts(fr: Frame, h: Arr | float, thetas: Arr, r: Arr | float) -> Arr:
    """Points at local height h (a number or one per angle) and radius r around a frame's axis."""
    th = np.asarray(thetas, float)
    hh = np.broadcast_to(np.asarray(h, float), th.shape)
    rr = np.broadcast_to(np.asarray(r, float), th.shape)
    return world(np.stack([rr * np.sin(th), hh, rr * np.cos(th)], 1), fr)


def loft(rings: list[Arr], closed: bool = True, cap_end: bool = False) -> tuple[Arr, Arr]:
    """Triangles through a list of (n, 3) rings (a fixed topology). Returns (points, triangles)."""
    n, m = len(rings[0]), len(rings)
    x = np.concatenate(rings)
    t = []
    for i in range(m - 1):
        for j in range(n if closed else n - 1):
            a, b = i * n + j, i * n + (j + 1) % n
            t += [[a, b, b + n], [a, b + n, a + n]]
    tri = np.array(t)
    if cap_end:
        c = len(x)
        x = np.concatenate([x, rings[-1].mean(0, keepdims=True)])
        base = (m - 1) * n
        tri = np.concatenate([tri, [[base + j, base + (j + 1) % n, c] for j in range(n)]])
    return x, tri


def loft_uv(rings: list[Arr], cap_end: bool = False) -> Arr:
    """UVs in metres for a loft: u along the first ring, v along the rings."""
    n, m = len(rings[0]), len(rings)
    seg = np.linalg.norm(np.roll(rings[0], -1, 0) - rings[0], axis=1)
    u = np.concatenate([[0], np.cumsum(seg)[:-1]])
    steps = [np.linalg.norm(rings[i + 1] - rings[i], axis=1).mean() for i in range(m - 1)]
    v = np.concatenate([[0], np.cumsum(steps)])
    uv = np.stack([np.tile(u, m), np.repeat(v, n)], 1)
    return np.concatenate([uv, [[0, v[-1]]]]) if cap_end else uv


_BOX_T = [
    [0, 2, 1],
    [1, 2, 3],
    [4, 5, 6],
    [5, 7, 6],
    [0, 1, 4],
    [1, 5, 4],
    [2, 6, 3],
    [3, 6, 7],
    [0, 4, 2],
    [2, 4, 6],
    [1, 3, 5],
    [3, 7, 5],
]


def box(c: Arr, axes: tuple[Arr, Arr, Arr], size: tuple[float, float, float]) -> tuple[Arr, Arr]:
    """A box centred at c along three axes, with the three sizes."""
    (ax, ay, az), (sx, sy, sz) = axes, size
    p = [
        c + ax * dx * sx / 2 + ay * dy * sy / 2 + az * dz * sz / 2
        for dz in (-1, 1)
        for dy in (-1, 1)
        for dx in (-1, 1)
    ]
    return np.array(p), np.array(_BOX_T)


def disc(
    c: Arr, n: Arr, t: Arr, r: float, h: float, seg: int = 10, dome: bool = True
) -> tuple[Arr, Arr]:
    """A button or a watch case: a disc of radius r and height h at c, facing n (t: a tangent)."""
    n = np.asarray(n, float) / np.linalg.norm(n)
    t = np.asarray(t, float) - (np.asarray(t, float) @ n) * n
    t = t / np.linalg.norm(t)
    b = np.cross(n, t)
    a = np.arange(seg) / seg * 2 * np.pi
    circ = np.cos(a)[:, None] * t + np.sin(a)[:, None] * b
    rings = [
        c + circ * r,
        c + circ * r + n * h * (0.6 if dome else 1.0),
        c + circ * r * (0.7 if dome else 0.9) + n * h,
    ]
    return loft(rings, closed=True, cap_end=True)


def merge(parts: list[tuple[Arr, Arr]]) -> tuple[Arr, Arr]:
    """Several (points, triangles) as one."""
    xs, ts, off = [], [], 0
    for x, t in parts:
        xs.append(x)
        ts.append(t + off)
        off += len(x)
    return np.concatenate(xs), np.concatenate(ts)


def smoothstep(a: float | Arr, b: float | Arr, x: Arr | float) -> Arr:
    t = np.clip((np.asarray(x, float) - a) / (b - a), 0, 1)
    return t * t * (3 - 2 * t)


def circ_smooth(r: Arr, rounds: int) -> Arr:
    """Smooth a closed ring of radii (1-2-1 weights)."""
    for _ in range(rounds):
        r = 0.25 * np.roll(r, 1) + 0.5 * r + 0.25 * np.roll(r, -1)
    return r


def cyl_uv(x: Arr, t: Arr, fr: Frame, radius: float) -> Arr:
    """Per-corner cylindrical UVs about a frame, in metres at `radius`: (triangles, 3, 2)."""
    loc = local(x, fr)
    th = np.arctan2(loc[:, 0], loc[:, 2])
    c = loc[t].mean(1)
    thc = np.arctan2(c[:, 0], c[:, 2])
    tc = thc[:, None] + (th[t] - thc[:, None] + np.pi) % (2 * np.pi) - np.pi
    return np.stack([tc * radius, loc[:, 1][t]], 2)


def weld(t: Arr, cuv: Arr) -> tuple[Arr, Arr, Arr]:
    """Corner UVs -> export vertices (logical index, triangles, uv), split only on UV seams."""
    key = np.concatenate([t.reshape(-1, 1), np.round(cuv.reshape(-1, 2) * 2e4)], 1)
    uq, inv = np.unique(key, axis=0, return_inverse=True)
    inv = inv.reshape(-1)
    first = np.zeros(len(uq), int)
    first[inv] = np.arange(len(inv))
    return uq[:, 0].astype(int), inv.reshape(-1, 3), cuv.reshape(-1, 2)[first]


def orient_out(x: Arr, t: Arr, axis_z: float, strips: list[tuple[int, int]]) -> Arr:
    """Triangles wound so their normals point away from the figure, piece by piece: each connected
    piece is checked against its own middle, or (a flat band lying on the body, given as [first,
    count] point ranges in `strips`) against the trunk's axis; a piece that faces in is flipped."""
    n = len(x)
    e, _ = edges_of(t)
    graph = sp.coo_matrix((np.ones(len(e)), (e[:, 0], e[:, 1])), shape=(n, n))
    _, label = sp.csgraph.connected_components(graph, directed=False)
    strip = np.zeros(n, bool)
    for a, c in strips:
        strip[a : a + c] = True
    nrm = np.cross(x[t[:, 1]] - x[t[:, 0]], x[t[:, 2]] - x[t[:, 0]])
    mid = x[t].mean(1)
    piece = label[t[:, 0]]
    out = t.copy()
    for k in np.unique(piece):
        m = piece == k
        ref = x[label == k].mean(0)
        away = mid[m] - ref
        if strip[t[m][0, 0]]:
            away = mid[m] - np.stack([np.zeros(m.sum()), mid[m][:, 1], np.full(m.sum(), axis_z)], 1)
        if (nrm[m] * away).sum() < 0:
            out[m] = out[m][:, ::-1]
    return out
