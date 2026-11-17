# scripts/mannequin/outer.py
"""R13.1 Part B (docs/plans/r13-1-try-on.md D5, D6, AVT-07, AVT-10): the outer layer, ONE
approximate shape, `jacket` (a blazer, jacket, coat, hoodie, sweater, rainwear, festive layer): a
V neck that shows the shirt's collar, a front cut down the middle, lapels, a collar that sits UNDER
the shirt's, and sleeves that end above the shirt cuff (so the cuff and the watch stay in view).
The part is the CLOSED jacket; its `open` state lets the two fronts hang apart."""

from __future__ import annotations

from typing import Any

import numpy as np
from scipy.interpolate import LinearNDInterpolator, NearestNDInterpolator

from .figure import TH, Ctx, Figure, torso_uv
from .mesh import (
    Arr,
    Frame,
    avg_matrix,
    boundary_smoother,
    boundary_verts,
    loft,
    merge,
    ring_pts,
    slice_r,
    slide_boundary,
    smoothstep,
    tri_of,
)
from .tops import CUFF_END, arm_tris, neck_frame, neck_radius, part_ranges, sleeve_ends, trunk_shell

SLEEVE_ABOVE_CUFF = 0.015  # the jacket's sleeve ends this far above the shirt cuff's end (AVT-07)
V_DROP = 0.20  # the V's point below the neck joint (m)
FALL = 0.95  # the fronts are shaped within this angle (rad) of the centre: short of the shoulders


def cut(fig: Figure) -> dict[str, Any]:
    """The jacket's cut: the helper mesh minus a neck scoop, slit down the front from the neck to
    the hem. The slit doubles the front-centre vertices: `src` maps each point to the unslit shell,
    `side` is +1 (the figure's left front), -1 (right) or 0."""
    if "jacketS" in fig.g:
        return fig.g["jacketS"]
    j, p = fig.J0, fig.P0
    q = fig.g["jacket"]["q"]
    zc, neck = j["zc"], j["neck"]
    th = np.arctan2(p[:, 0], p[:, 2] - zc)  # where each point ends up once the V is shaped
    th = th + np.sign(p[:, 0]) * vee_at(j, p[:, 1]) * smoothstep(FALL, 0.0, np.abs(th)) * (
        p[:, 2] > zc
    )
    r = np.hypot(p[:, 0], p[:, 2] - zc)
    shaped = np.stack([r * np.sin(th), p[:, 1], zc + r * np.cos(th)], 1)
    c = np.where(fig.arm[:, None], p, shaped)[q].mean(1)
    scoop = (np.hypot(c[:, 0], c[:, 2] - neck[2] - 0.012) < 0.072) & (c[:, 1] > neck[1] - 0.09)
    q = q[~scoop]
    vid = np.unique(q)
    re = np.full(len(p), -1)
    re[vid] = np.arange(len(vid))
    ql = re[q]
    mid = np.where((np.abs(p[vid, 0]) < 1e-5) & (p[vid, 2] > j["zc"]))[0]
    twin = np.full(len(vid), -1)
    twin[mid] = len(vid) + np.arange(len(mid))
    left = p[q].mean(1)[:, 0] > 0
    ql = np.where(left[:, None] & (twin[ql] >= 0), twin[ql], ql)
    src = np.concatenate([np.arange(len(vid)), mid])
    side = np.sign(p[vid, 0])
    side[mid] = -1
    side = np.concatenate([side, np.ones(len(mid))])
    t0, t = tri_of(re[q]), tri_of(ql)
    g = dict(
        vid=vid[src],
        T=t,
        bnd=boundary_verts(t),
        A0=avg_matrix(len(vid), t0),
        T0=t0,
        vid0=vid,
        src=src,
        side=side,
        S=boundary_smoother(len(src), t),
    )
    fig.g["jacketS"] = g
    return g


def vee_at(j: dict[str, Any], y: Arr) -> Arr:
    """How far (rad) each front edge stands back from the centre at height y: nothing below the
    V's point, widening to the neck (so the shirt's collar and the top of its placket show)."""
    yv, yn = j["neck"][1] - V_DROP, j["neck"][1] - 0.035
    return 0.56 * np.clip((np.asarray(y, float) - yv) / (yn - yv), 0, 1) ** 1.15


def vee(ctx: Ctx, y: Arr) -> Arr:
    return vee_at(ctx.J, y)


def hang(ctx: Ctx, y: Arr) -> Arr:
    """How much further (rad) each front swings out when the jacket hangs open."""
    yv = ctx.J["neck"][1] - V_DROP
    return 0.26 + 0.20 * smoothstep(yv, ctx.J["crotch"], y)


def radius_field(th: Arr, y: Arr, r: Arr) -> Any:
    """The shell's radius about the trunk's axis as a function of (angle, height), from its own
    points: a point moved round the axis is put back ON the shell, never inside it."""
    pts = np.concatenate([np.stack([th + k, y], 1) for k in (-2 * np.pi, 0.0, 2 * np.pi)])
    val = np.tile(r, 3)
    lin, near = LinearNDInterpolator(pts, val), NearestNDInterpolator(pts, val)

    def at(th2: Arr, y2: Arr) -> Arr:
        out = lin(th2, y2)
        return np.where(np.isnan(out), near(th2, y2), out)

    return at


