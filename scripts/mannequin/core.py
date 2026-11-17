# scripts/mannequin/core.py
"""R13.1 Part B (docs/plans/r13-1-try-on.md D3): the mannequin's source and shape.

The body is the MakeHuman/MPFB2 base mesh, its targets and the standard rig weights (CC0 1.0) as
shipped in a local clone of naver/anny at the commit below, read with plain numpy. ONLY the files of
`SOURCES` are read, each refused when its SHA-256 differs; the `smplx` folder (non-commercial) and
Anny's own topology are never touched, and nothing is downloaded."""

from __future__ import annotations

import gzip
import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np
import scipy.sparse as sp

from .mesh import Arr

ANNY_COMMIT = "8f35dc2df1c4062fd2fae86734f9705de50c0c2b"
DATA = "src/anny/data/mpfb2"  # inside the clone; CC0 1.0 (its LICENSE.md)
NV, NBODY = 19158, 13380  # the base mesh's vertices; the first NBODY are the body
_T, _Z = "targets/", ".target.gz"
_TABLE = """
3dobjs/base.obj
    8e761e6624b8f54536409135d1636da63b32486a90d4897f84e121d144f6fb4c
mesh_metadata/basemesh_vertex_groups.json
    8cb1417bc55ae5ec8aa99f90734e81ed5fbb556511ff6a2c00e0534b70911444
rigs/standard/rig.default.json
    8b949de35c2dd70dbb5094e57a8586c3b9a9f650775a293212581a8f67be6797
rigs/standard/weights.default.json
    c3df45e2f2165663b483b7fa3dfed6f1bd5e2dd48d8825308de1a8453a88b111
targets/macrodetails/universal-male-young-averagemuscle-averageweight.target.gz
    e814651195c53971503d9823d6841216718a561951ef064f81d132297f4fa494
targets/macrodetails/universal-male-young-averagemuscle-maxweight.target.gz
    13b79074ecf00a0d028495a51865ae9e86c06b5801b6a614257b455ffbec7d10
targets/macrodetails/caucasian-male-young.target.gz
    ffe69537e53148edff2776204ba48cf3bf1f3cbc72966592c8a562ab80b07333
targets/macrodetails/asian-male-young.target.gz
    0928ed8b9f08f60afb9884cf9e9f33a939ed3a85d7f136de9ccc88a76981d6d7
targets/macrodetails/african-male-young.target.gz
    05ed84d6df36e788cdfa8da0be15376850524b960cf2f17f3e592b9cf7d21c85
targets/torso/measure-shoulder-dist-incr.target.gz
    d9508362063fee6f697bee2d7204cb6a799d9711fb2436f93f781242a104494f
targets/torso/measure-shoulder-dist-decr.target.gz
    6eef8cfafd4021579645565040f14113b5156d6c1d9069d39c76b732527a1709
targets/torso/measure-bust-circ-incr.target.gz
    d80557578cb087287e299025e1c4aa60d9b119fb8ab003d42e34bba0d01c92ff
targets/torso/measure-bust-circ-decr.target.gz
    459c9bf4e043669490be8e7d37ea4679397d7b72662f85c2678881552dc2c320
targets/torso/measure-underbust-circ-incr.target.gz
    6d1e86d9a86744f2ee4adb5f2791a27f8f397e621c181aaada47c45aa3bc6dc0
targets/torso/measure-underbust-circ-decr.target.gz
    28a34f1d3e455e8ca72764c5d4e6d936ca67c7fd2f3fb37c2affe04639460e7e
targets/torso/measure-waist-circ-incr.target.gz
    dcbca91a872f64c9015ecc3473a6769e2ccbb2ad551dce1a7692d277a88d39a1
targets/torso/measure-waist-circ-decr.target.gz
    be10c1d44a229f1faf302f7d51f45a0146e70a1912d3f9022c0ce5a3761ebb88
targets/torso/measure-hips-circ-incr.target.gz
    fe642001634d6c63080e0d75d8d835aeb406f04ee8e7ec3eaf7a6f085c8dd9db
targets/torso/measure-hips-circ-decr.target.gz
    326177958c09515f4c3612e270eb4a9e7670289a6c5de3a2c6ca6557aafd3c7b
targets/legs/measure-upperleg-height-incr.target.gz
    97b2de6960da43cdcce12d5139db868d96764faba6c8ba454635789b423d8180
targets/legs/measure-upperleg-height-decr.target.gz
    a0a5390594d3f33fc9f3688af6323e50fbe358bcb46ca5363f24b3fcdea23d07
targets/legs/measure-lowerleg-height-incr.target.gz
    82a085a996d2c5a7fd9e44e0333801127992edee9aae7fdac5f17e1f6522a635
targets/legs/measure-lowerleg-height-decr.target.gz
    f9dfdad1d34966804da611eeccad4aace5e03fec3006eef58ba40148a1a93054
"""
# each file this build may read (under DATA), and the SHA-256 it must have
SOURCES: dict[str, str] = dict(zip(_TABLE.split()[0::2], _TABLE.split()[1::2], strict=True))


