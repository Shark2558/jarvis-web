# scripts/mannequin/tops.py
"""R13.1 Part B (docs/plans/r13-1-try-on.md D5, D6): the tops, each ONE approximate shape cut from
the CC0 helper mesh: `shirt` (collar stand and leaf, placket, cuffs, buttons), `tee` (short sleeves,
a neck band), `kurta` (to the knee, a band collar, a short placket, always worn out) and the base
`vest`. A shirt and a tee carry a second state, `tuck` (the tail pulled inside the waistband)."""

from __future__ import annotations

from typing import Any

import numpy as np

from .figure import TH, Ctx, Cut, torso_uv
from .mesh import (
    Arr,
    Frame,
    boundary_smoother,
    circ_smooth,
    disc,
    frame,
    loft,
    merge,
    ring_pts,
    slice_r,
    slide_boundary,
    smoothstep,
    taubin,
)

CUFF_END = 0.012  # the shirt cuff ends this far above the wrist joint (m): the watch sits below it
CUFF_LEN = 0.064
X_AXIS = np.array([1.0, 0.0, 0.0])


def trunk_shell(
    ctx: Ctx, cut: Cut, ease: float, tucked: bool, loose: float = 1.0, arm_ease: float = 0.002
) -> tuple[Arr, Arr]:
    """A top's shell with its drape (worn out) or its blouse and tuck; returns (points, angle)."""
    fig, j = ctx.fig, ctx.J
    g = ctx.g(cut)
    vid = g["vid"]
    armw = np.clip(fig.wArmAny[vid], 0, 1)
    x = ctx.shell(cut, ease + arm_ease * armw, 3)
    yy, tw, wa, cr = x[:, 1], j["trouser_top"], j["waist"], j["crotch"]
    th = np.arctan2(x[:, 0], x[:, 2] - j["zc"])
    rad = np.stack([np.sin(th), np.zeros(len(th)), np.cos(th)], 1)
    if tucked:
        push = 0.010 * np.exp(-(((yy - (tw + 0.055)) / 0.05) ** 2))
        push = push - 0.007 * smoothstep(tw + 0.02, tw - 0.01, yy)
    else:
        push = 0.013 * np.exp(-(((yy - wa) / 0.09) ** 2)) + 0.012 * smoothstep(
            wa - 0.02, cr + 0.03, yy
        )
        push = push * loose
    fold = (
        0.0022
        * np.sin(th * 13 + 1.3 * np.sin(yy * 40))
        * np.exp(-(((yy - (tw + 0.07)) / 0.07) ** 2))
    )
    x = x + rad * ((push + fold) * (1 - armw))[:, None]
    b = g["bnd"]
    hem = b[(~fig.arm[vid][b]) & (fig.P0[vid][b, 1] < fig.J0["trouser_top"] + 0.1)]
    x[hem, 1] = cr + 0.022 + 0.035 * np.sin(th[hem]) ** 2
    if tucked:  # the tail folds up inside the waistband (it never reaches the legs)
        low = (~fig.arm[vid]) & (x[:, 1] < tw - 0.07)
        x[low, 1] = tw - 0.07
    return x, th


def sleeve_ends(ctx: Ctx, cut: Cut, x: Arr, end_m: float, gather: float) -> None:
    """Square each sleeve end to the forearm at `end_m` above the wrist; `gather` narrows the
    last part into a cuff (below 0: flares it)."""
    fig, j = ctx.fig, ctx.J
    g = ctx.g(cut)
    for s in "LR":
        e, w = j["elbow" + s], j["wrist" + s]
        ln = float(np.linalg.norm(w - e))
        ax = (w - e) / ln
        sm = fig.wArm[s][g["vid"]] >= 0.5
        rel = x[sm] - e
        al = rel @ ax
        k = 1 - gather * smoothstep(0.4, 0.8, al / ln)
        x[sm] = e + al[:, None] * ax + (rel - al[:, None] * ax) * k[:, None]
        cv = g["bnd"][fig.wArm[s][g["vid"]][g["bnd"]] >= 0.5]
        end = w - ax * end_m
        x[cv] -= ((x[cv] - end) @ ax)[:, None] * ax


