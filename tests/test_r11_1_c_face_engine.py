# tests/test_r11_1_c_face_engine.py -- R11.1 O7 (plan D15): the laptop's face engine for still
# pictures. Decoder safety first (JPEG only, size and pixel caps BEFORE anything is decoded), the
# two model files pinned by hash, plain words when the engine can't run, and the detect -> align
# -> embed -> crop pipeline over a fake detector and recogniser (the real models are not in the
# repository; a last test runs them when JARVIS_FACE_MODELS_DIR points at the downloaded files).
from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Any

import pytest
from r11_1_fakes_c import jpeg_bytes

from jarvis.homebridge import face_engine
from jarvis.homebridge.face_engine import (
    MAX_PIXELS,
    MAX_SIDE,
    MODELS,
    RUNTIME_PACKAGES,
    EngineOff,
    OpenCvEngine,
    PictureRefused,
    reduction,
)
from jarvis.homebridge.face_types import DIM
from jarvis.homebridge.jpeg import jpeg_size


def test_the_size_is_read_from_the_header_without_decoding() -> None:
    assert jpeg_size(jpeg_bytes(640, 480)) == (640, 480)
    assert jpeg_size(jpeg_bytes(8, 8, sof=0xC2)) == (8, 8)  # progressive
    # a thumbnail inside the camera data is skipped: the real frame is the one that counts
    exif = b"\xff\xe1" + (2 + 30).to_bytes(2, "big") + b"Exif\x00\x00" + b"\xff\xc0" + bytes(22)
    assert jpeg_size(jpeg_bytes(300, 200, app=exif)) == (300, 200)


@pytest.mark.parametrize(
    "bad",
    [
        b"",
        b"GIF89a" + bytes(40),
        b"\x89PNG\r\n\x1a\n" + bytes(40),
        b"\xff\xd8\xff",
        jpeg_bytes()[:30],
        jpeg_bytes(8, 8, sof=0xC9),  # arithmetic coding
        jpeg_bytes(8, 8, sof=0xC3),  # lossless
        jpeg_bytes(0, 8),
        b"\xff\xd8\xff\xdb\xff\xff" + bytes(40),  # a segment longer than the file
        b"\xff\xd8\xff\xd9",  # ends before any frame
    ],
)
def test_anything_that_is_not_a_plain_jpeg_is_refused(bad: bytes) -> None:
    with pytest.raises(PictureRefused):
        jpeg_size(bad)


def test_a_picture_from_the_cloud_must_fit_the_caps_and_is_never_shrunk() -> None:
    assert (MAX_SIDE, MAX_PIXELS) == (2048, 4_200_000)
    assert reduction(1024, 768, own_file=False) == 1
    assert reduction(2048, 2048, own_file=False) == 1
    for w, h in ((2049, 100), (100, 2049), (4000, 3000)):
        with pytest.raises(PictureRefused) as err:
            reduction(w, h, own_file=False)
        assert err.value.code == "too_large"


def test_the_owners_own_big_photo_is_decoded_smaller_instead() -> None:
    assert reduction(2000, 1500, own_file=True) == 1
    assert reduction(4000, 3000, own_file=True) == 2
    assert reduction(8000, 6000, own_file=True) == 4
    assert reduction(12000, 9000, own_file=True) == 8
    for w, h in ((17000, 100), (16000, 12000)):  # over 16,384 a side, or over 150 megapixels
        with pytest.raises(PictureRefused):
            reduction(w, h, own_file=True)


def test_the_two_models_are_pinned_by_hash_size_licence_and_source() -> None:
    assert [m.name for m in MODELS] == [
        "face_detection_yunet_2026may.onnx",
        "face_recognition_sface_2021dec.onnx",
    ]
    assert [m.licence for m in MODELS] == ["MIT", "Apache-2.0"]
    for m in MODELS:
        assert len(m.sha256) == 64 and int(m.sha256, 16) >= 0 and m.size > 100_000
        assert m.source.startswith("https://media.githubusercontent.com/media/opencv/opencv_zoo/")
        assert face_engine.ZOO_COMMIT in m.source and m.source.endswith("/" + m.name)
    assert RUNTIME_PACKAGES == {"cv2": "opencv-python-headless", "numpy": "numpy"}


