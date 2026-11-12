# tests/test_r11_1_c_decoder.py -- review C-sec H2 and C-code H3: one bad picture can neither take
# the bridge down nor stop the folder. The JPEG decoder runs in a fresh child process that caps
# its own address space (RLIMIT_AS) and CPU time, with a wall-clock kill in the parent; the
# owner's own files are capped at 50 megapixels; whatever OpenCV raises while finding a face is a
# refused picture, never a crash. Every picture here is drawn by OpenCV in the test or written as
# bytes: never a photo of anyone.
from __future__ import annotations

import struct
import time
from pathlib import Path
from typing import Any

import pytest
from r11_1_fakes_c import jpeg_bytes

from jarvis.homebridge import decoder
from jarvis.homebridge.face_engine import OWN_MAX_PIXELS, OpenCvEngine, reduction
from jarvis.homebridge.jpeg import PictureRefused

cv2 = pytest.importorskip("cv2")
np = pytest.importorskip("numpy")


def drawn(width: int, height: int, *, progressive: int = 0) -> bytes:
    img = np.full((height, width, 3), 110, np.uint8)
    cv2.rectangle(img, (width // 4, height // 4), (width // 2, height // 2), (200, 60, 40), -1)
    params = [cv2.IMWRITE_JPEG_QUALITY, 80, cv2.IMWRITE_JPEG_PROGRESSIVE, progressive]
    ok, buf = cv2.imencode(".jpg", img, params)
    assert ok
    return bytes(buf.tobytes())


def progressive_bomb(width: int, height: int) -> bytes:
    """The reviewer's mkbomb.py without the 432 MB encode: a progressive, 4:4:4, three-component
    header of the given size and a first scan of almost nothing. libjpeg allocates the whole
    picture's coefficients for a progressive file before it reads the scan (width x height x 3 x
    2 bytes), which is what exhausted the bridge's memory."""

    def seg(marker: int, payload: bytes) -> bytes:
        return bytes([0xFF, marker]) + struct.pack(">H", 2 + len(payload)) + payload

    dqt = seg(0xDB, b"\x00" + bytes([1] * 64))
    frame = seg(
        0xC2, struct.pack(">BHHB", 8, height, width, 3) + b"\x01\x11\x00\x02\x11\x00\x03\x11\x00"
    )
    dht = seg(0xC4, b"\x00" + bytes([0, 1] + [0] * 14) + b"\x00")
    scan = seg(0xDA, b"\x03\x01\x00\x02\x00\x03\x00\x00\x00\x00")  # DC first scan, all three
    return b"\xff\xd8" + dqt + frame + dht + scan + bytes(64) + b"\xff\xd9"


def test_a_normal_picture_is_decoded_in_the_child_at_the_size_asked() -> None:
    data = drawn(640, 480)
    img = decoder.decode_isolated(data, cv2.IMREAD_COLOR, max_side=2048, np=np)
    assert img.shape == (480, 640, 3) and img.dtype == np.uint8
    half = decoder.decode_isolated(data, cv2.IMREAD_REDUCED_COLOR_2, max_side=2048, np=np)
    assert half.shape == (240, 320, 3)
    assert int(img[200, 250, 0]) > 150  # the drawn rectangle came through (BGR: blue first)


def test_a_progressive_memory_bomb_is_refused_and_the_caller_lives_on() -> None:
    # 9,000 x 9,000 progressive 4:4:4 needs ~486 MB of coefficients: over the child's ceiling
    bomb = progressive_bomb(9_000, 9_000)
    assert len(bomb) < 2_000
    started = time.monotonic()
    with pytest.raises(PictureRefused) as err:
        decoder.decode_isolated(bomb, cv2.IMREAD_REDUCED_COLOR_8, max_side=2048, np=np)
    assert err.value.code == "unreadable"
    assert time.monotonic() - started < decoder.DECODE_TIMEOUT_S
    # the same kind of file at a size the ceiling allows is decoded: it is the ceiling that said no
    small = decoder.decode_isolated(
        progressive_bomb(2_000, 2_000), cv2.IMREAD_REDUCED_COLOR_8, max_side=2048, np=np
    )
    assert small.shape == (250, 250, 3)
    # and the process that asked is fine: the next picture is read as usual
    assert decoder.decode_isolated(drawn(64, 48), cv2.IMREAD_COLOR, max_side=2048, np=np).shape == (
        48,
        64,
        3,
    )


def test_a_decode_that_takes_too_long_is_killed() -> None:
    started = time.monotonic()
    with pytest.raises(PictureRefused):
        decoder.decode_isolated(
            drawn(64, 48), cv2.IMREAD_COLOR, max_side=2048, np=np, timeout_s=0.01
        )
    assert time.monotonic() - started < 5


def test_what_the_child_says_is_checked_before_it_is_trusted() -> None:
    assert decoder.parse_child(b"NO", 0, max_side=2048, np=np) is None
    assert decoder.parse_child(b"", 0, max_side=2048, np=np) is None
    assert decoder.parse_child(
        b"OK" + struct.pack(">II", 2, 2) + bytes(12), 0, max_side=8, np=np
    ).shape == (2, 2, 3)
    for out, code in (
        (b"OK" + struct.pack(">II", 2, 2) + bytes(11), 0),  # short
        (b"OK" + struct.pack(">II", 2, 2) + bytes(13), 0),  # long
        (b"OK" + struct.pack(">II", 9, 2) + bytes(54), 0),  # bigger than asked
        (b"OK" + struct.pack(">II", 0, 2), 0),
        (b"OK" + struct.pack(">II", 2, 2) + bytes(12), -9),  # killed
        (b"XX" + bytes(20), 0),
    ):
        assert decoder.parse_child(out, code, max_side=8, np=np) is None


def test_the_child_inherits_nothing_from_the_bridge() -> None:
    env = decoder.child_env()
    assert set(env) <= {
        "SYSTEMROOT",
        "OPENBLAS_NUM_THREADS",
        "OMP_NUM_THREADS",
        "OPENCV_IO_MAX_IMAGE_PIXELS",
    }
    assert env["OPENCV_IO_MAX_IMAGE_PIXELS"] == str(OWN_MAX_PIXELS)
    assert "-I" in decoder.command(1, 2048, 1, 1)


def test_the_owners_own_files_are_capped_at_fifty_megapixels() -> None:
    assert OWN_MAX_PIXELS == 50_000_000
    assert reduction(8_000, 6_000, own_file=True) == 4  # 48 MP: a big phone photo
    for w, h in ((12_000, 9_000), (12_000, 12_000), (16_384, 9_155)):
        with pytest.raises(PictureRefused) as err:
            reduction(w, h, own_file=True)
        assert err.value.code == "too_large"


# ---- the engine: OpenCV's errors after decoding are refusals ------------------------------------


class _Det:
    def __init__(self, rows: Any, boom: str = "") -> None:
        self.rows, self.boom = rows, boom

    def setInputSize(self, size: tuple[int, int]) -> None:  # noqa: N802 - OpenCV's name
        return None

    def detect(self, img: Any) -> tuple[int, Any]:
        if self.boom == "detect":
            raise cv2.error("detector exploded on a picture")
        return 1, self.rows


class _Rec:
    def __init__(self, boom: str = "") -> None:
        self.boom = boom

    def alignCrop(self, img: Any, row: Any) -> Any:  # noqa: N802 - OpenCV's name
        if self.boom == "align":
            raise cv2.error("alignCrop exploded")
        return np.zeros((112, 112, 3), np.uint8)

    def feature(self, aligned: Any) -> Any:
        if self.boom == "feature":
            raise cv2.error("feature exploded")
        if self.boom == "nan":
            return np.full((1, 128), np.nan, np.float32)
        return np.arange(1, 129, dtype=np.float32).reshape(1, 128)


ROW = [[100, 80, 120, 150, 130, 140, 190, 140, 160, 170, 140, 200, 180, 200, 0.95]]


@pytest.mark.parametrize("boom", ["detect", "align", "feature"])
def test_an_opencv_error_while_looking_is_a_refused_picture(tmp_path: Path, boom: str) -> None:
    engine = OpenCvEngine(tmp_path)
    rows = np.array(ROW, np.float32)
    engine.install(cv2, np, _Det(rows, boom), _Rec(boom))
    with pytest.raises(PictureRefused) as err:
        engine.faces(drawn(640, 480))
    assert err.value.code == "unreadable"


def test_a_picture_that_is_not_a_jpeg_inside_is_refused_by_the_child(tmp_path: Path) -> None:
    engine = OpenCvEngine(tmp_path)
    engine.install(cv2, np, _Det(None), _Rec())
    broken = jpeg_bytes(64, 64).replace(b"\x01\x11\x00\xff\xda", b"\x01\x11\x03\xff\xda")
    with pytest.raises(PictureRefused):
        engine.faces(broken)
