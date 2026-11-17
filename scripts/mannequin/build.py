#!/usr/bin/env python3
# scripts/mannequin/build.py
"""R13.1 Part B (docs/plans/r13-1-try-on.md D3): build the mannequin's files.

    python scripts/mannequin/build.py <a local clone of naver/anny at ANNY_COMMIT> <output folder>

A dev tool run by hand with the pins of requirements-dev.txt (numpy 2.5.3, scipy 1.18.1); never in
the server's image. It reads only the CC0 MakeHuman/MPFB2 files of `core.SOURCES` from the clone
(each checked against its SHA-256; never the `smplx` folder), solves the sample shape and the seven
morph shapes (each measurement at its range's top, and `waist_down`: waist 62), cuts and shapes the
garments at every shape, and writes into the output folder: body.glb (the body's regions without
the private zone, the base vest and shorts, the measure rig), garments.glb (every template),
MANIFEST.json (each file's sha256, bytes, type, source, licence and changes; the build's facts and
its measure table) and the two licence texts and the NOTICE. The committed output lives in
src/jarvis/api/static/vendor/mannequin/m1/."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Any

if __package__ in (None, ""):  # run as a script: make the package importable
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    __package__ = "mannequin"

import numpy as np  # noqa: E402

from . import accessories, bottoms, feet, outer, tops  # noqa: E402
from .core import ANNY_COMMIT, DATA, Human, SourceRefused  # noqa: E402
from .figure import BODY_PARTS, SOLE, Figure, begin  # noqa: E402
from .glb import LINES, GlbWriter, read_glb  # noqa: E402
from .measure import (  # noqa: E402
    MEASURES,
    MORPHS,
    RANGES,
    SAMPLE,
    Measurer,
    rig_ids,
    rig_measure,
    solve,
    table_cases,
    weights_of,
)
from .mesh import Arr, weld  # noqa: E402

RELEASE = "m1"
TEMPLATES: dict[str, dict[str, Any]] = {
    "shirt": dict(parts=["shirt", "shirtButtons"], variants=["tucked", "untucked"], state="tuck"),
    "tee": dict(parts=["tee"], variants=["tucked", "untucked"], state="tuck"),
    "kurta": dict(parts=["kurta"], variants=["knee"], state=None),
    "trousers": dict(parts=["trousers"], variants=[], state=None),
    "shorts": dict(parts=["shortsG"], variants=[], state=None),
    "wrap": dict(parts=["wrap"], variants=["ankle"], state=None),
    "jacket": dict(parts=["jacket"], variants=["open", "closed"], state="open"),
    "shoe": dict(parts=["shoes", "soles"], variants=[], state=None),
    "sandal": dict(parts=["sandals"], variants=[], state=None),
    "belt": dict(parts=["belt", "buckle"], variants=[], state=None),
    "watch": dict(parts=["watchStrap", "watchCase"], variants=[], state=None),
    "socks": dict(parts=["socks"], variants=[], state=None),
}
BASE_PARTS = ("vest", "baseShorts")
LICENCES = {  # the clone's licence texts, copied as they are (their SHA-256 pinned too)
    "LICENSE-mpfb2-CC0.txt": (
        DATA + "/LICENSE.md",
        "f6089cba01cb570a24712b41ab8a586ccd3cc5ef53dc266ca50b95c288956d2c",
    ),
    "LICENSE-anny-Apache-2.0.txt": (
        "LICENSE",
        "1d459b13c9650c763d6351ce21ad3b02433c80131195cf9d908de4fbc213cf27",
    ),
}
NOTICE = (
    "Body and garment base: MakeHuman/MPFB2 assets (CC0 1.0) as shipped in NAVER's Anny at\n"
    f"{ANNY_COMMIT}; the waist measurement loop from Anny's anthropometry.py\n"
    "(Apache-2.0, NAVER Corp.); shaped, posed, cut and quantised by JARVIS.\n"
)
SOURCE = f"naver/anny@{ANNY_COMMIT}"
CHANGES = (
    "MakeHuman/MPFB2 base mesh, targets and standard rig weights read from the clone; a neutral "
    "shape solved for six measurements, posed, the private zone removed, garments cut from the "
    "helper-tights helper mesh and shaped, seven morph targets, quantised to int16 (JARVIS)"
)


def evaluate(fig: Figure, a: Arr, first: bool = False) -> dict[str, Arr]:
    """Every part's points at shape `a` (and, the first time, the topology in `fig`)."""
    ctx = begin(fig, a, first)
    for make in (
        tops.vest,
        bottoms.base_shorts,
        bottoms.trousers,
        accessories.belt,
        bottoms.shorts_garment,
        bottoms.wrap,
        tops.shirt,
        tops.tee,
        tops.kurta,
        outer.jacket,
        feet.shoes,
        feet.sandals,
        feet.socks,
        accessories.watch,
    ):
        make(ctx)
    ctx.out["_P"] = ctx.P
    return ctx.out


