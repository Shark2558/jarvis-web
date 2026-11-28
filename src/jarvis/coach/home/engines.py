# src/jarvis/coach/home/engines.py
"""R8 row 216's home leg (docs/plans/r8-vision.md v8.0.4 section 4.5a; the owner's D3 and D4;
ADR-49; builder J): what touches the home camera's pictures on the home laptop. Ships in the home
kit (`jarvis.coach.home` is kit-safe: the standard library and Pydantic here; OpenCV, NumPy and
MediaPipe are loaded by name, `RUNTIME_PACKAGES`, and are in the bridge image only, hash-locked).

- `OpenCvSource`: the camera's RTSP sub-stream through OpenCV's FFmpeg reader. The address (with
  the camera's user name and password) comes from `HOMEVISION_RTSP_URL` in bridge.env and stays
  on the laptop: it is never logged, sent or put in an error (`SourceDown` carries a short word).
  Only `rtsp://` to a private-range IP literal is accepted (`rtsp_url_ok`: RFC 1918 or fc00::/7,
  as the no-cloud check's rule), so the bridge only ever pulls from the home network. Between two
  looks every frame is grabbed and thrown away undecoded to colour, so a look is always the
  newest picture; a look is one RGB frame that lives only inside one step of the runtime.
- `MediaPipePose`: MediaPipe's pose landmarker (Apache-2.0), VIDEO mode, up to `BODIES_MAX` 4
  bodies. The model files are the same pinned files as the browser's (`POSE_MODELS`: the lite
  model of release r7-1, the full model of r8-1); a file whose size or SHA-256 is not the pinned
  one is never loaded, and a pin that is still empty (before the vision-models workflow, ADR-50)
  loads nothing. D4: the full model while the laptop keeps `FULL_FPS` 15 frames a second with it
  (measured on the first `BENCH_FRAMES` looks), else the lite model.
- `MediaPipeObjects`: MediaPipe's object detector for the `objects` task (cup, phone, chair ...),
  only with a pinned model whose licence was read as permissive (D9); until then `objects` is
  "not installed" and the home use cases get poses only.

MediaPipe's Python package imports matplotlib for its drawing helpers, which the bridge never
uses; the image does not install matplotlib, so `load_mediapipe` puts an inert stand-in in its
place for the import only (any use of it raises).
"""

from __future__ import annotations

import hashlib
import importlib
import importlib.util
import ipaddress
import logging
import math
import sys
import threading
import time
import types
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, Protocol
from urllib.parse import urlsplit

from jarvis.homebridge.face_engine import ModelPin

log = logging.getLogger(__name__)

# import name -> the package the bridge image installs (tests check each is hash-locked)
RUNTIME_PACKAGES = {"cv2": "opencv-python-headless", "numpy": "numpy", "mediapipe": "mediapipe"}
READY = "ready"
BODIES_MAX = 4
POSE_POINTS = 33
FULL_FPS = 15.0  # D4
BENCH_FRAMES = 15
OPEN_TIMEOUT_MS = 8000
READ_TIMEOUT_MS = 8000
MAX_MISSES = 30  # grabs in a row that give nothing before the stream counts as down
MAX_PIXELS = 4_200_000  # a sub-stream is far smaller; a 4 MP main stream still fits
OBJECT_SCORE = 0.4
OBJECTS_MAX = 20
_MP = "https://storage.googleapis.com/mediapipe-models"
# The same files the browser loads (src/jarvis/api/static/vendor/vision/r7-1 and r8-1). Their
# SHA-256 and size are filled from those manifests when the vision-models workflow has pinned them
# (ADR-50; tests/test_r8_j_homevision.py fails until both agree); empty = not pinned = never loaded.
POSE_MODELS: dict[str, ModelPin] = {
    "full": ModelPin(
        "pose_landmarker_full.task",
        "",
        0,
        "Apache-2.0",
        f"{_MP}/pose_landmarker/pose_landmarker_full/float16/1/pose_landmarker_full.task",
    ),
    "lite": ModelPin(
        "pose_landmarker_lite.task",
        "",
        0,
        "Apache-2.0",
        f"{_MP}/pose_landmarker/pose_landmarker_lite/float16/1/pose_landmarker_lite.task",
    ),
}
OBJECT_MODEL = ModelPin(
    "efficientdet_lite0.tflite",
    "",
    0,
    "to be read",  # D9: loaded only once this names a permissive licence
    f"{_MP}/object_detector/efficientdet_lite0/int8/1/efficientdet_lite0.tflite",
)
PERMISSIVE = frozenset({"Apache-2.0", "MIT", "BSD-2-Clause", "BSD-3-Clause"})  # ADR-29

