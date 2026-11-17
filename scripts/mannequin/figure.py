# scripts/mannequin/figure.py
"""R13.1 Part B (docs/plans/r13-1-try-on.md D3, D6): the figure the garments are cut for.

`Figure` fixes, once, at the sample shape: the garment cuts of the CC0 `helper-tights` helper mesh,
and the body's regions. **The private zone (D6):** every body face deep under the base shorts or the
base vest is REMOVED here and never written to a file; the base shorts are always drawn and the vest
whenever no top is, so no layer state, slot set, variant or view can show the zone.
`Ctx` is one evaluation (one shape): the posed points, the joints and the parts made so far."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
from scipy.spatial import cKDTree

from .core import NBODY, Human
from .measure import Measurer
from .mesh import (
    UP,
    Arr,
    Frame,
    avg_matrix,
    boundary_verts,
    cyl_uv,
    frame,
    orient_out,
    smoothstep,
    taubin,
    tri_of,
    vnormals,
)
from .pose import Posed, pose, posed_joint

SOLE = 0.016  # the shoe's sole (m)
TH = np.arange(64) / 64 * 2 * np.pi
Cut = str | dict[str, Any]  # a cut's name, or a cut made elsewhere (the jacket's)
STRIPS = ("placket", "lapelL", "lapelR")  # flat bands lying on the trunk
BODY_PARTS = ("bodyCore", "bodyArms", "bodyShoulders", "bodyShins", "bodyThighs", "bodyFeet")


def joints(h: Human, ms: Measurer, v: Arr, posed: Posed) -> dict[str, Any]:
    """The landmarks a garment needs, for one posed shape."""
    crotch, waist, _ = ms.levels(posed.P)

    def pj(b: str) -> Arr:
        return posed_joint(h, v, posed, b)

    j: dict[str, Any] = dict(
        crotch=crotch,
        waist=waist,
        trouser_top=waist - 0.028,
        neck=pj("neck01"),
        head=pj("head"),
        scale=float(posed.P[:NBODY, 1].max()) / 1.72,
        zc=0.5 * (pj("spine03")[2] + pj("spine01")[2]),
    )
    names = (
        ("shoulder", "upperarm01."),
        ("elbow", "lowerarm01."),
        ("wrist", "wrist."),
        ("hip", "upperleg01."),
        ("knee", "lowerleg01."),
        ("ankle", "foot."),
    )
    for s in "LR":
        for key, bone in names:
            j[key + s] = pj(bone + s)
    return j


def along(p: Arr, a: Arr, b: Arr) -> Arr:
    """Each point's place along a -> b (0 at a, 1 at b)."""
    return (p - a) @ (b - a) / ((b - a) @ (b - a))