class SourceRefused(RuntimeError):
    """A source file is not one of SOURCES, is missing, or fails its SHA-256."""


def read_source(root: Path, rel: str, sums: dict[str, str] | None = None) -> bytes:
    """One source file's bytes, only when `rel` is in the table and its SHA-256 matches."""
    table = SOURCES if sums is None else sums
    if rel not in table or "smplx" in rel.lower() or ".." in rel:
        raise SourceRefused(f"{rel}: not a source this build reads")
    path = Path(root) / rel
    if not path.is_file():
        raise SourceRefused(f"{rel}: missing")
    data = path.read_bytes()
    if hashlib.sha256(data).hexdigest() != table[rel]:
        raise SourceRefused(f"{rel}: its SHA-256 differs from the build's table")
    return data


def parse_obj(text: str) -> tuple[Arr, Arr, Arr]:
    """Vertices (metres; x = the figure's left, y = up, z = front), quads and each quad's group."""
    v: list[list[float]] = []
    q: list[list[int]] = []
    g: list[str] = []
    cur = ""
    for line in text.splitlines():
        if line.startswith("v "):
            v.append([float(x) for x in line.split()[1:4]])
        elif line.startswith("g "):
            cur = line.split()[1]
        elif line.startswith("f "):
            q.append([int(t.split("/")[0]) - 1 for t in line.split()[1:5]])
            g.append(cur)
    return np.array(v) * 0.1, np.array(q), np.array(g)  # decimetres -> metres


def parse_target(data: bytes, nv: int) -> Arr:
    """A gzipped MakeHuman target as (nv, 3) offsets in metres."""
    d = np.zeros((nv, 3))
    for line in gzip.decompress(data).decode().splitlines():
        if line.startswith("#") or not line.strip():
            continue
        p = line.split()
        d[int(p[0])] = [float(p[1]), float(p[2]), float(p[3])]
    return d * 0.1


def skin_matrix(weights: dict[str, list[list[float]]], bones: list[str], nv: int) -> Arr:
    """The (nv, bones) skinning weights, each row summing to 1."""
    bi = {b: i for i, b in enumerate(bones)}
    r, c, d = [], [], []
    for b, lst in weights.items():
        for i, w in lst:
            r.append(int(i))
            c.append(bi[b])
            d.append(w)
    w_ = sp.csr_matrix((d, (r, c)), shape=(nv, len(bones)))
    return sp.diags(1 / np.maximum(np.asarray(w_.sum(1)).ravel(), 1e-9)) @ w_


def bone_order(parent: dict[str, str | None]) -> list[str]:
    """The bones, every parent before its children."""
    order: list[str] = []
    seen: set[str] = set()

    def visit(b: str) -> None:
        if b in seen:
            return
        p = parent[b]
        if p:
            visit(p)
        seen.add(b)
        order.append(b)

    for b in parent:
        visit(b)
    return order