NO_LIBRARY = "the picture libraries are missing from the bridge: update the home kit"
NO_MODELS = "the pose model files are not on this laptop yet: run the home kit's update"
CHANGED_MODEL = "a pose model file is not the reviewed one, so it was not loaded: run the update"
NOT_PINNED = "the pose model is not pinned yet: it arrives with the next home kit"
NO_OBJECTS = "the object model is not installed on this laptop"

Model = Literal["lite", "full"]


class SourceDown(RuntimeError):
    """The camera's stream can't be read right now. The message is a short word, never the
    address (`bad_address`, `unreachable`, `no_frames`, `ended`, `too_large`, `no_library`)."""


@dataclass(frozen=True)
class Frame:
    """One decoded RGB picture (H x W x 3, uint8). It never leaves the runtime's step."""

    image: Any
    at: float  # epoch seconds (the Result's `at`)
    mono_ms: int  # a monotonic stamp for the landmarker's VIDEO mode
    width: int
    height: int


class FrameSource(Protocol):
    def open(self) -> None: ...

    def read(self, until: float, stop: threading.Event) -> Frame | None:
        """Grab and drop frames until the monotonic clock reaches `until`, then decode one.
        None when `stop` was set; `SourceDown` when the stream is gone."""
        ...

    def close(self) -> None: ...


class PoseEngine(Protocol):
    model: Model | None

    def status(self) -> str: ...

    def bodies(self, frame: Frame) -> list[list[dict[str, float]]]:
        """Each body's 33 points {x, y, z, visibility} (0..1 of the frame), at most 4 bodies."""
        ...

    def close(self) -> None: ...


class ObjectEngine(Protocol):
    def status(self) -> str: ...

    def objects(self, frame: Frame) -> list[dict[str, Any]]:
        """[{label, score, box: {x, y, w, h}}] with labels from `jarvis.vision.results`."""
        ...

    def close(self) -> None: ...


# ---- the address ---------------------------------------------------------------------------------


def rtsp_url_ok(url: str) -> bool:
    """An `rtsp://` address of a private-range IP literal (RFC 1918 or fc00::/7)."""
    try:
        parts = urlsplit(url.strip())
        host = parts.hostname or ""
        ip = ipaddress.ip_address(host)
        port = parts.port
    except ValueError:
        return False
    if parts.scheme != "rtsp" or port == 0:
        return False
    if isinstance(ip, ipaddress.IPv4Address):
        nets = ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16")
        return any(ip in ipaddress.ip_network(n) for n in nets)
    return ip in ipaddress.ip_network("fc00::/7")


def pinned(path: Path, pin: ModelPin) -> bool:
    """The file is the pinned one (size and SHA-256). An empty pin matches nothing."""
    if not pin.sha256 or pin.size <= 0:
        return False
    try:
        if path.stat().st_size != pin.size:
            return False
        digest = hashlib.sha256()
        with path.open("rb") as fh:
            for block in iter(lambda: fh.read(1 << 20), b""):
                digest.update(block)
    except OSError:
        return False
    return digest.hexdigest() == pin.sha256


def load_mediapipe(load: Callable[[str], Any] = importlib.import_module) -> Any:
    """MediaPipe's vision tasks, with an inert matplotlib in place only while it is imported."""
    stand_in = importlib.util.find_spec("matplotlib") is None and "matplotlib" not in sys.modules
    if stand_in:
        sys.modules["matplotlib"] = _Inert("matplotlib")
        sys.modules["matplotlib.pyplot"] = _Inert("matplotlib.pyplot")
    try:
        mp = load("mediapipe")
        vision = load("mediapipe.tasks.python.vision")
        base = load("mediapipe.tasks.python.core.base_options")
    finally:
        if stand_in:
            sys.modules.pop("matplotlib.pyplot", None)
            sys.modules.pop("matplotlib", None)
    return types.SimpleNamespace(mp=mp, vision=vision, BaseOptions=base.BaseOptions)


