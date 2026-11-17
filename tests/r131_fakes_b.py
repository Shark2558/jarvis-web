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