def test_no_models_means_plain_words_and_no_crash(tmp_path: Path) -> None:
    engine = OpenCvEngine(tmp_path)
    assert "model" in engine.status() and engine.status() != "ready"
    with pytest.raises(EngineOff):
        engine.faces(jpeg_bytes())


def test_a_model_file_that_is_not_the_pinned_one_is_never_loaded(tmp_path: Path) -> None:
    for m in MODELS:
        (tmp_path / m.name).write_bytes(b"not the reviewed model")
    engine = OpenCvEngine(tmp_path)
    assert "changed" in engine.status() or "model" in engine.status()
    with pytest.raises(EngineOff):
        engine.faces(jpeg_bytes())


def test_a_missing_library_is_said_plainly(tmp_path: Path) -> None:
    def no_library(name: str) -> Any:
        raise ImportError(name)

    engine = OpenCvEngine(tmp_path, load=no_library)
    assert "update" in engine.status().lower()
    with pytest.raises(EngineOff):
        engine.faces(jpeg_bytes())


# ---- with OpenCV: the decoder and the pipeline over a fake detector and recogniser --------------


def _engine_with_fakes(tmp_path: Path, rows: list[list[float]]) -> tuple[OpenCvEngine, Any, Any]:
    cv2 = pytest.importorskip("cv2")
    np = pytest.importorskip("numpy")

    class Detector:
        def __init__(self) -> None:
            self.sizes: list[tuple[int, int]] = []

        def setInputSize(self, size: tuple[int, int]) -> None:  # noqa: N802 - OpenCV's name
            self.sizes.append(size)

        def detect(self, img: Any) -> tuple[int, Any]:
            if len(self.sizes) > 1:  # the second, smaller pass finds nothing new here
                return 1, None
            return 1, np.array(rows, dtype=np.float32) if rows else None

    class Recogniser:
        def alignCrop(self, img: Any, row: Any) -> Any:  # noqa: N802 - OpenCV's name
            return np.zeros((112, 112, 3), dtype=np.uint8)

        def feature(self, aligned: Any) -> Any:
            return np.arange(1, DIM + 1, dtype=np.float32).reshape(1, DIM)

    engine = OpenCvEngine(tmp_path)
    det = Detector()
    engine.install(cv2, np, det, Recogniser())
    return engine, cv2, np


def _photo(cv2: Any, np: Any, width: int, height: int) -> bytes:
    img = np.full((height, width, 3), 90, dtype=np.uint8)
    cv2.circle(img, (width // 2, height // 2), min(width, height) // 4, (200, 180, 160), -1)
    ok, data = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 80])
    assert ok
    return bytes(data.tobytes())


def _row(x: float, y: float, w: float, h: float, score: float) -> list[float]:
    marks = [x + w * 0.3, y + h * 0.4, x + w * 0.7, y + h * 0.4, x + w * 0.5, y + h * 0.6]
    marks += [x + w * 0.35, y + h * 0.8, x + w * 0.65, y + h * 0.8]
    return [x, y, w, h, *marks, score]


def test_each_face_becomes_an_embedding_and_a_small_crop(tmp_path: Path) -> None:
    rows = [_row(100, 80, 120, 150, 0.93), _row(400, 100, 60, 70, 0.88)]
    engine, cv2, np = _engine_with_fakes(tmp_path, rows)
    assert engine.status() == "ready"
    faces = engine.faces(_photo(cv2, np, 640, 480))
    assert len(faces) == 2
    first = faces[0]
    assert len(first.vector) == DIM and all(isinstance(x, float) for x in first.vector)
    assert first.score == pytest.approx(0.93, abs=0.01) and first.size == 120
    assert first.crop.startswith(b"\xff\xd8\xff") and len(first.crop) < 64 * 1024
    crop = cv2.imdecode(np.frombuffer(first.crop, np.uint8), cv2.IMREAD_COLOR)
    assert max(crop.shape[:2]) <= face_engine.CROP_SIDE


def test_tiny_unsure_and_duplicate_faces_are_left_out(tmp_path: Path) -> None:
    rows = [
        _row(100, 80, 120, 150, 0.93),
        _row(104, 84, 118, 148, 0.90),  # the same face again (overlapping box)
        _row(300, 300, 20, 22, 0.95),  # too small to tell anyone by
        _row(450, 60, 90, 100, 0.55),  # the detector is not sure it is a face
    ]
    engine, cv2, np = _engine_with_fakes(tmp_path, rows)
    faces = engine.faces(_photo(cv2, np, 640, 480))
    assert [f.size for f in faces] == [120]