class _Inert(types.ModuleType):
    def __getattr__(self, name: str) -> Any:
        if name.startswith("__"):
            raise AttributeError(name)
        raise RuntimeError("drawing is not part of the home kit")


# ---- the camera's stream ------------------------------------------------------------------------


class OpenCvSource:
    """The RTSP sub-stream through OpenCV's FFmpeg reader (TCP: OPENCV_FFMPEG_CAPTURE_OPTIONS in
    the bridge image). `opener` is for tests (a recorded file); the bridge never passes one."""

    def __init__(
        self,
        url: str,
        *,
        load: Callable[[str], Any] = importlib.import_module,
        opener: Callable[[Any], Any] | None = None,
        clock: Callable[[], float] = time.monotonic,
        wall: Callable[[], float] = time.time,
    ) -> None:
        self._url = url
        self._load = load
        self._opener = opener
        self._clock = clock
        self._wall = wall
        self._cap: Any = None
        self._cv: Any = None
        self._last_ms = 0

    def __repr__(self) -> str:  # never the address
        return "OpenCvSource(<camera>)"

    def open(self) -> None:
        if self._cap is not None:
            return
        if self._opener is None and not rtsp_url_ok(self._url):
            raise SourceDown("bad_address")
        try:
            cv = self._load("cv2")
        except ImportError:
            raise SourceDown("no_library") from None
        self._cv = cv
        try:
            if self._opener is not None:
                cap = self._opener(cv)
            else:
                params = [cv.CAP_PROP_OPEN_TIMEOUT_MSEC, OPEN_TIMEOUT_MS]
                params += [cv.CAP_PROP_READ_TIMEOUT_MSEC, READ_TIMEOUT_MS]
                cap = cv.VideoCapture(self._url, cv.CAP_FFMPEG, params)
        except Exception:  # noqa: BLE001 - OpenCV's text may hold the address: never kept
            raise SourceDown("unreachable") from None
        if cap is None or not cap.isOpened():
            raise SourceDown("unreachable")
        self._cap = cap

    def read(self, until: float, stop: threading.Event) -> Frame | None:
        if self._cap is None:
            self.open()
        cap, misses = self._cap, 0
        while True:
            if stop.is_set():
                return None
            if not cap.grab():
                misses += 1
                if misses >= MAX_MISSES:
                    raise SourceDown("no_frames")
                continue
            misses = 0
            if self._clock() >= until:
                break
        ok, bgr = cap.retrieve()
        if not ok or bgr is None or getattr(bgr, "ndim", 0) != 3:
            raise SourceDown("ended")
        high, wide = int(bgr.shape[0]), int(bgr.shape[1])
        if high * wide > MAX_PIXELS:
            raise SourceDown("too_large")
        rgb = self._cv.cvtColor(bgr, self._cv.COLOR_BGR2RGB)
        stamp = max(self._last_ms + 1, int(self._clock() * 1000))
        self._last_ms = stamp
        return Frame(rgb, float(self._wall()), stamp, wide, high)

    def close(self) -> None:
        cap, self._cap = self._cap, None
        if cap is not None:
            try:
                cap.release()
            except Exception:  # noqa: BLE001 - closing never fails the caller
                log.info("the camera stream did not close cleanly")


# ---- pose (D4) ---------------------------------------------------------------------------------


@dataclass
class _Bench:
    times: list[float] = field(default_factory=list)


