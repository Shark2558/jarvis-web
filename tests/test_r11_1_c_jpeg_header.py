# tests/test_r11_1_c_jpeg_header.py -- review C-sec H1: the bridge's JPEG header reader must read a
# file exactly as the decoder (libjpeg) does, or a crafted file can show it one size and the
# decoder another. Before the frame header only the segments libjpeg itself steps over by their
# length are accepted (APPn, COM, DQT, DHT, DRI, DAC); a parameterless marker (TEM, RSTn), a second
# frame header, a second SOI and anything it can't parse are refused. Every picture here is made
# in the test (bytes, or OpenCV drawing a flat grey rectangle): never a photo.
from __future__ import annotations

import struct

import pytest

from jarvis.homebridge.jpeg import PictureRefused, jpeg_size


def seg(marker: int, payload: bytes) -> bytes:
    return bytes([0xFF, marker]) + struct.pack(">H", 2 + len(payload)) + payload


def sof(width: int, height: int, *, marker: int = 0xC0, comps: int = 1) -> bytes:
    body = struct.pack(">BHHB", 8, height, width, comps)
    body += b"".join(bytes([i + 1, 0x11, 0]) for i in range(comps))
    return seg(marker, body)


DQT = seg(0xDB, b"\x00" + bytes(64))
DHT = seg(0xC4, b"\x00" + bytes(16))
SOS = seg(0xDA, b"\x01\x01\x00\x00\x3f\x00") + b"\x12\x34\xff\xd9"


def jpeg(*parts: bytes) -> bytes:
    return b"\xff\xd8" + b"".join(parts)


def tem_trick(real: bytes, *, decoy: tuple[int, int] = (100, 100)) -> bytes:
    """The reviewer's differential.py, in bytes: TEM (FF01) is parameterless to libjpeg, but a
    reader that takes it as length-bearing jumps over the REAL frame header and finds a decoy one
    hidden inside a comment."""
    hidden = DQT + real
    com = seg(0xFE, sof(*decoy))
    # the "length" lands the careless reader on the decoy, four bytes into the comment
    return b"\xff\xd8\xff\x01" + struct.pack(">H", len(hidden) + 6) + hidden + com + DHT + SOS


def careless_size(data: bytes) -> tuple[int, int]:
    """The reader as it was before the review: every marker but SOS and EOI taken as one with a
    length (kept here only to prove the trick below is a real one)."""
    pos = 2
    while data[pos + 1] not in (0xD9, 0xDA):
        marker, (length,) = data[pos + 1], struct.unpack_from(">H", data, pos + 2)
        if marker in (0xC0, 0xC1, 0xC2):
            height, width = struct.unpack_from(">HH", data, pos + 5)
            return width, height
        pos += 2 + length
    raise AssertionError("no frame")


def test_the_reviewers_poc_is_refused_whole() -> None:
    # a header that says 100 x 100 to a careless reader while the frame libjpeg decodes is
    # 12,000 x 12,000 (144 megapixels): refused, whatever size it would have claimed
    poc = tem_trick(sof(12_000, 12_000, comps=3))
    assert careless_size(poc) == (100, 100)
    with pytest.raises(PictureRefused) as err:
        jpeg_size(poc)
    assert err.value.code == "bad_jpeg"


@pytest.mark.parametrize("marker", [0x01, *range(0xD0, 0xD8)])
def test_a_parameterless_marker_before_the_frame_is_refused(marker: int) -> None:
    with pytest.raises(PictureRefused):
        jpeg_size(jpeg(bytes([0xFF, marker]), DQT, sof(64, 48), DHT, SOS))


@pytest.mark.parametrize(
    "extra",
    [
        b"\xff\xd8",  # a second start of image
        seg(0xDC, b"\x00\x30"),  # DNL: libjpeg-turbo does not take it
        seg(0xF0, b"\x00\x00"),  # JPG0..JPG13: reserved
        seg(0xC8, b"\x00\x00"),  # JPG
        seg(0xDF, b"\x00\x00"),  # EXP
        seg(0xFD, b"\x00\x00"),
        seg(0x02, b"\x00\x00"),  # a reserved marker
        b"\x00\x00",  # bytes that are not a marker at all (libjpeg would skip them)
    ],
)
def test_anything_else_before_the_frame_is_refused(extra: bytes) -> None:
    with pytest.raises(PictureRefused):
        jpeg_size(jpeg(DQT, extra, sof(64, 48), DHT, SOS))