class Human:
    """The base mesh, its rig and the shape space (a neutral young male, five shape directions and
    a scale): `rest(a)` is the unposed shape for the six shape numbers `a`."""

    def __init__(self, clone: Path, sums: dict[str, str] | None = None) -> None:
        self.root = Path(clone) / DATA
        self._sums = sums
        self.V0, self.Q, self.G = parse_obj(self._read("3dobjs/base.obj").decode())
        self.groups: dict[str, Any] = json.loads(
            self._read("mesh_metadata/basemesh_vertex_groups.json")
        )
        self.rig: dict[str, Any] = json.loads(self._read("rigs/standard/rig.default.json"))
        wj = json.loads(self._read("rigs/standard/weights.default.json"))["weights"]
        self.bones = list(self.rig)
        self.parent: dict[str, str | None] = {b: self.rig[b]["parent"] or None for b in self.rig}
        self.order = bone_order(self.parent)
        self.bi = {b: i for i, b in enumerate(self.bones)}
        self.W = skin_matrix(wj, self.bones, len(self.V0))
        self.Wc = self.W.tocsc()
        self._tc: dict[str, Arr] = {}
        self._n: Arr | None = None
        self._r: list[Arr] = []

    def _read(self, rel: str) -> bytes:
        return read_source(self.root, rel, self._sums)

    def gidx(self, name: str) -> Arr:
        return np.concatenate([np.arange(a, b + 1) for a, b in self.groups[name]])

    def target(self, rel: str) -> Arr:
        if rel not in self._tc:
            self._tc[rel] = parse_target(self._read(_T + rel + _Z), len(self.V0))
        return self._tc[rel]

    def subtree(self, bone: str) -> list[str]:
        out = []
        for b in self.bones:
            p: str | None = b
            while p:
                if p == bone:
                    out.append(b)
                    break
                p = self.parent[p]
        return out

    def wsum(self, bones: list[str]) -> Arr:
        return np.asarray(self.W[:, [self.bi[b] for b in bones]].sum(1)).ravel()

    def joint(self, v: Arr, spec: dict[str, Any]) -> Arr:
        if spec["strategy"] == "CUBE":
            return v[self.gidx(spec["cube_name"])].mean(0)
        if spec["strategy"] == "VERTEX":
            return v[spec["vertex_index"]]
        return v[spec["vertex_indices"]].mean(0)

    def head(self, v: Arr, bone: str) -> Arr:
        return self.joint(v, self.rig[bone]["head"])

    def neutral(self) -> Arr:
        t, m = self.target, "macrodetails/"
        races = (
            t(m + "caucasian-male-young") + t(m + "asian-male-young") + t(m + "african-male-young")
        )
        return self.V0 + t(m + "universal-male-young-averagemuscle-averageweight") + races / 3

    def directions(self) -> list[Arr]:
        """The five shape directions after the scale: shoulders, chest, waist, hips, legs."""
        t = self.target

        def pm(p: str) -> Arr:
            return (t(p + "-incr") - t(p + "-decr")) / 2

        m = "macrodetails/universal-male-young-averagemuscle-"
        fat = t(m + "maxweight") - t(m + "averageweight")
        return [
            pm("torso/measure-shoulder-dist"),
            pm("torso/measure-bust-circ") + 0.6 * pm("torso/measure-underbust-circ"),
            0.6 * pm("torso/measure-waist-circ") + 0.4 * fat,
            pm("torso/measure-hips-circ"),
            pm("legs/measure-upperleg-height") + pm("legs/measure-lowerleg-height"),
        ]

    def rest(self, a: Arr) -> Arr:
        """The unposed shape: a[0] scales it, a[1:6] weigh the five directions."""
        if self._n is None:
            self._n, self._r = self.neutral(), self.directions()
        v = self._n.copy()
        for j in range(5):
            v = v + a[j + 1] * self._r[j]
        return v * (1 + a[0])
