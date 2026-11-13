# src/jarvis/vision/assets.py
"""R7 D14: the files each vision task loads, from JARVIS itself (`static/vendor/vision/<RELEASE>/`).

The route (`api/console.py`, I0 seam 11) serves only what that folder's MANIFEST.json lists with
a matching SHA-256; `scripts/vision_assets.py` fetches, verifies and records them. A task is
installed when every file it needs is served; `quality` is plain arithmetic and needs none. The
two MediaPipe model files sit on a Google storage host this workspace cannot reach, so until CI
or the owner's laptop fetches and pins them, `pose` and `objects` say "not installed".
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


def installed(served: Mapping[str, str]) -> dict[str, bool]:
    """{task: every file it needs is served} (`served`: the route's `vision_files(RELEASE)`)."""
    return {task: all(name in served for name in files) for task, files in TASK_FILES.items()}


def why(task: str, served: Mapping[str, str]) -> str:
    """The empty word when the task can run here, else the plain reason ("not installed")."""
    return "" if installed(served).get(task) else NOT_INSTALLED


__all__ = [
    "FOLDER",
    "MEDIAPIPE",
    "NOT_INSTALLED",
    "OBJECT_MODEL",
    "POSE_MODEL",
    "RELEASE",
    "TASK_FILES",
    "installed",
    "why",
]
