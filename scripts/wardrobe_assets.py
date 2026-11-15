#!/usr/bin/env python3
# scripts/wardrobe_assets.py
"""R13 D8 (docs/plans/r13-wardrobe.md "The model files"): fetch, verify, cut and pin the wardrobe's
three on-device models, served from `static/vendor/vision/r13-1/` by the existing vision route.

    python scripts/wardrobe_assets.py check     the folder matches MANIFEST.json and every sum
                                                below (standard library; no network; exit 1)
    python scripts/wardrobe_assets.py manifest  write MANIFEST.json from the pins below (no
                                                network); refused when a vendored file differs
    python scripts/wardrobe_assets.py fetch [--from DIR] [--fallback]
        download each upstream file from the ONNX Model Zoo at the pinned commit (or take it from
        DIR, found by its SHA-256), refuse any other sum, make the cut, check the cut's sum, and
        write the files, the licence texts and MANIFEST.json (last)

A dev tool run by hand, never in the image. `fetch` needs `onnx==1.23.2` for the cut only:
`onnx.utils.extract_model(..., ["472_quantized"])` refuses the quantized graph here ("not found in
value_infos"), so the cut is made by hand, exactly as the plan's probe made it: keep every node
that feeds the output, drop unused initializers and value_info (and, for the fp32 graph, unused
inputs), set the output's type, save. Each upstream file's and each cut's SHA-256 is pinned below;
a byte that differs is refused. The fp32 cut (the fallback, D8) is written only with `--fallback`.
Nothing here runs a downloaded file: ONNX files are parsed as data. Every file is written
atomically (a temporary name, `os.replace`) and the manifest last.

MANIFEST.json (the route in `api/console.py` reads `files` only: `sha256` and `type`):

    {"release", "commit", "files": {name: {sha256, bytes, type, task, source, upstream_sha256,
     upstream_bytes, licence, licence_files, changes, output, quant?, selfcheck?}},
     "licences": {LICENSE-*.txt beside the release folder: sha256}, "notice", "fallback"}

`selfcheck` (D8, M8): a fixed ramp input, `((i % 251) / 250) * 2 - 1` over 1 x 3 x 224 x 224, and
the SHA-256 of the output bytes on the vendored onnxruntime-web 1.30.0 (one thread); the task's
`load()` compares it on the phone. Part D recorded the other two the same way (Node 22, the vendored
runtime, one thread; console-vision.js SELF13 holds the same numbers and its SELFCHECK arithmetic
makes the same inputs): `face`, the top five face scores on the ramp over 1 x 3 x 240 x 320 (fp32:
a tolerance of 0.002); `person`, SSD's one detection on a drawn dark silhouette against a pale sky
(uint8 1 x 300 x 300 x 3: class 1, its score and box, a tolerance of 0.03 for the int8 graph).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import tempfile
import urllib.request
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
VISION = ROOT / "src" / "jarvis" / "api" / "static" / "vendor" / "vision"
RELEASE = "r13-1"
FOLDER = VISION / RELEASE
COMMIT = "c5cae0f1942c8d7727372c7b1f6b485aa39e4421"  # github.com/onnx/models, Apache-2.0
BASE = f"https://media.githubusercontent.com/media/onnx/models/{COMMIT}/validated/vision/"
OCTET = "application/octet-stream"
RAMP = "((i % 251) / 250) * 2 - 1 over float32[1, 3, 224, 224]"
INT8_SCALE = 0.019110053777694702  # 472_quantized: uint8, zero point 0 (D7)
ZOO_MIT = "MIT (ONNX Model Zoo); weights from the TensorFlow Object Detection API (Apache-2.0)"


@dataclass(frozen=True)
class Model:
    name: str
    task: str
    upstream: str  # under validated/vision/
    upstream_sha256: str
    upstream_bytes: int
    sha256: str
    nbytes: int
    licence: str
    licence_files: tuple[str, ...]
    changes: str
    output: str
    cut: str | None = None  # the output to cut after ("472_quantized" / "472"), or None
    elem: str = ""  # the cut output's type: "UINT8" / "FLOAT"
    prune_inputs: bool = False
    extra: Mapping[str, Any] = field(default_factory=dict)


MODELS: tuple[Model, ...] = (
    Model(
        name="mobilenetv2-int8-embed.onnx",
        task="embed",
        upstream="classification/mobilenet/model/mobilenetv2-12-int8.onnx",
        upstream_sha256="cc028fe6cae7bc11a4ff53cfc9b79c920e8be65ce33a904ec3e2a8f66d77f95f",
        upstream_bytes=3_655_033,
        sha256="c32ba47ca0cadf3845f771da1e429aa992e7b92d598b1e1a68054ed6b54e4ab0",
        nbytes=2_368_080,
        licence="Apache-2.0",
        licence_files=("LICENSE-onnx-models.txt", "NOTICE-wardrobe-models.txt"),
        changes=(
            "Modified (Apache-2.0 section 4): cut after the global average pool and its Reshape "
            "(output 472_quantized, uint8 x 1280); the classifier removed; weights byte-identical."
        ),
        output="472_quantized: uint8[batch, 1280]",
        cut="472_quantized",
        elem="UINT8",
        extra={
            "quant": {"zero_point": 0, "scale": INT8_SCALE},
            "model": "mnv2-int8-1",
            "selfcheck": {
                "input": RAMP,
                "sha256": "e5b53d7e5bf35dda17217bb1feed42f900451b5fe1f2db3eca1f50442bf15abd",
            },
        },
    ),
    Model(
        name="version-RFB-320.onnx",
        task="face",
        upstream="body_analysis/ultraface/models/version-RFB-320.onnx",
        upstream_sha256="34cd7e60aeff28744c657de7a3dc64e872d506741de66987f3426f2b79f88017",
        upstream_bytes=1_270_727,
        sha256="34cd7e60aeff28744c657de7a3dc64e872d506741de66987f3426f2b79f88017",
        nbytes=1_270_727,
        licence="MIT",
        licence_files=("LICENSE-ultraface.txt",),
        changes="None: served as upstream.",
        output="scores float[1, 4420, 2], boxes float[1, 4420, 4]",
        extra={
            "selfcheck": {
                "input": "((i % 251) / 250) * 2 - 1 over float32[1, 3, 240, 320]",
                "top": [0.07956, 0.07937, 0.07899, 0.07852, 0.07781],
                "tol": 0.002,
            }
        },
    ),
    Model(
        name="ssd_mobilenet_v1_12-int8.onnx",
        task="person",
        upstream="object_detection_segmentation/ssd-mobilenetv1/model/ssd_mobilenet_v1_12-int8.onnx",
        upstream_sha256="2b79e6a7fb1ec6a33f332b9b10d82d9de4b7b49dcd26b5946921bb356895c954",
        upstream_bytes=9_540_809,
        sha256="2b79e6a7fb1ec6a33f332b9b10d82d9de4b7b49dcd26b5946921bb356895c954",
        nbytes=9_540_809,
        licence=ZOO_MIT,
        licence_files=("LICENSE-tensorflow-models.txt", "NOTICE-wardrobe-models.txt"),
        changes="None: served as upstream.",
        output="detection boxes, classes (COCO; person is 1), scores, count",
        extra={
            "selfcheck": {
                "input": (
                    "the drawn silhouette (console-vision.js SELFCHECK: a dark figure against a "
                    "pale sky) as uint8[1, 300, 300, 3]"
                ),
                "class": 1,
                "score": 0.9449,
                "box": [0.1013, 0.2648, 0.8171, 0.7278],
                "tol": 0.03,
            }
        },
    ),
)
FALLBACK = Model(
    name="mobilenetv2-fp32-embed.onnx",
    task="embed",
    upstream="classification/mobilenet/model/mobilenetv2-12.onnx",
    upstream_sha256="c0c3f76d93fa3fd6580652a45618618a220fced18babf65774ed169de0432ad5",
    upstream_bytes=13_964_571,
    sha256="d0049881dc99da166c7519a596df35ca0d25bff5c223fe0c72cd76deb150c793",
    nbytes=8_840_380,
    licence="Apache-2.0",
    licence_files=("LICENSE-onnx-models.txt", "NOTICE-wardrobe-models.txt"),
    changes=(
        "Modified (Apache-2.0 section 4): cut after the global average pool and its Reshape "
        "(output 472, float x 1280); the classifier removed; weights byte-identical. The phone "
        "quantizes its output with the int8 file's scale (uint8, mnv2-fp32-1)."
    ),
    output="472: float[batch, 1280]",
    cut="472",
    elem="FLOAT",
    prune_inputs=True,
    extra={
        "quant": {"zero_point": 0, "scale": INT8_SCALE},
        "model": "mnv2-fp32-1",
        "selfcheck": {
            "input": RAMP + ", quantized with the int8 scale",
            "sha256": "5785a2efe90c29332a4a68f1c571f75024366ba38b359444f417b82c24f31306",
        },
    },
)
# The licence texts, each at a pinned commit, with its own sum.
LICENCES: Mapping[str, tuple[str, str]] = {
    "LICENSE-onnx-models.txt": (
        f"https://raw.githubusercontent.com/onnx/models/{COMMIT}/LICENSE",
        "cfc7749b96f63bd31c3c42b5c471bf756814053e847c10f3eb003417bc523d30",
    ),
    "LICENSE-ultraface.txt": (
        "https://raw.githubusercontent.com/Linzaer/Ultra-Light-Fast-Generic-Face-Detector-1MB/"
        "dffdddda9794a50607cba8f318507a28c1c27cab/LICENSE",
        "21f0df2b54c9fef1b4f4061dd0b153bc72f071b5ce9fc04234f13ebfd093b44c",
    ),
    "LICENSE-tensorflow-models.txt": (
        "https://raw.githubusercontent.com/tensorflow/models/"
        "19f287775ae950e22a9b5fb82727e72cff2e3664/LICENSE",
        "5b17814bf0de8cf65069bc6d7cc38cff19fcaa864d243423ad3ef3db01b52385",
    ),
}
NOTICE_NAME = "NOTICE-wardrobe-models.txt"
NOTICE = f"""JARVIS R13 (the wardrobe): the on-device models in vendor/vision/{RELEASE}/

