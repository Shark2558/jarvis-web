# src/jarvis/homebridge/face_engine.py
"""The laptop's face engine for still pictures (R11.1 O7; plan D15). Ships in the home kit.

`OpenCvEngine.faces(jpeg)` finds the faces in one picture and gives each as a `SeenFace`: a
128-number embedding (OpenCV's SFace recogniser), the detector's confidence (OpenCV's YuNet), the
face's size and a small crop. Embeddings and crops go only to `face_store` on this laptop.

- Models: two ONNX files from github.com/opencv/opencv_zoo, pinned here by commit, size and
  SHA-256 (`MODELS`; YuNet is MIT, SFace is Apache-2.0). The kit's setup downloads them into
  `models/`; a file that is missing or is not the pinned one is never loaded (`EngineOff`, in
  plain words: the bridge and the camera keep working, photos and face groups wait).
- Decoder safety (the laptop is the only decoder): JPEG only; the size is read from the header
  BEFORE decoding (`jpeg.jpeg_size`); a picture from the cloud must be at most 2048 px a side and
  4.2 megapixels and is never resized here; the owner's own file from the watched folder may be
  larger and is then decoded at 1/2, 1/4 or 1/8 size by the JPEG decoder itself, never at full
  size; the decoded shape is checked again.
- Detection runs twice, at <= 1024 px and at <= 384 px on the long side: YuNet finds faces of
  about 10 to 300 px, so the small pass is what finds a close-up. Overlapping finds are one face.
  A face under `MIN_FACE` px or under the detector's `DETECT_SCORE` is left out; at most 20 a
  picture.

OpenCV and NumPy are loaded by name when the engine is first used (`RUNTIME_PACKAGES`): they are
in the bridge image only (hash-locked in deploy/home/bridge-requirements.txt), never in the cloud
image, and a bridge without them still starts. One picture at a time (the caller holds a lock).
"""

from __future__ import annotations

import hashlib
import importlib
import logging
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from jarvis.homebridge.face_store import MAX_FACES_PER_PICTURE
from jarvis.homebridge.face_types import DIM, SeenFace
from jarvis.homebridge.jpeg import PictureRefused, jpeg_size

log = logging.getLogger(__name__)

ZOO_COMMIT = "48b10fa505aeb51fbd127fc60a5c660040e823b7"
_ZOO = f"https://media.githubusercontent.com/media/opencv/opencv_zoo/{ZOO_COMMIT}/models"
# import name -> the package the bridge image installs (tests/test_deploy_home.py checks the pins)
RUNTIME_PACKAGES = {"cv2": "opencv-python-headless", "numpy": "numpy"}
MAX_SIDE = 2048
MAX_PIXELS = 4_200_000
OWN_MAX_SIDE = 16_384  # the owner's own file: decoded smaller, never refused for being a photo
OWN_MAX_PIXELS = 150_000_000
DETECT_SIDES = (1024, 384)
DETECT_SCORE = 0.8
MIN_FACE = 40
SAME_FACE_IOU = 0.4
CROP_SIDE = 192
CROP_MARGIN = 0.35
CROP_QUALITY = 85
READY = "ready"
NO_LIBRARY = "the picture library is missing from the bridge: update the home kit"
NO_MODELS = "the face model files are not on this laptop yet: run the home kit's update"
CHANGED_MODEL = "a face model file is not the reviewed one, so it was not loaded: run the update"


@dataclass(frozen=True)
class ModelPin:
    name: str
    sha256: str
    size: int
    licence: str
    source: str


MODELS = (
    ModelPin(
        "face_detection_yunet_2026may.onnx",
        "ebafce4e3c118d6554634be5c27ab333b4c047a9a8c3faf1d7cf93101c22f0f0",
        229_738,
        "MIT",
        f"{_ZOO}/face_detection_yunet/face_detection_yunet_2026may.onnx",
    ),
    ModelPin(
        "face_recognition_sface_2021dec.onnx",
        "0ba9fbfa01b5270c96627c4ef784da859931e02f04419c829e83484087c34e79",
        38_696_353,
        "Apache-2.0",
        f"{_ZOO}/face_recognition_sface/face_recognition_sface_2021dec.onnx",
    ),
)


