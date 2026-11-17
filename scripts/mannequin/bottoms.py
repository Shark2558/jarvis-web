# scripts/mannequin/bottoms.py
"""R13.1 Part B (docs/plans/r13-1-try-on.md D5, D6): the bottoms, each ONE approximate shape:
`trousers` (a straight leg with ease, a clean waist and hems), `shorts` (to just above the knee),
`wrap` (a mundu or dhoti: cloth hanging round both legs to the ankle) and the base layer's shorts,
which are ALWAYS drawn and sit inside every bottom's ease (the private zone, D6)."""

from __future__ import annotations

import numpy as np

from .figure import TH, Ctx, legs_uv
from .mesh import Arr, loft, loft_uv, ring_pts, smoothstep
from .tops import hang_radius

BOTTOM_EASE = 0.007  # every bottom's shell (m); the base shorts' is 0.0035


def leg_axis(ctx: Ctx, s: str, y: Arr) -> tuple[Arr, Arr]:
    """The leg's centre line (x, z) at heights y, through ankle, knee and hip."""
    j = ctx.J
    a, k, hp = j["ankle" + s], j["knee" + s], j["hip" + s]
    ys = [a[1], k[1], hp[1]]
    return np.interp(y, ys, [a[0], k[0], hp[0]]), np.interp(y, ys, [a[2], k[2], hp[2]])


def leg_tubes(
    ctx: Ctx, cut: str, x: Arr, rmin_of: tuple[float, float], tube_y: tuple[float, float]
) -> None:
    """Give each leg a minimum radius (at the hem, at the knee and above) and, near the hem (base
    heights tube_y), a clean round tube whatever the leg inside does."""
    fig, j = ctx.fig, ctx.J
    vid = fig.g[cut]["vid"]
    yb, cr, sc = fig.P0[vid, 1], j["crotch"], j["scale"]
    for s, sg in (("L", 1), ("R", -1)):
        m = (fig.wLeg[s][vid] > 0.5) & (x[:, 1] < cr + 0.02)
        ax, az = leg_axis(ctx, s, x[:, 1])
        dx, dz = x[:, 0] - ax, x[:, 2] - az
        r = np.hypot(dx, dz)
        kn = j["knee" + s][1]
        rmin = np.interp(
            x[:, 1], [0.0, kn, cr + 0.02], [rmin_of[0] * sc, rmin_of[1] * sc, rmin_of[1] * sc]
        )
        rmin = rmin * smoothstep(cr + 0.02, cr - 0.12, x[:, 1])
        tube = smoothstep(tube_y[1], tube_y[0], yb) * (rmin > 0)
        want = np.maximum(r, rmin) * (1 - tube) + rmin * tube
        f = np.where(m, want / np.maximum(r, 1e-6), 1.0)
        x[:, 0], x[:, 2] = ax + dx * f, az + dz * f
        x[:, 0] = np.where(m, sg * np.maximum(sg * x[:, 0], 0.004), x[:, 0])


def edges(ctx: Ctx, cut: str) -> tuple[Arr, Arr]:
    """A leg garment's open edges: (the waist's vertices, the hems')."""
    fig = ctx.fig
    g = fig.g[cut]
    yb = fig.P0[g["vid"], 1]
    b = g["bnd"]
    return b[yb[b] > fig.J0["crotch"]], b[yb[b] < fig.J0["crotch"]]


def leg_sides(ctx: Ctx, cut: str) -> dict[str, Arr]:
    return {s: ctx.fig.wLeg[s][ctx.fig.g[cut]["vid"]] > 0.5 for s in "LR"}


def trousers(ctx: Ctx) -> None:
    fig, j = ctx.fig, ctx.J
    g = fig.g["trousers"]
    x = ctx.shell("trousers", BOTTOM_EASE, 3)
    leg_tubes(ctx, "trousers", x, (0.069, 0.074), (0.12, 0.24))
    top, bot = edges(ctx, "trousers")
    hem = np.zeros(len(x))
    for s, sg in (("L", 1), ("R", -1)):  # the hem breaks a little higher at the front
        an = j["ankle" + s]
        fr = (x[:, 2] - an[2]) / np.maximum(np.hypot(x[:, 0] - an[0], x[:, 2] - an[2]), 1e-6)
        hem = np.where(sg * x[:, 0] > 0, 0.052 + 0.022 * fr, hem)
    x[bot, 1] = hem[bot]
    low = (fig.P0[g["vid"], 1] < 0.14) & (x[:, 1] < hem)
    x[low, 1] = hem[low]
    x[top, 1] = j["trouser_top"]
    uv = legs_uv(ctx, x, g["T"], leg_sides(ctx, "trousers")) if ctx.first else None
    ctx.put("trousers", x, g["T"], uv)


def shorts_garment(ctx: Ctx) -> None:
    """Shorts: the trousers' top with a looser leg ending just above the knee."""
    fig, j = ctx.fig, ctx.J
    g = fig.g["shortsG"]
    x = ctx.shell("shortsG", BOTTOM_EASE, 3)
    knee0 = fig.J0["kneeL"][1]
    leg_tubes(ctx, "shortsG", x, (0.105, 0.105), (knee0 + 0.04, knee0 + 0.16))
    top, bot = edges(ctx, "shortsG")
    x[bot, 1] = j["kneeL"][1] + 0.045
    x[top, 1] = j["trouser_top"]
    uv = legs_uv(ctx, x, g["T"], leg_sides(ctx, "shortsG")) if ctx.first else None
    ctx.put("shortsG", x, g["T"], uv)


def wrap(ctx: Ctx) -> None:
    """A mundu or dhoti: a folded band at the waist, then cloth hanging straight to the ankle."""
    j = ctx.J
    tw = j["trouser_top"]
    hs = np.concatenate(
        [
            [tw + 0.012, tw + 0.010, tw - 0.03, tw - 0.034],
            np.linspace(tw - 0.07, j["ankleL"][1] + 0.035, 14),
        ]
    )
    rr = hang_radius(ctx, hs, BOTTOM_EASE + 0.004, 0.012)
    rr[0], rr[1], rr[2] = rr[0] - 0.006, rr[1] + 0.004, rr[2] + 0.004  # the fold stands proud
    front = 0.004 * np.exp(
        -((((TH - 0.35 + np.pi) % (2 * np.pi) - np.pi) / 0.05) ** 2)
    )  # the overlap's edge
    rings = [
        ring_pts(ctx.vert, h, TH, r + front * (k > 3))
        for k, (h, r) in enumerate(zip(hs, rr, strict=True))
    ]
    x, t = loft(rings)
    ctx.put("wrap", x, t, loft_uv(rings) if ctx.first else None)


def base_shorts(ctx: Ctx) -> None:
    """The base layer's boxer-length shorts (always drawn: the private zone's cover)."""
    fig, j = ctx.fig, ctx.J
    g = fig.g["shorts"]
    x = ctx.shell("shorts", 0.0035, 2)
    top, bot = edges(ctx, "shorts")
    x[top, 1] = j["waist"] - 0.04
    x[bot, 1] = j["crotch"] - 0.19 * j["scale"]
    ctx.put("baseShorts", x, g["T"], rim=True)