All three come from the ONNX Model Zoo (https://github.com/onnx/models, Apache License 2.0, see
LICENSE-onnx-models.txt) at commit {COMMIT}.

mobilenetv2-int8-embed.onnx - MobileNet v2-1.0 int8 (validated/vision/classification/mobilenet;
  the model page: "SPDX-License-Identifier: Apache-2.0", "License: Apache 2.0"). MODIFIED (Apache
  License 2.0, section 4(b)): JARVIS cut the graph after its global average pool and its Reshape
  (output 472_quantized) and removed the classifier; the weights are byte-identical.

version-RFB-320.onnx - UltraFace (validated/vision/body_analysis/ultraface; the model page:
  "License: MIT"; upstream Linzaer/Ultra-Light-Fast-Generic-Face-Detector-1MB, MIT, see
  LICENSE-ultraface.txt). Unmodified.

ssd_mobilenet_v1_12-int8.onnx - SSD-MobileNetV1 int8 (validated/vision/object_detection_
  segmentation/ssd-mobilenetv1; the model page: "License: MIT"). Its weights come from the
  TensorFlow Object Detection API (tensorflow/models, /research: Apache License 2.0, see
  LICENSE-tensorflow-models.txt). Unmodified.

The data that trained these weights (ImageNet, WIDER FACE, COCO) has its own terms, some of them
for non-commercial research; JARVIS uses the published weights under the licences above, for one
person, non-commercially.
"""


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def write_atomic(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".tmp-")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        os.chmod(tmp, 0o644)  # a vendored file, readable like the rest
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def download(url: str, timeout: float = 120.0) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "jarvis-wardrobe-assets"})
    with urllib.request.urlopen(req, timeout=timeout) as r:  # noqa: S310 - pinned https only
        return bytes(r.read())


def _from_dir(folder: Path | None, want: str) -> bytes | None:
    """A file from a folder found by its SHA-256 (the planner's or a reviewer's download)."""
    if folder is None:
        return None
    for path in sorted(folder.iterdir()):
        if path.is_file():
            data = path.read_bytes()
            if sha256(data) == want:
                return data
    return None


def upstream(m: Model, folder: Path | None) -> bytes:
    data = _from_dir(folder, m.upstream_sha256)
    if data is None:
        data = download(BASE + m.upstream)
    if sha256(data) != m.upstream_sha256 or len(data) != m.upstream_bytes:
        raise SystemExit(f"refused: {m.upstream} does not match its pinned SHA-256")
    return data


def cut(m: Model, data: bytes) -> bytes:
    """The plan's cut: every node feeding `m.cut`, unused initializers and value_info dropped."""
    import onnx  # noqa: PLC0415 - the dev tool's one non-stdlib import, for `fetch` only
    from onnx import TensorProto, helper  # noqa: PLC0415

    if onnx.__version__ != "1.23.2":
        raise SystemExit(f"the cut is pinned to onnx 1.23.2 (found {onnx.__version__})")
    model = onnx.load_from_string(data)
    g = model.graph
    need, kept = {m.cut}, []
    for node in reversed(list(g.node)):
        if any(o in need for o in node.output):
            kept.append(node)
            need.update(i for i in node.input if i)
    kept.reverse()
    del g.node[:]
    g.node.extend(kept)
    elem = getattr(TensorProto, m.elem)
    del g.output[:]
    g.output.extend([helper.make_tensor_value_info(m.cut, elem, ["batch_size", 1280])])
    used = {i for node in g.node for i in node.input}
    inits = [t for t in g.initializer if t.name in used]
    del g.initializer[:]
    g.initializer.extend(inits)
    infos = [v for v in g.value_info if v.name in used]
    del g.value_info[:]
    g.value_info.extend(infos)
    if m.prune_inputs:
        inputs = [i for i in g.input if i.name in used or i.name == "input"]
        del g.input[:]
        g.input.extend(inputs)
    out = model.SerializeToString()
    return bytes(out)