class Figure:
    """The cuts and the body regions, fixed at the sample shape `a0`."""

    def __init__(self, h: Human, ms: Measurer, a0: Arr) -> None:
        self.h, self.ms, self.a0 = h, ms, a0
        v = h.rest(a0)
        posed = pose(h, v)
        self.P0 = posed.P
        self.J0 = joints(h, ms, v, posed)
        self.Qt, self.Qb = h.Q[h.G == "helper-tights"], h.Q[h.G == "body"]
        self._weights()
        self.g: dict[str, dict[str, Any]] = {}
        for name, keep in self._cuts().items():
            self.g[name] = self._garment(self.Qt[keep[self.Qt].all(1)])
        self.g["vest"] = self._garment(self._scooped(self.g["vest"]["q"]))
        self.g["tee"] = self._garment(self._crew(self.g["tee"]["q"]))
        self.Abody = avg_matrix(len(self.P0), tri_of(self.Qb))
        self.body_q = self._regions()
        self.topo: dict[str, tuple[Arr, Arr | None]] = {}  # part -> triangles, corner or vertex UVs
        self.meta: dict[str, dict[str, Any]] = {}  # part -> extras for the file (ranges, rims)

    def _weights(self) -> None:
        h, p, j = self.h, self.P0, self.J0

        def ws(b: str) -> Arr:
            return h.wsum(h.subtree(b))

        self.wArm = {s: ws("upperarm01." + s) for s in "LR"}
        self.wArmAny = self.wArm["L"] + self.wArm["R"]
        self.wLeg = {s: ws("upperleg01." + s) for s in "LR"}
        self.wHead = h.wsum(h.subtree("neck02"))
        self.arm = self.wArmAny >= 0.5
        tf, tu = np.zeros(len(p)), np.full(len(p), 9.0)
        for s in "LR":  # tf: 0 at the elbow, 1 at the wrist; tu: 0 at the shoulder, 1 at the elbow
            on = self.wArm[s] >= 0.5
            tf = np.where(on, along(p, j["elbow" + s], j["wrist" + s]), tf)
            tu = np.where(on, along(p, j["shoulder" + s], j["elbow" + s]), tu)
        self.tf, self.tu = tf, tu

    def _cuts(self) -> dict[str, Arr]:
        j, y, arm, tf = self.J0, self.P0[:, 1], self.arm, self.tf
        tw, cr, wa, knee = j["trouser_top"], j["crotch"], j["waist"], j["kneeL"][1]
        return {
            "shirt": np.where(arm, tf <= 0.80, y >= cr + 0.012),
            "tee": np.where(arm, self.tu <= 0.62, y >= cr + 0.012),
            "jacket": np.where(arm, tf <= 0.76, y >= cr + 0.012),
            "trousers": (~arm) & (y <= tw + 0.012) & (y >= 0.035),
            "shortsG": (~arm) & (y <= tw + 0.012) & (y >= knee + 0.02),
            "vest": (~arm) & (y >= wa - 0.13),
            "shorts": (~arm) & (y <= wa - 0.03) & (y >= cr - 0.2),
            "shoes": (~arm) & (y <= 0.095),
            "socks": (~arm) & (y <= 0.27),
            "legs": ~arm & (y <= wa + 0.05),
        }

    def _scooped(self, q: Arr) -> Arr:
        """The vest's scoop neck and armholes."""
        j = self.J0
        c = self.P0[q].mean(1)
        nb = j["neck"] + np.array([0, 0.0, 0.01])
        scoop = np.linalg.norm((c - nb) * [1, 0.75, 1], axis=1) < 0.1
        capx = np.abs(c[:, 0]) > j["shoulderL"][0] - 0.035
        return q[~scoop & ~(capx & (c[:, 1] > j["shoulderL"][1] - 0.13))]

    def _crew(self, q: Arr) -> Arr:
        """The tee's round neck, at the base of the neck."""
        c = self.P0[q].mean(1)
        nb = self.J0["neck"] + np.array([0, 0.0, 0.012])
        return q[np.linalg.norm((c - nb) * [1, 0.8, 1], axis=1) >= 0.082]

    def _garment(self, q: Arr) -> dict[str, Any]:
        vid = np.unique(q)
        re = np.full(len(self.P0), -1)
        re[vid] = np.arange(len(vid))
        t = tri_of(re[q])
        return dict(q=q, vid=vid, T=t, A=avg_matrix(len(vid), t), bnd=boundary_verts(t))

    def _deep(self, names: tuple[str, ...], rings: int = 2) -> Arr:
        """Body vertices at least `rings` edges inside the union of some cuts (nothing of the
        body can show there while one of them is drawn)."""
        tv = np.unique(self.Qt)
        tall = tri_of(self.Qt)
        near = tv[cKDTree(self.h.rest(self.a0)[tv]).query(self.h.rest(self.a0)[:NBODY])[1]]
        at = avg_matrix(len(self.P0), tall)
        inside = np.zeros(len(self.P0), bool)
        for n in names:
            inside[self.g[n]["vid"]] = True
        out = np.zeros(len(self.P0))
        out[tv] = (~inside[tv]).astype(float)
        out[boundary_verts(tall)] = 1
        for _ in range(rings):
            out = np.maximum(out, (at @ out > 0).astype(float))
        return (out == 0)[near]

    def _regions(self) -> dict[str, Arr]:
        """The body's faces by what can cover them; the private zone is in none of them."""
        qb = self.Qb

        def faces(*names: str) -> Arr:
            return self._deep(names)[qb].all(1)

        gone = faces("vest", "shorts")  # D6: never written, never drawn
        self.removed = qb[gone]
        feet = faces("shoes") & ~gone
        thighs = faces("shortsG", "shorts") & ~gone & ~feet
        shins = faces("trousers", "shoes", "shorts") & ~gone & ~feet & ~thighs
        shoulders = faces("tee", "vest") & ~gone
        arms = faces("shirt", "vest") & ~gone & ~shoulders
        core = ~(gone | feet | thighs | shins | shoulders | arms)
        masks = dict(
            bodyCore=core,
            bodyArms=arms,
            bodyShoulders=shoulders,
            bodyShins=shins,
            bodyThighs=thighs,
            bodyFeet=feet,
        )
        return {k: qb[m] for k, m in masks.items()}

    def body(self, p: Arr) -> Arr:
        """The body's points: the eye sockets filled, the face softened into a mannequin head."""
        h, x = self.h, p.copy()
        for g in ("helper-l-eye", "helper-r-eye"):
            e = p[h.gidx(g)]
            c = e.mean(0)
            r = np.linalg.norm(e - c, axis=1).mean() * 1.06
            b = x[:NBODY]
            d2 = (b[:, 0] - c[0]) ** 2 + (b[:, 1] - c[1]) ** 2
            m = (d2 < (0.97 * r) ** 2) & (b[:, 2] > c[2] - 1.6 * r) & (self.wHead[:NBODY] > 0.5)
            dome = c[2] + np.sqrt(np.maximum(r * r - d2, 0))
            b[m, 2] = np.maximum(b[m, 2], dome[m])
        w = (smoothstep(0.5, 1.0, self.wHead) * 0.7)[:, None]
        for _ in range(8):
            x[:NBODY] = (x + w * (self.Abody @ x - x))[:NBODY]
        return x