def morph_shapes(ms: Measurer, a0: Arr) -> dict[str, Arr]:
    """The shape numbers of the seven morph targets: each measurement at its range's top with the
    others at the sample, and `waist_down` (waist at its range's bottom)."""
    target = np.array([SAMPLE[k] for k in MEASURES], float)
    out = {}
    for i, k in enumerate(MEASURES):
        t = target.copy()
        t[i] = RANGES[k][1]
        out[k] = solve(ms.of_shape, t, a0)
    t = target.copy()
    t[MEASURES.index("waist")] = RANGES["waist"][0]
    out["waist_down"] = solve(ms.of_shape, t, a0)
    return out


def part_mesh(
    name: str, fig: Figure, base: dict[str, Arr], morphs: dict[str, dict[str, Arr]]
) -> dict[str, Any]:
    """One part ready to write: points, triangles, UVs, morph deltas (the seven, then its state)."""
    t, uv = fig.topo[name]
    x = base[name]
    vmap = np.arange(len(x))
    if uv is not None and uv.ndim == 3:
        vmap, t, uv = weld(t, uv)
    targets = {k: (m[name] - x)[vmap] for k, m in morphs.items()}
    for key in base:
        if key.startswith(name + "@"):
            targets[key.split("@")[1]] = (base[key] - x)[vmap]
    extras = {k: v for k, v in fig.meta[name].items() if k in ("ranges", "rim") and v is not True}
    if "ranges" in extras:  # sub-part ranges follow the welded order (welding keeps it)
        first = {k: int(np.searchsorted(vmap, a)) for k, (a, _) in extras["ranges"].items()}
        last = {k: int(np.searchsorted(vmap, a + n)) for k, (a, n) in extras["ranges"].items()}
        extras["ranges"] = {k: [first[k], last[k] - first[k]] for k in first}
    return dict(x=x[vmap], index=t, uv=uv, targets=targets, extras=extras)


def rig_mesh(
    ms: Measurer, base: dict[str, Arr], morphs: dict[str, dict[str, Arr]]
) -> dict[str, Any]:
    """The measure rig as a mesh of lines (never drawn: a test measures the file with it)."""
    shapes = [base["_P"], *[m["_P"] for m in morphs.values()]]
    ids, pairs, sections = rig_ids(ms, shapes)
    targets = {k: m["_P"][ids] - base["_P"][ids] for k, m in morphs.items()}
    return dict(
        x=base["_P"][ids],
        index=pairs,
        uv=None,
        targets=targets,
        extras=dict(sections=sections, targetNames=list(targets)),
    )


def write_glb(parts: dict[str, dict[str, Any]], extras: dict[str, Any]) -> bytes:
    w = GlbWriter()
    for name, p in parts.items():
        ex = {k: v for k, v in p["extras"].items() if k != "targetNames"}
        w.mesh(
            name, p["x"], p["index"], p["uv"], p["targets"], ex, LINES if name == "measure" else 4
        )
    return w.to_bytes(extras)


