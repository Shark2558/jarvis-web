# tests/r131_fakes_b.py -- R13.1 Part B: made-up meshes and a made-up source clone for the mannequin
# build's tests (scripts/mannequin). Nothing here is MakeHuman's or anyone's body: a tube, a box of
# eight points, and files with the build's names and nonsense inside.
from __future__ import annotations

import gzip
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
M1 = ROOT / "src" / "jarvis" / "api" / "static" / "vendor" / "mannequin" / "m1"
STATIC = ROOT / "src" / "jarvis" / "api" / "static"
FIXTURES = ROOT / "tests" / "fixtures" / "r13_1"


def mannequin() -> Any:
    """The build's package (`scripts/mannequin`), importable in a test."""
    if str(SCRIPTS) not in sys.path:
        sys.path.insert(0, str(SCRIPTS))
    import mannequin as pkg

    return pkg


def tube(
    radius: float = 0.1, height: float = 0.5, around: int = 16, up: int = 6
) -> tuple[Any, Any]:
    """An open tube about the y axis: (points, quads)."""
    import numpy as np

    th = np.arange(around) / around * 2 * np.pi
    rings = [
        np.stack([radius * np.sin(th), np.full(around, y), radius * np.cos(th)], 1)
        for y in np.linspace(0, height, up)
    ]
    quads = [
        [
            i * around + j,
            i * around + (j + 1) % around,
            (i + 1) * around + (j + 1) % around,
            (i + 1) * around + j,
        ]
        for i in range(up - 1)
        for j in range(around)
    ]
    return np.concatenate(rings), np.array(quads)


BOX_OBJ = "\n".join(
    [
        *(f"v {x} {y} {z}" for z in (0, 1) for y in (0, 10) for x in (-1, 1)),
        "g body",
        "f 1 2 4 3",
        "f 5 6 8 7",
        "g helper-tights",
        "f 1 2 6 5",
        "",
    ]
)


def fake_clone(root: Path, sources: dict[str, str], data_dir: str) -> dict[str, str]:
    """A folder with every file of `sources` (made-up content) under `data_dir`, plus an `smplx`
    folder that must never be read; returns the made-up files' own SHA-256 table."""
    sums: dict[str, str] = {}
    base = root / data_dir
    for rel in sources:
        if rel.endswith("base.obj"):
            data = BOX_OBJ.encode()
        elif rel.endswith("vertex_groups.json"):
            data = json.dumps({"Mid": [[0, 1]], "joint-a": [[0, 7]]}).encode()
        elif rel.endswith("rig.default.json"):
            head = {"strategy": "VERTEX", "vertex_index": 0}
            data = json.dumps(
                {"root": {"parent": "", "head": head}, "tip": {"parent": "root", "head": head}}
            ).encode()
        elif rel.endswith("weights.default.json"):
            data = json.dumps({"weights": {"root": [[i, 1.0] for i in range(8)]}}).encode()
        else:
            data = gzip.compress(f"# made up\n0 0.1 0.2 0.3\n# {rel}\n".encode(), mtime=0)
        path = base / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        sums[rel] = hashlib.sha256(data).hexdigest()
    trap = base / "smplx" / "model.bin"
    trap.parent.mkdir(parents=True, exist_ok=True)
    trap.write_bytes(b"never read")
    return sums


# ---- a small source for the build's own tests (review B-1, finding 7) ----------------------------
# The build's shape code used to run only in an opt-in rebuild from a 69 MB clone, so CI covered
# 44 % of scripts/mannequin. `b_source.bin.xz` is what the build needs of the pinned CC0 files,
# packed small (about 0.3 MB): the neutral body and the five shape directions instead of the 19
# targets (16-bit steps of 0.06 mm), the quads and their groups, the vertex groups, the rig and its
# skinning weights. It is MakeHuman/MPFB2 data (CC0 1.0) as shipped in NAVER's Anny at ANNY; made by
# `pack_source(<a local clone>)`, pinned by its SHA-256 in tests/test_r131_b_script.py.
SOURCE_FIXTURE = FIXTURES / "b_source.bin.xz"
_SPAN = 2.0  # metres: the neutral body's coordinates are stored as int16 / 32767 * _SPAN


def _packed(arrays: dict[str, Any], meta: dict[str, Any]) -> bytes:
    import lzma
    import struct

    head: dict[str, Any] = {"meta": meta, "arrays": {}}
    body = b""
    for name, a in arrays.items():
        head["arrays"][name] = [a.dtype.str, list(a.shape), len(body)]
        body += a.tobytes()
    js = json.dumps(head, separators=(",", ":"), sort_keys=True).encode()
    return lzma.compress(struct.pack("<I", len(js)) + js + body, preset=9)