class MediaPipePose:
    """The pose landmarker on the laptop's CPU; one frame at a time (the runtime's thread)."""

    def __init__(
        self,
        models_dir: Path,
        *,
        load: Callable[[], Any] = load_mediapipe,
        pins: dict[str, ModelPin] | None = None,
        clock: Callable[[], float] = time.perf_counter,
    ) -> None:
        self._dir = models_dir
        self._load = load
        self._pins = pins if pins is not None else POSE_MODELS
        self._clock = clock
        self._mp: Any = None
        self._task: Any = None
        self._why = ""
        self._bench: _Bench | None = None
        self.model: Model | None = None
        self.capacity: float | None = None  # frames a second the laptop keeps with `model`
        self._usable_lite = False

    def _usable(self) -> tuple[list[Model], str]:
        found: list[Model] = []
        why = NOT_PINNED
        for kind in ("full", "lite"):
            pin = self._pins[kind]
            if not pin.sha256:
                continue
            path = self._dir / pin.name
            if not path.is_file():
                why = NO_MODELS if why == NOT_PINNED else why
                continue
            if not pinned(path, pin):
                why = CHANGED_MODEL
                continue
            found.append(kind)
        return found, why

    def _open(self, kind: Model) -> None:
        mp = self._mp
        opts = mp.vision.PoseLandmarkerOptions(
            base_options=mp.BaseOptions(model_asset_path=str(self._dir / self._pins[kind].name)),
            running_mode=mp.vision.RunningMode.VIDEO,
            num_poses=BODIES_MAX,
        )
        self._task = mp.vision.PoseLandmarker.create_from_options(opts)
        self.model = kind
        self._bench = _Bench() if kind == "full" else None

    def status(self) -> str:
        if self._task is not None:
            return READY
        usable, why = self._usable()
        if not usable:
            self._why = why
            return why
        try:
            self._mp = self._mp or self._load()
            self._open(usable[0])
        except ImportError:
            self._why = NO_LIBRARY
            return NO_LIBRARY
        except Exception as exc:  # noqa: BLE001 - MediaPipe's own text stays out of the log
            log.error("the pose model could not be loaded", extra={"error": type(exc).__name__})
            self._why = NO_LIBRARY
            return NO_LIBRARY
        self._usable_lite = "lite" in usable
        return READY

    def bodies(self, frame: Frame) -> list[list[dict[str, float]]]:
        if self._task is None and self.status() != READY:
            return []
        mp = self._mp
        start = self._clock()
        image = mp.mp.Image(image_format=mp.mp.ImageFormat.SRGB, data=frame.image)
        found = self._task.detect_for_video(image, int(frame.mono_ms))
        self._measure(self._clock() - start)
        out: list[list[dict[str, float]]] = []
        for body in list(getattr(found, "pose_landmarks", None) or ())[:BODIES_MAX]:
            points = [_point(p) for p in list(body)[:POSE_POINTS]]
            if len(points) == POSE_POINTS and all(p is not None for p in points):
                out.append(points)  # type: ignore[arg-type]
        return out

    def _measure(self, took: float) -> None:
        """D4: after the first looks with the full model, keep it only if it keeps 15 a second."""
        bench = self._bench
        if bench is None:
            return
        bench.times.append(max(took, 1e-6))
        if len(bench.times) < BENCH_FRAMES:
            return
        self._bench = None
        self.capacity = round(len(bench.times) / sum(bench.times), 1)
        if self.capacity < FULL_FPS and self._usable_lite:
            log.info("the full pose model is too slow on this laptop: the lite one is used")
            self.close()
            self._open("lite")

    def close(self) -> None:
        task, self._task = self._task, None
        self.model = None
        if task is not None:
            try:
                task.close()
            except Exception:  # noqa: BLE001
                log.info("the pose model did not close cleanly")


def _point(p: Any) -> dict[str, float] | None:
    try:
        x, y, z = float(p.x), float(p.y), float(p.z)
        vis = float(getattr(p, "visibility", None) or 0.0)
    except (TypeError, ValueError):
        return None
    if not all(math.isfinite(v) for v in (x, y, z, vis)):
        return None
    return {  # the Result's ranges (jarvis.vision.results.Point)
        "x": _clamp(x, -1.0, 2.0),
        "y": _clamp(y, -1.0, 2.0),
        "z": _clamp(z, -10.0, 10.0),
        "visibility": _clamp(vis, 0.0, 1.0),
    }


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


# ---- objects (D9) -------------------------------------------------------------------------------


