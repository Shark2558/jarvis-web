# scripts/mannequin/glb.py
"""R13.1 Part B (docs/plans/r13-1-try-on.md D2, D3): the mannequin's GLB files, written and read.

The subset (the console's reader, console-tryon-glb.js, takes exactly this and refuses the rest):
one JSON and one BIN chunk; every mesh ONE primitive of triangles (or of lines: the measure rig);
POSITION and each morph target's POSITION as normalised int16 VEC3 in an 8-byte stride
(KHR_mesh_quantization), with the accessor's own `extras.scale` (and `extras.offset` for the base):
value = int / 32767 * scale + offset; TEXCOORD_0 as float32 VEC2; indices uint16. No normals: the
reader computes them after the morphs are applied (better than a blended normal, and smaller).
`mesh.extras.targetNames` names the morph targets; other extras are the build's facts."""

from __future__ import annotations

import json
import struct
from typing import Any

import numpy as np

from .mesh import Arr

MAGIC, JSON_CHUNK, BIN_CHUNK = 0x46546C67, 0x4E4F534A, 0x004E4942
I16, U16, F32 = 5122, 5123, 5126
Q = 32767
TRIANGLES, LINES = 4, 1


def quantise(a: Arr, centred: bool) -> tuple[Arr, list[float], list[float]]:
    """(n, 3) floats -> (n, 4) int16 (the last column pads), a scale and an offset per axis."""
    a = np.asarray(a, np.float64).reshape(-1, 3)
    if not np.isfinite(a).all():
        raise ValueError("a point that is not a number cannot be written")
    lo, hi = (a.min(0), a.max(0)) if len(a) else (np.zeros(3), np.zeros(3))
    off = (lo + hi) / 2 if centred else np.zeros(3)
    scale = np.maximum(np.abs(a - off).max(0) if len(a) else np.zeros(3), 1e-9)
    out = np.zeros((len(a), 4), np.int16)
    out[:, :3] = np.rint((a - off) / scale * Q).astype(np.int16)
    return out, [float(s) for s in scale], [float(o) for o in off]


def dequantise(q: Arr, scale: list[float], offset: list[float] | None = None) -> Arr:
    """The reader's rule: int / 32767 * scale + offset."""
    out = np.asarray(q, np.float64)[:, :3] / Q * np.asarray(scale)
    return out + np.asarray(offset) if offset is not None else out


# Each accessor carries its own scale (extras.scale, extras.offset), which no general glTF loader
# knows: the files REQUIRE a vendor extension, so another loader refuses them instead of reading
# wrong sizes (review B-1, finding 13).
EXTENSIONS = ("KHR_mesh_quantization", "JARVIS_accessor_scale")


class GlbWriter:
    """Collects meshes and writes one .glb."""

    def __init__(self) -> None:
        self.bin = bytearray()
        self.views: list[dict[str, Any]] = []
        self.acc: list[dict[str, Any]] = []
        self.meshes: list[dict[str, Any]] = []
        self.nodes: list[dict[str, Any]] = []

    def _add(self, arr: Arr, ctype: int, typ: str, stride: int | None = None, **extra: Any) -> int:
        arr = np.ascontiguousarray(arr)
        self.bin += b"\0" * (-len(self.bin) % 4)
        view: dict[str, Any] = dict(buffer=0, byteOffset=len(self.bin), byteLength=arr.nbytes)
        if stride:
            view["byteStride"] = stride
        self.bin += arr.tobytes()
        self.views.append(view)
        acc: dict[str, Any] = dict(
            bufferView=len(self.views) - 1, componentType=ctype, count=len(arr), type=typ
        )
        acc.update(extra)
        self.acc.append(acc)
        return len(self.acc) - 1

    def _vec3(self, a: Arr, centred: bool) -> int:
        q, scale, off = quantise(a, centred)
        ex = dict(scale=scale, offset=off) if centred else dict(scale=scale)
        return self._add(q, I16, "VEC3", stride=8, normalized=True, extras=ex)

    def mesh(
        self,
        name: str,
        x: Arr,
        index: Arr,
        uv: Arr | None,
        targets: dict[str, Arr],
        extras: dict[str, Any] | None = None,
        mode: int = TRIANGLES,
    ) -> None:
        """One mesh: points, its index (triangles or line pairs), UVs and named morph deltas."""
        if len(x) > 65535:
            raise ValueError(f"{name}: too many points for a uint16 index")
        attr = dict(POSITION=self._vec3(x, centred=True))
        if uv is not None:
            attr["TEXCOORD_0"] = self._add(np.asarray(uv, np.float32), F32, "VEC2")
        prim: dict[str, Any] = dict(attributes=attr, mode=mode)
        prim["indices"] = self._add(np.asarray(index, np.uint16).reshape(-1), U16, "SCALAR")
        if targets:
            prim["targets"] = [
                dict(POSITION=self._vec3(d, centred=False)) for d in targets.values()
            ]
        ex = dict(targetNames=list(targets), **(extras or {}))
        self.meshes.append(dict(name=name, primitives=[prim], extras=ex))
        self.nodes.append(dict(name=name, mesh=len(self.meshes) - 1))

    def to_bytes(self, extras: dict[str, Any]) -> bytes:
        self.bin += b"\0" * (-len(self.bin) % 4)
        doc = dict(
            asset=dict(version="2.0", generator="JARVIS scripts/mannequin", extras=extras),
            extensionsUsed=list(EXTENSIONS),
            extensionsRequired=list(EXTENSIONS),
            scene=0,
            scenes=[dict(nodes=list(range(len(self.nodes))))],
            nodes=self.nodes,
            meshes=self.meshes,
            accessors=self.acc,
            bufferViews=self.views,
            buffers=[dict(byteLength=len(self.bin))],
        )
        js = json.dumps(doc, separators=(",", ":")).encode()
        js += b" " * (-len(js) % 4)
        head = struct.pack("<III", MAGIC, 2, 28 + len(js) + len(self.bin))
        return b"".join(
            [
                head,
                struct.pack("<II", len(js), JSON_CHUNK),
                js,
                struct.pack("<II", len(self.bin), BIN_CHUNK),
                bytes(self.bin),
            ]
        )