def pack_source(clone: Path) -> bytes:
    """The small source fixture's bytes, from a local clone of naver/anny at the pinned commit
    (every file read through the build's own SHA-checked door)."""
    import numpy as np

    mannequin()
    from mannequin import core

    h = core.Human(Path(clone))
    arrays: dict[str, Any] = {
        "neutral": np.round(h.neutral() / _SPAN * 32767).astype("<i2"),
        "quads": h.Q.astype("<u2"),
    }
    names, inverse = np.unique(h.G, return_inverse=True)
    arrays["quad_group"] = inverse.astype("u1")
    spans = []
    for i, d in enumerate(h.directions()):
        at = np.where(np.abs(d).max(1) > 2e-5)[0]
        spans.append(float(np.abs(d).max()))
        arrays[f"dir{i}_at"] = np.diff(at, prepend=0).astype("<u2")
        arrays[f"dir{i}_by"] = np.round(d[at] / spans[-1] * 32767).astype("<i2")
    w = h.W.tocoo()
    keep = w.data > 5e-4
    order = np.lexsort((w.col[keep], w.row[keep]))
    arrays["w_row"] = np.diff(w.row[keep][order], prepend=0).astype("<u2")
    arrays["w_col"] = w.col[keep][order].astype("u1")
    arrays["w_val"] = np.round(w.data[keep][order] * 65535).astype("<u2")
    meta = dict(
        source=f"naver/anny@{core.ANNY_COMMIT}", licence="CC0-1.0 (MakeHuman/MPFB2 assets)",
        group_names=[str(n) for n in names], groups=h.groups, rig=h.rig, spans=spans,
    )  # fmt: skip
    return _packed(arrays, meta)


def fixture_human() -> Any:
    """The build's `Human` from the small committed source (no clone, no file but the fixture)."""
    import lzma
    import struct

    import numpy as np
    import scipy.sparse as sp

    mannequin()
    from mannequin import core

    raw = lzma.decompress(SOURCE_FIXTURE.read_bytes())
    (n,) = struct.unpack("<I", raw[:4])
    head, body = json.loads(raw[4 : 4 + n]), raw[4 + n :]
    a = {}
    for name, (dtype, shape, at) in head["arrays"].items():
        count = int(np.prod(shape))
        a[name] = np.frombuffer(body, dtype, count, at).reshape(shape)
    meta = head["meta"]
    neutral = a["neutral"].astype(float) / 32767 * _SPAN
    directions = []
    for i, span in enumerate(meta["spans"]):
        d = np.zeros_like(neutral)
        d[np.cumsum(a[f"dir{i}_at"].astype(int))] = a[f"dir{i}_by"].astype(float) / 32767 * span
        directions.append(d)
    rows = np.cumsum(a["w_row"].astype(int))
    w = sp.csr_matrix(
        (a["w_val"].astype(float) / 65535, (rows, a["w_col"].astype(int))),
        shape=(len(neutral), len(meta["rig"])),
    )
    w = sp.diags(1 / np.maximum(np.asarray(w.sum(1)).ravel(), 1e-9)) @ w
    return core.Human.of_parts(
        dict(
            neutral=neutral, quads=a["quads"].astype(int), groups=meta["groups"], rig=meta["rig"],
            quad_groups=np.array(meta["group_names"])[a["quad_group"]], weights=w,
            directions=directions,
        )
    )  # fmt: skip


def called_functions(run: Any, package: str = "mannequin") -> set[str]:
    """Run `run()` and name every function of the build's package that was called: "module.name"
    (a coverage check that needs no plug-in and no clone)."""
    seen: set[str] = set()
    root = str(SCRIPTS / package)

    def spy(frame: Any, event: str, arg: Any) -> None:
        code = frame.f_code
        if event == "call" and code.co_filename.startswith(root):
            seen.add(f"{Path(code.co_filename).stem}.{code.co_qualname}")

    old = sys.getprofile()
    sys.setprofile(spy)
    try:
        run()
    finally:
        sys.setprofile(old)
    return seen


CONTROLS = (
    "swap_morphs", "no_waist_down", "no_shorts", "long_sleeve", "side_is_front",
    "back_resets_tuck", "closed_is_open", "unsoftened_rig", "input_cadence", "thin_trousers",
)  # fmt: skip
_RUNS: dict[str, dict[str, dict[str, Any]]] = {}