class EngineOff(RuntimeError):
    """The engine can't look at pictures on this laptop right now (plain words)."""


class FaceEngine(Protocol):
    def status(self) -> str: ...

    def faces(self, jpeg: bytes, *, own_file: bool = False) -> list[SeenFace]: ...


def reduction(width: int, height: int, *, own_file: bool) -> int:
    """By how much the decoder shrinks the picture (1, 2, 4 or 8), or `PictureRefused`."""
    if not own_file:
        if max(width, height) > MAX_SIDE or width * height > MAX_PIXELS:
            raise PictureRefused("too_large")
        return 1
    if max(width, height) > OWN_MAX_SIDE or width * height > OWN_MAX_PIXELS:
        raise PictureRefused("too_large")
    return next(k for k in (1, 2, 4, 8) if max(width, height) <= MAX_SIDE * k)


def _overlap(a: Any, b: Any) -> float:
    """Intersection over union of two detector rows' boxes (x, y, w, h)."""
    ax, ay, aw, ah = (float(v) for v in a[:4])
    bx, by, bw, bh = (float(v) for v in b[:4])
    wide = min(ax + aw, bx + bw) - max(ax, bx)
    high = min(ay + ah, by + bh) - max(ay, by)
    if wide <= 0 or high <= 0:
        return 0.0
    both = wide * high
    return both / (aw * ah + bw * bh - both)


def _file_ok(path: Path, pin: ModelPin) -> bool:
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