def _accessor(doc: dict[str, Any], blob: bytes, i: int) -> Arr:
    a = doc["accessors"][i]
    v = doc["bufferViews"][a["bufferView"]]
    off, n = v.get("byteOffset", 0), a["count"]
    key = (a["componentType"], a["type"])
    if key == (I16, "VEC3") and a.get("normalized") and v.get("byteStride") == 8:
        q = np.frombuffer(blob, np.int16, n * 4, off).reshape(n, 4)
        return dequantise(q, a["extras"]["scale"], a["extras"].get("offset"))
    if key == (F32, "VEC2"):
        return np.frombuffer(blob, np.float32, n * 2, off).reshape(n, 2).astype(np.float64)
    if key == (U16, "SCALAR"):
        return np.frombuffer(blob, np.uint16, n, off).astype(np.int64)
    raise ValueError(f"accessor {i}: {key} is not in the mannequin's subset")


def read_glb(data: bytes) -> dict[str, Any]:
    """A .glb of the subset -> {"extras": ..., "meshes": {name: {x, index, uv, targets, extras,
    mode}}}; anything else is refused."""
    magic, version, total = struct.unpack_from("<III", data, 0)
    if magic != MAGIC or version != 2 or total != len(data):
        raise ValueError("not a version 2 GLB of the stated length")
    jl, jt = struct.unpack_from("<II", data, 12)
    bl, bt = struct.unpack_from("<II", data, 20 + jl)
    if jt != JSON_CHUNK or bt != BIN_CHUNK or 28 + jl + bl != len(data):
        raise ValueError("a GLB of one JSON and one BIN chunk is wanted")
    doc = json.loads(data[20 : 20 + jl])
    if EXTENSIONS[1] not in doc.get("extensionsRequired", []):
        raise ValueError("the file does not require the mannequin's scale extension")
    blob = data[28 + jl :]
    meshes: dict[str, Any] = {}
    for m in doc["meshes"]:
        (prim,) = m["primitives"]
        if prim.get("mode", TRIANGLES) not in (TRIANGLES, LINES) or set(prim["attributes"]) - {
            "POSITION",
            "TEXCOORD_0",
        }:
            raise ValueError(f"{m['name']}: a primitive outside the mannequin's subset")
        names = m["extras"]["targetNames"]
        tg = [_accessor(doc, blob, t["POSITION"]) for t in prim.get("targets", [])]
        uv = prim["attributes"].get("TEXCOORD_0")
        meshes[m["name"]] = dict(
            x=_accessor(doc, blob, prim["attributes"]["POSITION"]),
            index=_accessor(doc, blob, prim["indices"]),
            uv=None if uv is None else _accessor(doc, blob, uv),
            targets=dict(zip(names, tg, strict=True)),
            extras=m["extras"],
            mode=prim.get("mode", TRIANGLES),
        )
    return dict(extras=doc["asset"].get("extras", {}), meshes=meshes)