def short_sleeves(ctx: Ctx, cut: Cut, x: Arr, at: float) -> None:
    """Square each short sleeve's hem to the upper arm at fraction `at`, a little flared."""
    fig, j = ctx.fig, ctx.J
    g = ctx.g(cut)
    for s in "LR":
        a, e = j["shoulder" + s], j["elbow" + s]
        ln = float(np.linalg.norm(e - a))
        ax = (e - a) / ln
        sm = fig.wArm[s][g["vid"]] >= 0.5
        rel = x[sm] - a
        al = rel @ ax
        k = 1 + 0.10 * smoothstep(0.2, at, al / ln)
        x[sm] = a + al[:, None] * ax + (rel - al[:, None] * ax) * k[:, None]
        cv = g["bnd"][fig.wArm[s][g["vid"]][g["bnd"]] >= 0.5]
        x[cv] -= ((x[cv] - (a + ax * ln * at)) @ ax)[:, None] * ax


def neck_frame(ctx: Ctx, cut: Cut, x: Arr, lower: float) -> tuple[Frame, Arr, Arr]:
    """The neck opening: a tilted frame under the chin (the opening is lowered by `lower`);
    returns (frame, the front point, the trunk's triangles)."""
    fig = ctx.fig
    g = ctx.g(cut)
    vid, b = g["vid"], g["bnd"]
    nl = b[(~fig.arm[vid][b]) & (fig.P0[vid][b, 1] > fig.J0["trouser_top"] + 0.25)]
    front, back = x[nl[np.argmax(x[nl, 2])]], x[nl[np.argmin(x[nl, 2])]]
    nf = frame(x[nl].mean(0), np.cross(front - back, X_AXIS))
    x[nl] -= nf[2] * lower
    trunk_t = g["T"][(~fig.arm[vid][g["T"]]).all(1)]
    return nf, x[nl[np.argmax(x[nl, 2])]].copy(), trunk_t


def placket(ctx: Ctx, x: Arr, trunk_t: Arr, ytop: float, ybot: float, rows: int = 26) -> Arr:
    """The front band's three columns of points, (rows, 3, 3), a little proud of the cloth."""
    dth = 0.016 / 0.11
    ang = np.array([-dth, 0, dth])
    cols = []
    for yv in np.linspace(ytop, ybot, rows):
        r3 = slice_r(x, trunk_t, ctx.vert, yv, ang, rmax=0.3)
        cols.append(ring_pts(ctx.vert, yv, ang, r3 + 0.0016))
    return np.array(cols)


def neck_radius(x: Arr, trunk_t: Arr, nf: Frame) -> Arr:
    """The neck's radius round the frame, evened out."""
    r_hi = slice_r(x, trunk_t, nf, -0.010, TH, rmax=0.13)
    return 0.6 * r_hi + 0.4 * r_hi.mean()


def collar(r_hi: Arr, nf: Frame, drop0: float = 0.0) -> tuple[list[Arr], list[Arr]]:
    """A shirt collar: the stand's rings, and the folded leaf's (open at the front)."""
    front = np.cos(TH)
    h_top = -0.014 - 0.004 * (front > 0) * front**2 - drop0
    stand = [
        ring_pts(nf, -0.042, TH, r_hi + 0.008),
        ring_pts(nf, -0.028, TH, r_hi + 0.0035),
        ring_pts(nf, h_top, TH, r_hi * 0.985 + 0.0025),
    ]
    gap = 0.16
    tl = np.linspace(gap, 2 * np.pi - gap, 49)
    rl = np.interp(tl, np.append(TH, 2 * np.pi), np.append(r_hi, r_hi[0])) * 0.985 + 0.0025
    fr = np.cos(tl)
    pt = np.exp(-(((np.minimum(tl, 2 * np.pi - tl) - gap) / 0.5) ** 2))  # 1 at the collar points
    htop = -0.014 - 0.004 * (fr > 0) * fr**2 - drop0
    drop = 0.030 + 0.028 * pt
    flare = 0.016 + 0.006 * pt + 0.008 * np.abs(np.sin(tl))
    sgn = np.where(tl < np.pi, 1.0, -1.0)
    leaf = [
        ring_pts(nf, htop, tl, rl + 0.0005),
        ring_pts(nf, htop + 0.0045, tl, rl + 0.0045),
        ring_pts(nf, htop - drop * 0.45, tl + sgn * 0.42 * 0.45 * pt, rl + 0.0045 + flare * 0.6),
        ring_pts(nf, htop - drop, tl + sgn * 0.42 * pt, rl + 0.0045 + flare),
    ]
    return stand, leaf