def test_at_most_twenty_faces_a_picture(tmp_path: Path) -> None:
    rows = [_row(10 + 62 * (i % 16), 10 + 70 * (i // 16), 50, 60, 0.9) for i in range(30)]
    engine, cv2, np = _engine_with_fakes(tmp_path, rows)
    assert len(engine.faces(_photo(cv2, np, 1024, 768))) == 20


def test_a_big_own_photo_is_read_smaller_and_a_cloud_one_of_that_size_refused(
    tmp_path: Path,
) -> None:
    engine, cv2, np = _engine_with_fakes(tmp_path, [])
    big = _photo(cv2, np, 4000, 3000)
    with pytest.raises(PictureRefused) as err:
        engine.faces(big)
    assert err.value.code == "too_large"
    assert engine.faces(big, own_file=True) == []
    assert max(engine.last_shape) <= MAX_SIDE  # decoded at half size, never at 12 megapixels


def test_bytes_that_only_look_like_a_jpeg_are_refused_not_crashed_on(tmp_path: Path) -> None:
    engine, _, _ = _engine_with_fakes(tmp_path, [])
    no_picture = jpeg_bytes(64, 64).split(b"\xff\xda")[0] + b"\xff\xd9"  # a header, no picture
    with pytest.raises(PictureRefused) as err:
        engine.faces(no_picture)
    assert err.value.code == "bad_jpeg"  # review C-sec H1: refused before the decoder runs
    with pytest.raises(PictureRefused) as err:
        # a whole header whose component names a quantisation table that was never defined
        engine.faces(jpeg_bytes(64, 64).replace(b"\x01\x11\x00\xff\xda", b"\x01\x11\x03\xff\xda"))
    assert err.value.code == "unreadable"
    with pytest.raises(PictureRefused):
        engine.faces(b"GIF89a" + bytes(100))


# ---- the real models, when they have been downloaded (not in the repository, not in CI) ---------

MODELS_DIR = os.environ.get("JARVIS_FACE_MODELS_DIR", "")


@pytest.mark.skipif(not MODELS_DIR, reason="set JARVIS_FACE_MODELS_DIR to run the real models")
def test_the_real_models_load_by_hash_and_find_a_drawn_face() -> None:
    cv2 = pytest.importorskip("cv2")
    np = pytest.importorskip("numpy")
    for m in MODELS:
        data = (Path(MODELS_DIR) / m.name).read_bytes()
        assert hashlib.sha256(data).hexdigest() == m.sha256 and len(data) == m.size
    engine = OpenCvEngine(Path(MODELS_DIR))
    assert engine.status() == "ready"
    img = np.full((480, 640, 3), 127, dtype=np.uint8)
    c, size = (
        (200, 240),
        240,
    )  # a drawn face (an oval, two eyes, a nose, a mouth, hair): nobody real
    cv2.ellipse(img, c, (size // 4, size // 3), 0, 0, 360, (150, 180, 220), -1)
    for dx in (-24, 24):
        cv2.ellipse(img, (c[0] + dx, c[1] - 24), (8, 5), 0, 0, 360, (255, 255, 255), -1)
        cv2.circle(img, (c[0] + dx, c[1] - 24), 3, (30, 30, 30), -1)
    cv2.line(img, (c[0], c[1] - 16), (c[0] - 4, c[1] + 17), (110, 140, 190), 2)
    cv2.ellipse(img, (c[0], c[1] + 40), (20, 6), 0, 0, 180, (60, 60, 160), 3)
    cv2.ellipse(img, (c[0], c[1] - 48), (60, 40), 0, 180, 360, (20, 20, 20), -1)
    ok, data = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 92])
    assert ok
    faces = engine.faces(bytes(data.tobytes()))
    assert len(faces) == 1 and len(faces[0].vector) == DIM
    assert faces[0].crop.startswith(b"\xff\xd8\xff") and faces[0].size >= 40
    assert engine.faces(_photo(cv2, np, 640, 480)) == []  # a plain circle is not a face