def served(m: Model, folder: Path | None) -> bytes:
    data = upstream(m, folder)
    data = cut(m, data) if m.cut else data
    if sha256(data) != m.sha256 or len(data) != m.nbytes:
        raise SystemExit(f"refused: the cut {m.name} does not match its pinned SHA-256")
    return data


def entry(m: Model) -> dict[str, Any]:
    return {
        "sha256": m.sha256,
        "bytes": m.nbytes,
        "type": OCTET,
        "task": m.task,
        "source": BASE + m.upstream,
        "upstream_sha256": m.upstream_sha256,
        "upstream_bytes": m.upstream_bytes,
        "licence": m.licence,
        "licence_files": list(m.licence_files),
        "changes": m.changes,
        "output": m.output,
        **m.extra,
    }


def manifest(models: tuple[Model, ...]) -> dict[str, Any]:
    return {
        "release": RELEASE,
        "commit": COMMIT,
        "files": {m.name: entry(m) for m in models},
        "licences": {name: want for name, (_, want) in sorted(LICENCES.items())},
        "notice": {NOTICE_NAME: sha256(NOTICE.encode())},
        "fallback": {FALLBACK.name: {**entry(FALLBACK), "vendored": FALLBACK in models}},
    }


def manifest_bytes(models: tuple[Model, ...]) -> bytes:
    return (json.dumps(manifest(models), indent=1, sort_keys=False) + "\n").encode()