@dataclass
class Ctx:
    """One evaluation of the figure at one shape."""

    fig: Figure
    P: Arr
    J: dict[str, Any]
    first: bool
    out: dict[str, Arr] = field(default_factory=dict)

    @property
    def vert(self) -> Frame:
        return frame([0, 0, self.J["zc"]], UP)

    def g(self, cut: Cut) -> dict[str, Any]:
        return cut if isinstance(cut, dict) else self.fig.g[cut]

    def shell(self, cut: Cut, ease: Arr | float, iters: int) -> Arr:
        """A cut, smoothed and pushed out along its normals by `ease` (m)."""
        g = self.g(cut)
        x = taubin(self.P[g["vid"]], g["A"], iters)
        return x + vnormals(x, g["T"]) * np.broadcast_to(ease, (len(x),))[:, None]

    def put(self, name: str, x: Arr, t: Arr, uv: Arr | None = None, **meta: Any) -> None:
        """Keep a part's points; on the first evaluation also its triangles, UVs and extras."""
        self.out[name] = x
        if self.first:
            strips = [r for k, r in meta.get("ranges", {}).items() if k in STRIPS]
            t2 = orient_out(x, t, self.J["zc"], strips) if len(t) else t
            if uv is not None and uv.ndim == 3:  # corner UVs follow their flipped triangles
                flipped = (t2 != t).any(1)
                uv = uv.copy()
                uv[flipped] = uv[flipped][:, ::-1]
            self.fig.topo[name] = (t2, uv)
            self.fig.meta[name] = meta

    def state(self, name: str, state: str, x: Arr) -> None:
        """A part's points in another state (tucked, open): a morph target of the same part."""
        self.out[f"{name}@{state}"] = x


def begin(fig: Figure, a: Arr, first: bool = False) -> Ctx:
    """Start an evaluation at shape `a`, with the body's regions already put."""
    v = fig.h.rest(a)
    posed = pose(fig.h, v)
    ctx = Ctx(fig=fig, P=posed.P, J=joints(fig.h, fig.ms, v, posed), first=first)
    pb = fig.body(posed.P)
    for name in BODY_PARTS:
        q = fig.body_q[name]
        vid = np.unique(q)
        re = np.full(len(pb), -1)
        re[vid] = np.arange(len(vid))
        ctx.put(name, pb[vid], tri_of(re[q]) if len(q) else np.zeros((0, 3), int), src=vid)
    ctx.out["_body"] = pb
    return ctx


def torso_uv(ctx: Ctx, x: Arr, t: Arr, arm_tris: dict[str, Arr]) -> Arr:
    """Corner UVs in metres: cylindrical about the trunk, and about each arm for its triangles."""
    j = ctx.J
    cuv = cyl_uv(x, t, ctx.vert, 0.84 / (2 * np.pi))
    for s in "LR":
        sf = frame(j["shoulder" + s], j["shoulder" + s] - j["wrist" + s])
        su = cyl_uv(x, t, sf, 0.28 / (2 * np.pi))
        cuv[arm_tris[s]] = su[arm_tris[s]]
    return cuv


def legs_uv(ctx: Ctx, x: Arr, t: Arr, leg_verts: dict[str, Arr]) -> Arr:
    """Corner UVs in metres: cylindrical about the trunk, and about each leg below the crotch."""
    j = ctx.J
    cuv = cyl_uv(x, t, ctx.vert, 0.84 / (2 * np.pi))
    for s in "LR":
        lf = frame(j["hip" + s] * [1, 0, 1], UP)
        lu = cyl_uv(x, t, lf, 0.56 / (2 * np.pi))
        fm = (leg_verts[s] & (x[:, 1] < j["crotch"] - 0.01))[t].all(1)
        cuv[fm] = lu[fm]
    return cuv
