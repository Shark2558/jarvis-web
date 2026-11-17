# scripts/mannequin/accessories.py
"""R13.1 Part B (docs/plans/r13-1-try-on.md D5): the accessories: `belt` (at the trouser top, with
a steel buckle; drawn only with a tucked top) and `watch` (a strap round the LEFT wrist, below the
shirt cuff, with a steel case on the outer side)."""

from __future__ import annotations

import numpy as np

from .figure import TH, Ctx
from .mesh import box, disc, frame, loft, loft_uv, merge, ring_pts, slice_r, tri_of


def belt(ctx: Ctx) -> None:
    """The belt and its buckle, round whatever bottom was just made (`bottom` in the context)."""
    j = ctx.J
    x, t = ctx.out["trousers"], ctx.fig.topo["trousers"][0]
    tw, vert = j["trouser_top"], ctx.vert
    rb = slice_r(x, t, vert, tw - 0.022, TH)
    r1 = np.maximum(slice_r(x, t, vert, tw - 0.040, TH), rb)
    r2 = np.maximum(slice_r(x, t, vert, tw - 0.007, TH), rb - 0.002)
    rings = [
        ring_pts(vert, tw - 0.040, TH, r1 + 0.001),
        ring_pts(vert, tw - 0.039, TH, r1 + 0.0045),
        ring_pts(vert, tw - 0.006, TH, r2 + 0.0045),
        ring_pts(vert, tw - 0.005, TH, r2 + 0.001),
    ]
    bx, bt = loft(rings)
    ctx.put("belt", bx, bt, loft_uv(rings) if ctx.first else None)
    c = np.array([0, tw - 0.0225, j["zc"] + rb[0] + 0.007])
    ex, ey, ez = np.eye(3)
    ax = (ex, ey, ez)
    bars = [
        box(c + ey * 0.017, ax, (0.046, 0.005, 0.006)),
        box(c - ey * 0.017, ax, (0.046, 0.005, 0.006)),
        box(c + ex * 0.0205, ax, (0.005, 0.039, 0.006)),
        box(c - ex * 0.0205, ax, (0.005, 0.039, 0.006)),
        box(c + ex * 0.004 + ez * 0.002, ax, (0.036, 0.004, 0.004)),
    ]
    kx, kt = merge(bars)
    ctx.put("buckle", kx, kt)


def watch(ctx: Ctx) -> None:
    """The watch: its strap and its case, on the left wrist."""
    fig, j = ctx.fig, ctx.J
    e, w = j["elbowL"], j["wristL"]
    wf = frame(w, e - w, front=(1, 0, 0.0))  # this frame's "front" is the wrist's outer side
    arm_t = tri_of(fig.Qb)
    arm_t = arm_t[(fig.wArm["L"][arm_t] > 0.9).all(1)]
    t2 = TH[::2]
    rw = slice_r(ctx.out["_body"], arm_t, wf, -0.002, t2, rmax=0.06)
    rings = [
        ring_pts(wf, -0.013, t2, rw + 0.0005),
        ring_pts(wf, -0.012, t2, rw + 0.0028),
        ring_pts(wf, 0.008, t2, rw + 0.0028),
        ring_pts(wf, 0.009, t2, rw + 0.0005),
    ]
    wx, wt = loft(rings)
    ctx.put("watchStrap", wx, wt, loft_uv(rings) if ctx.first else None)
    o, _, e2, e3 = wf
    cx, ct = merge(
        [
            disc(o - e2 * 0.002 + e3 * (rw[0] + 0.002), e3, e2, 0.0185, 0.008, seg=20, dome=False),
            disc(
                o - e2 * 0.002 + e3 * (rw[0] + 0.0102), e3, e2, 0.0150, 0.0006, seg=20, dome=False
            ),
        ]
    )
    ctx.put("watchCase", cx, ct)