def fetch(folder: Path | None, *, fallback: bool) -> None:
    models = (*MODELS, FALLBACK) if fallback else MODELS
    files = {m.name: served(m, folder) for m in models}
    texts: dict[str, bytes] = {}
    for name, (url, want) in LICENCES.items():
        found = _from_dir(folder, want) or download(url)
        if sha256(found) != want:
            raise SystemExit(f"refused: {name} does not match its pinned SHA-256")
        texts[name] = found
    for name, data in files.items():
        write_atomic(FOLDER / name, data)
    for name, data in texts.items():
        write_atomic(VISION / name, data)
    write_atomic(VISION / NOTICE_NAME, NOTICE.encode())
    write_atomic(FOLDER / "MANIFEST.json", manifest_bytes(models))
    print(f"wrote {len(files)} model files, {len(texts)} licences and MANIFEST.json")


def write_manifest() -> None:
    """MANIFEST.json from the pins, without the network: every vendored file must match first."""
    try:
        listed = json.loads((FOLDER / "MANIFEST.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        listed = {}  # no manifest yet: the fallback counts only once it is vendored
    fallback = bool(listed.get("fallback", {}).get(FALLBACK.name, {}).get("vendored"))
    models = (*MODELS, FALLBACK) if fallback else MODELS
    for m in models:
        path = FOLDER / m.name
        if not path.is_file() or sha256(path.read_bytes()) != m.sha256:
            raise SystemExit(f"refused: {m.name} is missing or not its pinned SHA-256")
    write_atomic(FOLDER / "MANIFEST.json", manifest_bytes(models))
    print("wrote MANIFEST.json")


def problems() -> list[str]:
    """What `check` finds wrong in the folder (empty: all good)."""
    out: list[str] = []
    try:
        listed = json.loads((FOLDER / "MANIFEST.json").read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return [f"MANIFEST.json unreadable: {type(exc).__name__}"]
    vendored = (
        (*MODELS, FALLBACK)
        if listed.get("fallback", {}).get(FALLBACK.name, {}).get("vendored")
        else MODELS
    )
    if listed != manifest(vendored):
        out.append("MANIFEST.json is not the one this script writes")
    for m in vendored:
        path = FOLDER / m.name
        if not path.is_file() or sha256(path.read_bytes()) != m.sha256:
            out.append(f"{m.name}: missing or not its pinned SHA-256")
    for name, (_, want) in LICENCES.items():
        path = VISION / name
        if not path.is_file() or sha256(path.read_bytes()) != want:
            out.append(f"{name}: missing or not its pinned SHA-256")
    if (VISION / NOTICE_NAME).read_text(encoding="utf-8") != NOTICE:
        out.append(f"{NOTICE_NAME} differs")
    extra = {p.name for p in FOLDER.iterdir()} - {"MANIFEST.json", *(m.name for m in vendored)}
    if extra:
        out.append(f"files the manifest does not list: {sorted(extra)}")
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("check")
    sub.add_parser("manifest")
    f = sub.add_parser("fetch")
    f.add_argument("--from", dest="folder", type=Path, default=None)
    f.add_argument("--fallback", action="store_true")
    args = ap.parse_args(argv)
    if args.cmd == "fetch":
        fetch(args.folder, fallback=args.fallback)
        return 0
    if args.cmd == "manifest":
        write_manifest()
        return 0
    found = problems()
    for line in found:
        print(line, file=sys.stderr)
    print("wardrobe assets: " + ("FAILED" if found else "OK"))
    return 1 if found else 0


if __name__ == "__main__":
    raise SystemExit(main())
