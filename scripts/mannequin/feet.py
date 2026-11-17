# scripts/mannequin/feet.py
"""R13.1 Part B (docs/plans/r13-1-try-on.md D5): on the feet: `shoe` (a shaped toe, a sole with a
heel), `sandal` (a sole and two straps over the bare foot) and `socks`. Both feet, always a pair."""

from __future__ import annotations

import numpy as np

from .figure import SOLE, Ctx
from .mesh import UP, Arr, frame, loft, merge, ring_pts, slice_r, smoothstep

TS = np.arange(40) / 40 * 2 * np.pi


def _side_tris(x: Arr, t: Arr, sg: int) -> Arr:
    return t[(sg * x[t][:, :, 0] > 0).all(1)]


def shoes(ctx: Ctx) -> None:
    """Shoes (the upper) and their soles."""
    g = ctx.fig.g["shoes"]
    x = ctx.shell("shoes", 0.0045, 2)
    soles = []
    for sg in (1, -1):
        m = sg * x[:, 0] > 0
        zmax, zmin = x[m, 2].max(), x[m, 2].min()
        toe = smoothstep(zmax - 0.10, zmax, x[m, 2])
        x[m, 2] += 0.024 * toe  # a longer, shaped toe
        xc = x[m, 0].mean()
        x[m, 0] = xc + (x[m, 0] - xc) * (1 - 0.16 * smoothstep(zmax - 0.07, zmax + 0.018, x[m, 2]))
        x[m, 1] = x[m, 1] * (1 - 0.22 * toe) + 0.004 * toe  # and a lower toe box
        ff = frame([xc, 0, 0.5 * (zmin + zmax) + 0.011], UP)
        ro = slice_r(x, _side_tris(x, g["T"], sg), ff, 0.016, TS)
        rings = [
            ring_pts(ff, 0.010, TS, ro + 0.001),
            ring_pts(ff, 0.003, TS, ro + 0.0028),
            ring_pts(ff, -SOLE, TS, ro + 0.0028),
            ring_pts(ff, -SOLE, TS, ro * 0.9),
        ]
        soles.append(loft(rings, cap_end=True))
    x[:, 1] = np.maximum(x[:, 1], 0.001)
    x[g["bnd"], 1] = 0.088
    ctx.put("shoes", x, g["T"], ride=g["vid"])
    sx, st = merge(soles)
    ctx.put("soles", sx, st)


def sandals(ctx: Ctx) -> None:
    """Sandals: a flat sole under each bare foot, a strap over the toes and one over the instep."""
    fig = ctx.fig
    g = fig.g["shoes"]
    foot = ctx.shell("shoes", 0.0, 1)
    parts = []
    for sg in (1, -1):
        m = sg * foot[:, 0] > 0
        zmax, zmin, xc = foot[m, 2].max(), foot[m, 2].min(), foot[m, 0].mean()
        st = _side_tris(foot, g["T"], sg)
        ff = frame([xc, 0, 0.5 * (zmin + zmax)], UP)
        ro = slice_r(foot, st, ff, 0.012, TS) + 0.004
        rings = [
            ring_pts(ff, 0.0, TS, ro * 0.6),
            ring_pts(ff, 0.0, TS, ro),
            ring_pts(ff, -0.012, TS, ro),
            ring_pts(ff, -0.012, TS, ro * 0.85),
        ]
        parts.append(loft(rings, cap_end=True))
        for z0, wide in ((zmax - 0.075, 0.022), (zmax - 0.135, 0.026)):  # toes, instep
            zf = frame([xc, 0.0, z0], [0, 0, 1.0], front=UP)
            rs = [slice_r(foot, st, zf, dz, TS[::2], rmax=0.09) + 0.0025 for dz in (0.0, wide)]
            parts.append(
                loft(
                    [
                        ring_pts(zf, 0.0, TS[::2], rs[0] - 0.002),
                        ring_pts(zf, 0.0, TS[::2], rs[0]),
                        ring_pts(zf, wide, TS[::2], rs[1]),
                        ring_pts(zf, wide, TS[::2], rs[1] - 0.002),
                    ]
                )
            )
    x, t = merge(parts)
    ctx.put("sandals", x, t)


def socks(ctx: Ctx) -> None:
    g = ctx.fig.g["socks"]
    x = ctx.shell("socks", 0.0015, 1)
    top = g["bnd"]
    x[top, 1] = np.where(ctx.fig.P0[g["vid"]][top, 1] > 0.2, 0.262 * ctx.J["scale"], x[top, 1])
    ctx.put("socks", x, g["T"], ride=g["vid"])