def test_a_second_frame_header_is_refused() -> None:
    with pytest.raises(PictureRefused) as err:
        jpeg_size(jpeg(DQT, sof(64, 48), DHT, sof(12_000, 12_000), SOS))
    assert err.value.code == "bad_jpeg"


@pytest.mark.parametrize(
    "bad",
    [
        jpeg(DQT, sof(64, 48), DHT),  # no scan: nothing libjpeg could decode
        jpeg(DQT, sof(64, 48), DHT, b"\xff\xd9"),  # ends before the scan
        jpeg(DQT, SOS),  # a scan before any frame
        jpeg(DQT, seg(0xC0, struct.pack(">BHHB", 8, 48, 64, 3) + b"\x01\x11\x00"), SOS),  # short
        jpeg(DQT, sof(64, 48, comps=5), SOS),  # more components than a JPEG has
        jpeg(DQT, seg(0xC0, struct.pack(">BHHB", 12, 48, 64, 1) + b"\x01\x11\x00"), SOS),
        jpeg(DQT, sof(0, 48), SOS),
        jpeg(DQT, sof(64, 0), SOS),
        jpeg(DQT, sof(64, 48, marker=0xC9), SOS),  # arithmetic coding
        jpeg(DQT, sof(64, 48, marker=0xC3), SOS),  # lossless
    ],
)
def test_a_frame_it_cannot_parse_completely_is_refused(bad: bytes) -> None:
    with pytest.raises(PictureRefused):
        jpeg_size(bad)


def test_every_segment_libjpeg_steps_over_by_length_is_accepted() -> None:
    before = (
        seg(0xE0, b"JFIF\x00" + bytes(9)),
        seg(0xE1, b"Exif\x00\x00" + sof(9_000, 9_000)),  # a thumbnail's frame inside: stepped over
        seg(0xEE, b"Adobe" + bytes(7)),
        seg(0xFE, b"made in a test"),
        DQT,
        DHT,
        seg(0xDD, b"\x00\x10"),  # DRI
        seg(0xCC, b"\x00\x10"),  # DAC
        b"\xff\xff",  # fill bytes before a marker are allowed
    )
    assert jpeg_size(jpeg(*before, sof(640, 480, comps=3), DHT, SOS)) == (640, 480)
    assert jpeg_size(jpeg(DQT, sof(8, 8, marker=0xC2), DHT, SOS)) == (8, 8)  # progressive
    assert jpeg_size(jpeg(DQT, sof(8, 8, marker=0xC1, comps=4), DHT, SOS)) == (8, 8)


def test_what_the_header_says_is_what_the_decoder_decodes() -> None:
    cv2 = pytest.importorskip("cv2")
    np = pytest.importorskip("numpy")
    img = np.full((48, 64, 3), 128, np.uint8)
    for progressive in (0, 1):
        ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_PROGRESSIVE, progressive])
        assert ok
        data = bytes(buf.tobytes())
        decoded = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
        assert jpeg_size(data) == (decoded.shape[1], decoded.shape[0]) == (64, 48)


def test_the_trick_really_fooled_a_careless_reader_and_now_does_not() -> None:
    """The same differential on a real (small) picture: libjpeg decodes the hidden 64 x 48
    frame, never the 100 x 100 decoy, and the bridge refuses the file before decoding."""
    cv2 = pytest.importorskip("cv2")
    np = pytest.importorskip("numpy")
    ok, buf = cv2.imencode(".jpg", np.full((48, 64, 3), 90, np.uint8))
    assert ok
    src = bytes(buf.tobytes())
    # split the encoder's own file into what comes before the scan and the rest
    pos, head, tables = 2, b"", b""
    while src[pos + 1] != 0xDA:
        (length,) = struct.unpack_from(">H", src, pos + 2)
        part = src[pos : pos + 2 + length]
        if src[pos + 1] == 0xC4:
            tables += part
        else:
            head += part
        pos += 2 + length
    crafted = (
        b"\xff\xd8\xff\x01"
        + struct.pack(">H", len(head) + 6)
        + head
        + seg(0xFE, sof(100, 100, comps=3))
        + tables
        + src[pos:]
    )
    decoded = cv2.imdecode(np.frombuffer(crafted, np.uint8), cv2.IMREAD_COLOR)
    assert decoded is not None and decoded.shape[:2] == (48, 64)  # what libjpeg really reads
    with pytest.raises(PictureRefused):
        jpeg_size(crafted)