def measure_table(float_rig: dict[str, Any], file_rig: dict[str, Any]) -> list[dict[str, Any]]:
    """Each case's wanted values, what the float build measures and what the written file does."""
    rows = []
    for label, vals in table_cases():
        w = weights_of(vals)
        rows.append(
            dict(
                case=label,
                want=[vals[k] for k in MEASURES],
                float=[round(float(v), 3) for v in rig_measure(float_rig, w)],
                got=[round(float(v), 3) for v in rig_measure(file_rig, w)],
            )
        )
    return rows


def manifest(files: dict[str, bytes], facts: dict[str, Any]) -> dict[str, Any]:
    entries = {}
    for name, data in files.items():
        glb = name.endswith(".glb")
        entries[name] = dict(
            sha256=hashlib.sha256(data).hexdigest(),
            bytes=len(data),
            type="application/octet-stream" if glb else "text/plain",
            source=SOURCE,
            licence="CC0-1.0 (MakeHuman/MPFB2 assets); see NOTICE-mannequin.txt"
            if glb
            else ("CC0-1.0" if "CC0" in name else "Apache-2.0"),
            changes=CHANGES
            if glb
            else "none (copied as it is)"
            if name.startswith("LICENSE")
            else "written by JARVIS",
        )
    return dict(release=RELEASE, files=entries, **facts)


def build(clone: Path) -> dict[str, bytes]:
    """Everything the release folder holds, by file name."""
    h = Human(clone)
    ms = Measurer(h)
    a0 = solve(ms.of_shape, np.array([SAMPLE[k] for k in MEASURES], float), np.zeros(6))
    fig = Figure(h, ms, a0)
    base = evaluate(fig, a0, first=True)
    morphs = {k: evaluate(fig, a) for k, a in morph_shapes(ms, a0).items()}
    meshes = {n: part_mesh(n, fig, base, morphs) for n in fig.topo}
    rig = rig_mesh(ms, base, morphs)
    facts: dict[str, Any] = dict(
        sliders=list(MEASURES), morphs=list(MORPHS), ranges=RANGES, sample=SAMPLE, sole=SOLE
    )
    body = {n: meshes[n] for n in (*BODY_PARTS, *BASE_PARTS)} | {"measure": rig}
    worn = {n: m for n, m in meshes.items() if n not in body}
    files = {"body.glb": write_glb(body, facts), "garments.glb": write_glb(worn, facts)}
    for name, (rel, sha) in LICENCES.items():
        data = (Path(clone) / rel).read_bytes()
        if hashlib.sha256(data).hexdigest() != sha:
            raise SourceRefused(f"{rel}: its SHA-256 differs from the build's table")
        files[name] = data
    files["NOTICE-mannequin.txt"] = NOTICE.encode()
    facts.update(
        templates=TEMPLATES,
        shape=dict(
            cuff_end=tops.CUFF_END,
            cuff_len=tops.CUFF_LEN,
            sleeve_above_cuff=outer.SLEEVE_ABOVE_CUFF,
            v_drop=outer.V_DROP,
        ),
        base=list(BASE_PARTS),
        body=list(BODY_PARTS),
        triangles={n: len(m["index"]) for n, m in meshes.items()},
        joints={k: [round(float(c), 5) for c in v] for k, v in fig.J0.items() if np.ndim(v) == 1},
        levels={k: round(float(fig.J0[k]), 5) for k in ("crotch", "waist", "trouser_top", "zc")},
        measure=measure_table(rig, read_glb(files["body.glb"])["meshes"]["measure"]),
    )
    files["MANIFEST.json"] = (json.dumps(manifest(files, facts), indent=1) + "\n").encode()
    return files


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print(__doc__)
        return 2
    out = Path(argv[2])
    out.mkdir(parents=True, exist_ok=True)
    files = build(Path(argv[1]))
    for name, data in files.items():
        (out / name).write_bytes(data)
        print(f"{name}: {len(data):,} bytes")
    print(f"total: {sum(len(d) for d in files.values()):,} bytes")
    for row in json.loads(files["MANIFEST.json"])["measure"]:
        print(
            f"{row['case']:14s} "
            + " ".join(f"{w:5.0f}->{g:6.1f}" for w, g in zip(row["want"], row["got"], strict=True))
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