class OpenCvEngine:
    def __init__(
        self,
        models_dir: Path,
        *,
        detect_score: float = DETECT_SCORE,
        min_face: int = MIN_FACE,
        load: Callable[[str], Any] = importlib.import_module,
    ) -> None:
        self._dir = models_dir
        self._score = detect_score
        self._min_face = min_face
        self._load = load
        self._cv: Any = None
        self._np: Any = None
        self._det: Any = None
        self._rec: Any = None
        self._why = ""
        self.last_shape: tuple[int, int] = (0, 0)  # the last decoded picture (height, width)

    # ---- loading -------------------------------------------------------------------------------

    def install(self, cv: Any, np: Any, detector: Any, recogniser: Any) -> None:
        """The loaded parts (tests give fakes for the two models)."""
        self._cv, self._np, self._det, self._rec, self._why = cv, np, detector, recogniser, ""

    def _start(self) -> str:
        """Load the libraries and the two pinned models once. Returns "" or why it can't."""
        try:
            cv, np = self._load("cv2"), self._load("numpy")
        except ImportError:
            return NO_LIBRARY
        paths = [self._dir / pin.name for pin in MODELS]
        if not all(p.is_file() for p in paths):
            return NO_MODELS
        if not all(_file_ok(p, pin) for p, pin in zip(paths, MODELS, strict=True)):
            return CHANGED_MODEL
        try:
            cv.setNumThreads(2)  # leave the laptop's other cores to the camera
            det = cv.FaceDetectorYN.create(str(paths[0]), "", (320, 320), self._score, 0.3, 200)
            rec = cv.FaceRecognizerSF.create(str(paths[1]), "")
        except Exception as exc:  # noqa: BLE001 - OpenCV's own error text stays in the log
            log.error("the face models could not be loaded", extra={"error": type(exc).__name__})
            return NO_LIBRARY
        self.install(cv, np, det, rec)
        return ""

    def status(self) -> str:
        if self._det is None:
            self._why = self._start()
        return READY if self._det is not None else self._why

    # ---- one picture ---------------------------------------------------------------------------

    def _decode(self, data: bytes, own_file: bool) -> Any:
        cv, np = self._cv, self._np
        scale = reduction(*jpeg_size(data), own_file=own_file)
        flag = {
            1: cv.IMREAD_COLOR,
            2: cv.IMREAD_REDUCED_COLOR_2,
            4: cv.IMREAD_REDUCED_COLOR_4,
            8: cv.IMREAD_REDUCED_COLOR_8,
        }[scale]
        try:
            img = cv.imdecode(np.frombuffer(data, dtype=np.uint8), flag)
        except Exception:  # noqa: BLE001 - a broken file is a refused picture, never a crash
            img = None
        if img is None or img.ndim != 3 or img.shape[2] != 3:
            raise PictureRefused("unreadable")
        if max(img.shape[:2]) > MAX_SIDE + 8:  # what was decoded is what the header promised
            raise PictureRefused("too_large")
        self.last_shape = (int(img.shape[0]), int(img.shape[1]))
        return img

    def _detect(self, img: Any) -> list[Any]:
        """Detector rows in the picture's own coordinates, best first, one per face."""
        cv = self._cv
        high, wide = img.shape[:2]
        rows: list[Any] = []
        for side in DETECT_SIDES:
            k = min(1.0, side / max(high, wide))
            small = img
            if k < 1.0:
                size = (max(1, round(wide * k)), max(1, round(high * k)))
                small = cv.resize(img, size, interpolation=cv.INTER_AREA)
            self._det.setInputSize((int(small.shape[1]), int(small.shape[0])))
            _, found = self._det.detect(small)
            for row in found if found is not None else ():
                scaled = row.astype(self._np.float32).copy()
                scaled[:14] /= k
                rows.append(scaled)
            if k == 1.0 and max(high, wide) <= DETECT_SIDES[-1]:
                break  # a small picture: the second pass would be the same picture again
        rows.sort(key=lambda r: -float(r[14]))
        kept: list[Any] = []
        for row in rows:
            if all(_overlap(row, other) < SAME_FACE_IOU for other in kept):
                kept.append(row)
        return kept

    def _crop(self, img: Any, row: Any) -> bytes:
        cv = self._cv
        x, y, w, h = (float(v) for v in row[:4])
        high, wide = img.shape[:2]
        left = max(0, int(x - w * CROP_MARGIN))
        top = max(0, int(y - h * CROP_MARGIN))
        right = min(wide, int(x + w * (1 + CROP_MARGIN)))
        bottom = min(high, int(y + h * (1 + CROP_MARGIN)))
        part = img[top:bottom, left:right]
        if part.size == 0:
            return b""
        k = min(1.0, CROP_SIDE / max(part.shape[:2]))
        if k < 1.0:
            size = (max(1, round(part.shape[1] * k)), max(1, round(part.shape[0] * k)))
            part = cv.resize(part, size, interpolation=cv.INTER_AREA)
        ok, data = cv.imencode(".jpg", part, [cv.IMWRITE_JPEG_QUALITY, CROP_QUALITY])
        return bytes(data.tobytes()) if ok else b""

    def faces(self, jpeg: bytes, *, own_file: bool = False) -> list[SeenFace]:
        if self.status() != READY:
            raise EngineOff(self._why)
        img = self._decode(jpeg, own_file)
        out: list[SeenFace] = []
        for row in self._detect(img):
            size = int(min(float(row[2]), float(row[3])))
            score = float(row[14])
            if size < self._min_face or score < self._score:
                continue
            aligned = self._rec.alignCrop(img, row)
            vector = tuple(float(v) for v in self._rec.feature(aligned).reshape(-1))
            if len(vector) != DIM:
                raise EngineOff(CHANGED_MODEL)
            out.append(SeenFace(vector, min(1.0, score), size, self._crop(img, row)))
            if len(out) >= MAX_FACES_PER_PICTURE:
                break
        return out


__all__ = [
    "MAX_PIXELS",
    "MAX_SIDE",
    "MODELS",
    "READY",
    "RUNTIME_PACKAGES",
    "ZOO_COMMIT",
    "EngineOff",
    "FaceEngine",
    "ModelPin",
    "OpenCvEngine",
    "PictureRefused",
    "reduction",
]