class MediaPipeObjects:
    def __init__(
        self,
        models_dir: Path,
        labels: Sequence[str],
        *,
        load: Callable[[], Any] = load_mediapipe,
        pin: ModelPin = OBJECT_MODEL,
    ) -> None:
        self._dir = models_dir
        self._labels = frozenset(labels)
        self._load = load
        self._pin = pin
        self._task: Any = None
        self._mp: Any = None

    def status(self) -> str:
        if self._task is not None:
            return READY
        path = self._dir / self._pin.name
        if self._pin.licence not in PERMISSIVE or not pinned(path, self._pin):
            return NO_OBJECTS
        try:
            mp = self._mp = self._mp or self._load()
            opts = mp.vision.ObjectDetectorOptions(
                base_options=mp.BaseOptions(model_asset_path=str(path)),
                running_mode=mp.vision.RunningMode.VIDEO,
                max_results=OBJECTS_MAX,
                score_threshold=OBJECT_SCORE,
            )
            self._task = mp.vision.ObjectDetector.create_from_options(opts)
        except Exception as exc:  # noqa: BLE001
            log.error("the object model could not be loaded", extra={"error": type(exc).__name__})
            return NO_OBJECTS
        return READY

    def objects(self, frame: Frame) -> list[dict[str, Any]]:
        if self._task is None and self.status() != READY:
            return []
        mp = self._mp
        image = mp.mp.Image(image_format=mp.mp.ImageFormat.SRGB, data=frame.image)
        found = self._task.detect_for_video(image, int(frame.mono_ms))
        out: list[dict[str, Any]] = []
        wide, high = max(1, frame.width), max(1, frame.height)
        for det in list(getattr(found, "detections", None) or ())[:OBJECTS_MAX]:
            cats = list(getattr(det, "categories", None) or ())
            box = getattr(det, "bounding_box", None)
            if not cats or box is None:
                continue
            label = str(cats[0].category_name or "").strip().lower().replace(" ", "_")
            score = float(cats[0].score or 0.0)
            if label not in self._labels or not 0.0 <= score <= 1.0:
                continue
            out.append(
                {
                    "label": label,
                    "score": score,
                    "box": {
                        "x": _clamp(float(box.origin_x) / wide, 0.0, 1.0),
                        "y": _clamp(float(box.origin_y) / high, 0.0, 1.0),
                        "w": _clamp(float(box.width) / wide, 0.0, 1.0),
                        "h": _clamp(float(box.height) / high, 0.0, 1.0),
                    },
                }
            )
        return out

    def close(self) -> None:
        task, self._task = self._task, None
        if task is not None:
            try:
                task.close()
            except Exception:  # noqa: BLE001
                log.info("the object model did not close cleanly")


def quality_of(
    frame: Frame, load: Callable[[str], Any] = importlib.import_module
) -> dict[str, float]:
    """{light, sharp} 0..1 from a small grey copy (the Result's quality); 1.0 without OpenCV."""
    try:
        cv = load("cv2")
        grey = cv.cvtColor(frame.image, cv.COLOR_RGB2GRAY)
        k = min(1.0, 320 / max(1, frame.width))
        if k < 1.0:
            size = (max(1, round(frame.width * k)), max(1, round(frame.height * k)))
            grey = cv.resize(grey, size, interpolation=cv.INTER_AREA)
        light = float(grey.mean()) / 255.0
        sharp = float(cv.Laplacian(grey, cv.CV_64F).var()) / 500.0
    except Exception:  # noqa: BLE001 - a fake frame, or no OpenCV: quality is not the point
        return {"light": 1.0, "sharp": 1.0}

    def unit(v: float) -> float:
        return round(_clamp(v, 0.0, 1.0), 2) if math.isfinite(v) else 0.0

    return {"light": unit(light), "sharp": unit(sharp)}


__all__ = [
    "BODIES_MAX",
    "FULL_FPS",
    "OBJECT_MODEL",
    "POSE_MODELS",
    "READY",
    "RUNTIME_PACKAGES",
    "Frame",
    "FrameSource",
    "MediaPipeObjects",
    "MediaPipePose",
    "ObjectEngine",
    "OpenCvSource",
    "PoseEngine",
    "SourceDown",
    "load_mediapipe",
    "pinned",
    "quality_of",
    "rtsp_url_ok",
]