def cuffs(ctx: Ctx, cut: Cut, x: Arr) -> tuple[list[tuple[Arr, Arr]], list[tuple[Arr, Arr]]]:
    """The two cuffs (left, right) and a button on each."""
    fig, j = ctx.fig, ctx.J
    g = ctx.g(cut)
    t2 = TH[::2]
    parts, btn = [], []
    for s in "LR":
        e, w = j["elbow" + s], j["wrist" + s]
        cf = frame(w, e - w)
        st = g["T"][(fig.wArm[s][g["vid"]][g["T"]] >= 0.5).all(1)]
        rc = slice_r(x, st, cf, CUFF_END + CUFF_LEN - 0.01, t2, rmax=0.12)
        rc = 0.5 * rc + 0.5 * rc.mean()
        s0 = CUFF_END
        rings = [
            ring_pts(cf, s0 + CUFF_LEN, t2, rc - 0.002),
            ring_pts(cf, s0 + CUFF_LEN - 0.004, t2, rc + 0.0028),
            ring_pts(cf, s0 + 0.002, t2, rc * 0.95 + 0.002),
            ring_pts(cf, s0, t2, rc * 0.95 + 0.0005),
            ring_pts(cf, s0, t2, rc * 0.95 - 0.004),
        ]
        parts.append(loft(rings))
        out = -cf[3]
        at = cf[0] + cf[2] * (s0 + 0.03) + out * (rc[len(rc) // 2] * 0.96 + 0.003)
        btn.append(disc(at, out, cf[2], 0.0048, 0.0022, seg=8))
    return parts, btn


def front_buttons(cols: Arr, n: int, lo: int, hi: int) -> list[tuple[Arr, Arr]]:
    """`n` buttons down the placket's middle column, between rows lo and hi."""
    out = []
    for i in np.linspace(lo, hi, n).round().astype(int):
        tn = cols[min(i + 1, len(cols) - 1), 1] - cols[max(i - 1, 0), 1]
        nrm = np.cross(X_AXIS, tn)
        nrm = nrm / np.linalg.norm(nrm) * (1 if nrm[2] >= 0 else -1)
        out.append(disc(cols[i, 1], nrm, X_AXIS, 0.0055, 0.0024, seg=10))
    return out


def _shirt_state(ctx: Ctx, tucked: bool) -> tuple[list[tuple[Arr, Arr]], list[tuple[Arr, Arr]]]:
    x, _ = trunk_shell(ctx, "shirt", 0.0055, tucked)
    sleeve_ends(ctx, "shirt", x, CUFF_END + 0.045, 0.14)
    nf, front, trunk_t = neck_frame(ctx, "shirt", x, 0.012)
    ybot = ctx.J["trouser_top"] - 0.05 if tucked else float(x[:, 1].min()) + 0.03
    cols = placket(ctx, x, trunk_t, front[1] - 0.036, ybot)
    r_hi = neck_radius(x, trunk_t, nf)
    stand, leaf = collar(r_hi, nf)
    cuff_parts, btn = cuffs(ctx, "shirt", x)
    parts = [
        (x, ctx.fig.g["shirt"]["T"]),
        loft([cols[:, 0], cols[:, 1], cols[:, 2]], closed=False),
        loft(stand),
        loft(leaf, closed=False),
        *cuff_parts,
    ]
    btn += front_buttons(cols, 8, 3, 23)
    top = ring_pts(nf, -0.019, np.array([0.0]), r_hi[:1] + 0.004)[0]
    btn.append(disc(top, np.array([0, 0.25, 1.0]), X_AXIS, 0.005, 0.0022, seg=10))
    return parts, btn


def part_ranges(parts: list[tuple[Arr, Arr]], names: tuple[str, ...]) -> dict[str, list[int]]:
    """Each named sub-part's [first, count] in the merged part's points."""
    out, off = {}, 0
    for (x, _), n in zip(parts, names, strict=True):
        out[n] = [off, len(x)]
        off += len(x)
    return out


def arm_tris(
    ctx: Ctx, cut: Cut, parts: list[tuple[Arr, Arr]], t: Arr, cuff_at: int | None
) -> dict[str, Arr]:
    """Which triangles of a merged top lie on each arm (the trunk part's sleeves, and a cuff)."""
    fig = ctx.fig
    sizes = [len(p[0]) for p in parts]
    out = {}
    for k, s in enumerate("LR"):
        on = np.zeros(sum(sizes), bool)
        on[: sizes[0]] = fig.wArm[s][ctx.g(cut)["vid"]] >= 0.5
        if cuff_at is not None:
            a = sum(sizes[: cuff_at + k])
            on[a : a + sizes[cuff_at + k]] = True
        out[s] = on[t].all(1)
    return out


SHIRT_PARTS = ("trunk", "placket", "stand", "collar", "cuffL", "cuffR")


def shirt(ctx: Ctx) -> None:
    """The shirt worn out (the part) and tucked (its `tuck` state), and its buttons."""
    parts, btn = _shirt_state(ctx, tucked=False)
    x, t = merge(parts)
    uv = torso_uv(ctx, x, t, arm_tris(ctx, "shirt", parts, t, 4)) if ctx.first else None
    ctx.put("shirt", x, t, uv, ranges=part_ranges(parts, SHIRT_PARTS))
    bx, bt = merge(btn)
    ctx.put("shirtButtons", bx, bt)
    parts2, btn2 = _shirt_state(ctx, tucked=True)
    ctx.state("shirt", "tuck", merge(parts2)[0])
    ctx.state("shirtButtons", "tuck", merge(btn2)[0])


def _tee_state(ctx: Ctx, tucked: bool) -> Arr:
    g: dict[str, Any] = ctx.fig.g["tee"]
    x, _ = trunk_shell(ctx, "tee", 0.0065, tucked)
    if "S" not in g:
        g["S"] = boundary_smoother(len(x), g["T"])
    x = slide_boundary(x, g["T"], g["S"], 30)  # a clean round neck
    short_sleeves(ctx, "tee", x, 0.60)
    return x


def tee(ctx: Ctx) -> None:
    """The tee (also a polo and a top): short sleeves, a round neck; worn out, and its `tuck`."""
    g = ctx.fig.g["tee"]
    x = _tee_state(ctx, tucked=False)
    arms = {s: (ctx.fig.wArm[s][g["vid"]] >= 0.5)[g["T"]].all(1) for s in "LR"}
    ctx.put("tee", x, g["T"], torso_uv(ctx, x, g["T"], arms) if ctx.first else None)
    ctx.state("tee", "tuck", _tee_state(ctx, tucked=True))


def hang_radius(ctx: Ctx, heights: Arr, ease: float, flare: float) -> list[Arr]:
    """For cloth hanging round both legs: at each height (top to bottom) the radius about the
    trunk's axis that clears everything above it, evened out, with a little flare."""
    fig = ctx.fig
    g = fig.g["legs"]
    x = ctx.P[g["vid"]]
    out: list[Arr] = []
    reach = np.zeros(len(TH))
    for k, yv in enumerate(heights):
        r = slice_r(x, g["T"], ctx.vert, float(yv), TH, rmax=0.4)
        reach = np.maximum(reach, circ_smooth(r, 3))
        out.append(circ_smooth(reach, 2) + ease + flare * k / max(len(heights) - 1, 1))
    return out


def kurta(ctx: Ctx) -> None:
    """The kurta: long loose sleeves, a band collar, a short placket, a skirt to the knee."""
    j = ctx.J
    x, _ = trunk_shell(ctx, "shirt", 0.008, tucked=False, loose=0.6)
    sleeve_ends(ctx, "shirt", x, 0.02, -0.10)
    nf, front, trunk_t = neck_frame(ctx, "shirt", x, 0.012)
    cols = placket(ctx, x, trunk_t, front[1] - 0.03, front[1] - 0.30, rows=12)
    r = neck_radius(x, trunk_t, nf)
    band = [
        ring_pts(nf, -0.042, TH, r + 0.008),
        ring_pts(nf, -0.030, TH, r + 0.004),
        ring_pts(nf, -0.012, TH, r * 0.985 + 0.003),
        ring_pts(nf, -0.013, TH, r * 0.985),
    ]
    hs = np.linspace(j["waist"] - 0.01, j["kneeL"][1] - 0.02, 12)
    rr = hang_radius(ctx, hs, 0.016, 0.03)
    rr[0] = rr[0] - 0.012  # the skirt starts just inside the body of the kurta
    skirt = [ring_pts(ctx.vert, h, TH, r_) for h, r_ in zip(hs, rr, strict=True)]
    parts = [
        (x, ctx.fig.g["shirt"]["T"]),
        loft([cols[:, 0], cols[:, 1], cols[:, 2]], closed=False),
        loft(band),
        loft(skirt),
    ]
    xm, t = merge(parts)
    uv = torso_uv(ctx, xm, t, arm_tris(ctx, "shirt", parts, t, None)) if ctx.first else None
    ctx.put("kurta", xm, t, uv, ranges=part_ranges(parts, ("trunk", "placket", "band", "skirt")))


def vest(ctx: Ctx) -> None:
    """The base layer's vest: skin-close, with clean curved armholes and neckline."""
    g: dict[str, Any] = ctx.fig.g["vest"]
    x = taubin(ctx.shell("vest", 0.0012, 2), g["A"], 2)
    if "S" not in g:
        g["S"] = boundary_smoother(len(x), g["T"])
    x = slide_boundary(x, g["T"], g["S"], 60)
    ctx.put("vest", x, g["T"], rim=True)