def _fronts(ctx: Ctx, g: dict[str, Any], x: Arr, opened: bool) -> Arr:
    """Shape the fronts by sliding each point round the trunk's axis ALONG the shell: the V, then
    either the overlap (left over right) or the open hang; the arms are left alone."""
    fig, j = ctx.fig, ctx.J
    armw = np.clip(fig.wArmAny[g["vid"]], 0, 1)
    zc, yv = j["zc"], j["neck"][1] - V_DROP
    th = np.arctan2(x[:, 0], x[:, 2] - zc)
    r = np.hypot(x[:, 0], x[:, 2] - zc)
    side, y = g["side"], x[:, 1]
    trunk = armw < 0.8
    on_shell = radius_field(th[trunk], y[trunk], r[trunk])
    fall = smoothstep(FALL, 0.0, np.abs(th)) * (x[:, 2] > zc)
    th2 = th + side * vee(ctx, y) * fall
    lift = 0.004 * fall if opened else 0.0
    if opened:
        th2 = th2 + side * hang(ctx, y) * fall
    else:
        lap = (
            smoothstep(0.5, 0.0, np.abs(th)) * (x[:, 2] > zc) * smoothstep(yv + 0.02, yv - 0.03, y)
        )
        th2 = th2 - np.where(side > 0, 0.11, 0.0) * lap
        lift = np.where(side > 0, 0.003, -0.001) * lap
    r2 = np.where(fall > 0, on_shell(th2, y), r) + lift
    k = (1 - armw)[:, None]
    new = np.stack([r2 * np.sin(th2), y, zc + r2 * np.cos(th2)], 1)
    return x * (1 - k) + new * k


def _shell(ctx: Ctx, g: dict[str, Any], opened: bool) -> Arr:
    fig, j = ctx.fig, ctx.J
    g0 = dict(vid=g["vid0"], T=g["T0"], A=g["A0"], bnd=boundary_verts(g["T0"]))
    x0, _ = trunk_shell(ctx, g0, 0.011, tucked=False, loose=1.3, arm_ease=0.004)
    x = _fronts(ctx, g, x0[g["src"]], opened)
    b = g["bnd"]
    hem = b[(~fig.arm[g["vid"]][b]) & (fig.P0[g["vid"]][b, 1] < fig.J0["crotch"] + 0.02)]
    kept = x[hem].copy()
    x = slide_boundary(x, g["T"], g["S"], 24)  # clean neck and front edges
    x[hem] = kept  # the hem stays where the fronts put it
    x[hem, 1] = j["crotch"] - 0.015
    sleeve_ends(ctx, g, x, CUFF_END + SLEEVE_ABOVE_CUFF, 0.05)
    return x


def lapel(ctx: Ctx, x: Arr, trunk_t: Arr, side: int, opened: bool) -> tuple[Arr, Arr]:
    """One lapel: a folded band lying on the front along the V's edge."""
    j = ctx.J
    yv, yn = j["neck"][1] - V_DROP, j["neck"][1] - 0.035
    s = np.linspace(0, 1, 10)
    width = 0.006 + 0.05 * s * (1.25 - s) / 0.39
    cols: list[list[Arr]] = [[], [], []]
    for k, sv in enumerate(s):
        y = yv + sv * (yn - yv)
        ring = slice_r(x, trunk_t, ctx.vert, y, TH, rmax=0.3)
        th0 = float(vee(ctx, y)) + (float(hang(ctx, y)) if opened else 0.0)
        for c, (dw, lift) in enumerate(((-0.02, 0.003), (0.5, 0.007), (1.0, 0.004))):
            th = side * (th0 + dw * width[k] / float(ring[0]))
            rr = float(
                np.interp(th % (2 * np.pi), np.append(TH, 2 * np.pi), np.append(ring, ring[0]))
            )
            cols[c].append(ring_pts(ctx.vert, y, np.array([th]), rr + lift)[0])
    return loft([np.array(c) for c in cols], closed=False)


def back_collar(nf: Frame, r_hi: Arr) -> tuple[Arr, Arr]:
    """The collar round the back of the neck, lying on the shoulders under the shirt's collar."""
    tl = np.linspace(0.85, 2 * np.pi - 0.85, 33)
    r = np.interp(tl, np.append(TH, 2 * np.pi), np.append(r_hi, r_hi[0]))
    rings = [
        ring_pts(nf, -0.046, tl, r + 0.010),
        ring_pts(nf, -0.052, tl, r + 0.018),
        ring_pts(nf, -0.068, tl, r + 0.027),
    ]
    return loft(rings, closed=False)


def _state(ctx: Ctx, g: dict[str, Any], opened: bool) -> list[tuple[Arr, Arr]]:
    fig = ctx.fig
    x = _shell(ctx, g, opened)
    trunk_t = g["T"][(~fig.arm[g["vid"]][g["T"]]).all(1)]
    sx, _ = trunk_shell(ctx, "shirt", 0.0055, tucked=False)
    nf, _, shirt_t = neck_frame(ctx, "shirt", sx, 0.012)
    r_hi = neck_radius(sx, shirt_t, nf)
    return [
        (x, g["T"]),
        lapel(ctx, x, trunk_t, 1, opened),
        lapel(ctx, x, trunk_t, -1, opened),
        back_collar(nf, r_hi),
    ]


def jacket(ctx: Ctx) -> None:
    """The jacket closed (the part) and open (its `open` state)."""
    g = cut(ctx.fig)
    parts = _state(ctx, g, opened=False)
    x, t = merge(parts)
    uv = torso_uv(ctx, x, t, arm_tris(ctx, g, parts, t, None)) if ctx.first else None
    ctx.put("jacket", x, t, uv, ranges=part_ranges(parts, ("trunk", "lapelL", "lapelR", "collar")))
    ctx.state("jacket", "open", merge(_state(ctx, g, opened=True))[0])