def node_cases(
    control: str = "none", folder: Path | None = None, script: str = "b_check.mjs"
) -> dict[str, dict[str, Any]]:
    """The figure's Node checks (tests/fixtures/r13_1/b_check.mjs, or b_poke.mjs), by case name;
    run once a control (and a folder: another build than the committed one). Node missing is an
    error, never a skip."""
    import os
    import shutil
    import subprocess

    key = f"{script}:{control}@{folder or ''}"
    if key not in _RUNS:
        node = shutil.which("node")
        if node is None:
            raise RuntimeError("node is not installed")
        env = {**os.environ, **({"JARVIS_B_M1": str(folder)} if folder else {})}
        got = subprocess.run(
            [node, str(FIXTURES / script), control],
            capture_output=True, text=True, timeout=600, check=False, cwd=ROOT, env=env,
        )  # fmt: skip
        if got.returncode != 0:
            raise RuntimeError(f"{script} {control} failed: {got.stderr[-800:]}")
        out = json.loads(got.stdout)
        _RUNS[key] = {c["id"].split(":", 1)[1]: c for c in out["cases"]}
    return _RUNS[key]


POKE = "b_poke.mjs"  # review B-1, finding 6: what shows through its cover (a depth buffer in Node)


def manifest() -> dict[str, Any]:
    data: dict[str, Any] = json.loads((M1 / "MANIFEST.json").read_text(encoding="utf-8"))
    return data


MEASURE_OWN_CM, MEASURE_OTHERS_CM, QUANTISED_CM = 0.5, 3.5, 0.2
BUDGET_BYTES = int(3.5 * 1024 * 1024)
_CC0 = "f6089cba01cb570a24712b41ab8a586ccd3cc5ef53dc266ca50b95c288956d2c"
_APACHE = "1d459b13c9650c763d6351ce21ad3b02433c80131195cf9d908de4fbc213cf27"
LICENCE_SUMS = {"LICENSE-mpfb2-CC0.txt": _CC0, "LICENSE-anny-Apache-2.0.txt": _APACHE}
ANNY = "8f35dc2df1c4062fd2fae86734f9705de50c0c2b"
NOTICE_WORDS = (
    "MakeHuman/MPFB2 assets (CC0 1.0)",
    ANNY,
    "anthropometry.py",
    "(Apache-2.0, NAVER Corp.)",
    "shaped, posed, cut and quantised by JARVIS",
)


def manifest_problems(folder: Path | None = None) -> list[str]:
    """What is wrong with a release folder's manifest, sums, licences and size ([] when right)."""
    root = folder or M1
    out: list[str] = []
    man = json.loads((root / "MANIFEST.json").read_text(encoding="utf-8"))
    files = man.get("files", {})
    on_disk = {p.name for p in root.iterdir() if p.is_file()} - {"MANIFEST.json"}
    if set(files) != on_disk:
        out.append(f"the manifest lists {sorted(files)} but the folder holds {sorted(on_disk)}")
    for name, entry in files.items():
        data = (root / name).read_bytes() if (root / name).is_file() else b""
        if hashlib.sha256(data).hexdigest() != entry.get("sha256") or len(data) != entry.get(
            "bytes"
        ):
            out.append(f"{name}: its sum or size differs from the manifest")
        if not all(entry.get(k) for k in ("type", "source", "licence", "changes")):
            out.append(f"{name}: type, source, licence or changes is missing")
        if not str(entry.get("source", "")).endswith(ANNY):
            out.append(f"{name}: the source is not the pinned commit")
        if name.endswith(".glb") and entry.get("type") != "application/octet-stream":
            out.append(f"{name}: a model is served as data only")
    for name, sha in LICENCE_SUMS.items():
        text = (root / name).read_bytes() if (root / name).is_file() else b""
        if files.get(name, {}).get("sha256") != sha or hashlib.sha256(text).hexdigest() != sha:
            out.append(f"{name}: the licence text is missing or changed")
    notice = (
        (root / "NOTICE-mannequin.txt").read_text()
        if (root / "NOTICE-mannequin.txt").is_file()
        else ""
    )
    for words in NOTICE_WORDS:
        if words not in notice:
            out.append(f"the NOTICE lacks: {words}")
    total = sum(p.stat().st_size for p in root.rglob("*") if p.is_file())
    if total > BUDGET_BYTES:
        out.append(f"the release is {total} bytes, over the 3.5 MB budget")
    return out


def measure_problems(
    rows: list[dict[str, Any]], sample: dict[str, int], names: list[str]
) -> list[str]:
    """The measure table's rule: a measurement changed alone comes back within 0.5 cm, every
    other within 3.5 cm, and the written file within 0.2 cm of the float build."""
    out: list[str] = []
    for row in rows:
        changed = [k for k, w in zip(names, row["want"], strict=True) if w != sample[k]]
        for k, want, got, flt in zip(names, row["want"], row["got"], row["float"], strict=True):
            own = len(changed) <= 1 and (not changed or changed[0] == k)
            limit = MEASURE_OWN_CM if own else MEASURE_OTHERS_CM
            if abs(got - want) > limit:
                out.append(f"{row['case']}: {k} wanted {want}, measured {got} (limit {limit})")
            if abs(got - flt) > QUANTISED_CM:
                out.append(f"{row['case']}: {k} moved {abs(got - flt):.2f} cm when quantised")
    return out
