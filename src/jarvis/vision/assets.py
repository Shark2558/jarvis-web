# src/jarvis/vision/assets.py
"""R7 D14: the files each vision task loads, from JARVIS itself (`static/vendor/vision/<RELEASE>/`).

The route (`api/console.py`, I0 seam 11) serves only what that folder's MANIFEST.json lists with
a matching SHA-256; `scripts/vision_assets.py` fetches, verifies and records them. A task is
installed when every file it needs is served; `quality` is plain arithmetic and needs none. The
two MediaPipe model files sit on a Google storage host this workspace cannot reach, so until CI
or the owner's laptop fetches and pins them, `pose` and `objects` say "not installed".

R13 I0 (docs/plans/r13-wardrobe.md D8, plan review M7): the wardrobe's own release `r13-1`
(`WARDROBE_RELEASE`, `WARDROBE_FILES`): the MobileNet v2 int8 cut for `embed` (or its fp32 cut, the
fallback, only if vendored), UltraFace for `face`, SSD-MobileNetV1 for `person`; `colour` is plain
arithmetic. `scripts/wardrobe_assets.py` fetches, checks and cuts them and writes that folder's
MANIFEST.json. `installed(served)` answers R7's five tasks as before; with the wardrobe release's
files too (`installed(served, served13)`) it answers the four wardrobe tasks as well.

R8 I0 (docs/plans/r8-vision.md v8.0.3 4.2, 4.11, seam S4; builder A from I0 on): the release
`r8-1` (`R8_RELEASE`, `R8_FILES`) for the two new model files, the hand landmarker (`hands`) and
the full pose model (`pose`'s upgrade on the workout phone and the home laptop, D4); both
Apache-2.0, fetched and hashed twice by CI (`.github/workflows/vision-models.yml`, ADR-50).
`installed(served, served13, served8)` answers `hands` only when given the r8-1 files too, and
`digits` (D7) needs no file at I0 (builder D's method decides; until then its body says "not
installed"). The home laptop's pose runtime (builder J) reads the same pinned files.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

RELEASE = "r7-1"
FOLDER = Path(__file__).resolve().parents[1] / "api" / "static" / "vendor" / "vision"
NOT_INSTALLED = "not installed"
MEDIAPIPE: tuple[str, ...] = (
    "vision_bundle.mjs",
    "vision_wasm_internal.js",
    "vision_wasm_internal.wasm",
)
POSE_MODEL = "pose_landmarker_lite.task"
OBJECT_MODEL = "efficientdet_lite0.tflite"
TASK_FILES: Mapping[str, tuple[str, ...]] = {
    "text": (
        "tesseract.esm.min.js",
        "tesseract-worker.min.js",
        "tesseract-core-simd-lstm.js",
        "tesseract-core-simd-lstm.wasm",
        "eng.traineddata",
    ),
    "code": ("zxing-reader.iife.js", "zxing_reader.wasm"),
    "objects": (*MEDIAPIPE, OBJECT_MODEL),
    "pose": (*MEDIAPIPE, POSE_MODEL),
    "quality": (),
}
R8_RELEASE = "r8-1"
HAND_MODEL = "hand_landmarker.task"
POSE_FULL_MODEL = "pose_landmarker_full.task"
R8_FILES: Mapping[str, tuple[str, ...]] = {"hands": (HAND_MODEL,), "pose_full": (POSE_FULL_MODEL,)}
WARDROBE_RELEASE = "r13-1"
EMBED_INT8 = "mobilenetv2-int8-embed.onnx"
EMBED_FP32 = "mobilenetv2-fp32-embed.onnx"  # the fallback (D8): not vendored unless needed
WARDROBE_FILES: Mapping[str, tuple[str, ...]] = {
    "embed": (EMBED_INT8,),
    "colour": (),
    "person": ("ssd_mobilenet_v1_12-int8.onnx",),
    "face": ("version-RFB-320.onnx",),
}


def installed(
    served: Mapping[str, str],
    served13: Mapping[str, str] | None = None,
    served8: Mapping[str, str] | None = None,
) -> dict[str, bool]:
    """{task: every file it needs is served} (`served`: the route's `vision_files(RELEASE)`;
    `served13`, when given: `vision_files(WARDROBE_RELEASE)`, for the four wardrobe tasks;
    `served8`, when given: `vision_files(R8_RELEASE)`, for `hands`, which also needs MediaPipe's
    runtime from `served`)."""
    out = {task: all(name in served for name in files) for task, files in TASK_FILES.items()}
    if served8 is not None:
        out["hands"] = all(n in served for n in MEDIAPIPE) and HAND_MODEL in served8
    if served13 is None:
        return out
    for task, files in WARDROBE_FILES.items():
        out[task] = all(name in served13 for name in files)
    out["embed"] = out["embed"] or EMBED_FP32 in served13
    return out


def why(task: str, served: Mapping[str, str], served13: Mapping[str, str] | None = None) -> str:
    """The empty word when the task can run here, else the plain reason ("not installed")."""
    return "" if installed(served, served13).get(task) else NOT_INSTALLED


__all__ = [
    "EMBED_FP32",
    "EMBED_INT8",
    "FOLDER",
    "HAND_MODEL",
    "POSE_FULL_MODEL",
    "R8_FILES",
    "R8_RELEASE",
    "MEDIAPIPE",
    "NOT_INSTALLED",
    "OBJECT_MODEL",
    "POSE_MODEL",
    "RELEASE",
    "TASK_FILES",
    "WARDROBE_FILES",
    "WARDROBE_RELEASE",
    "installed",
    "why",
]
