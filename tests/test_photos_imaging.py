# tests/test_photos_imaging.py -- R4 D-C1: a dependency-free JPEG sanitiser. Every APPn (EXIF/GPS,
# XMP, ICC, ...) and COM segment is removed in the cloud; only the structural segments stay.
from __future__ import annotations

import struct

import pytest

from jarvis.photos.imaging import MAX_IMAGE_SIDE, sanitise_jpeg
from jarvis.photos.picker import BAD_PICTURE, PickerError

SOI, EOI = b"\xff\xd8", b"\xff\xd9"
GPS = b"GPS-LAT-12.97-LON-77.59"


def seg(marker: int, payload: bytes) -> bytes:
    return bytes([0xFF, marker]) + struct.pack(">H", len(payload) + 2) + payload


def sof(w: int, h: int, marker: int = 0xC0) -> bytes:
    return seg(marker, struct.pack(">BHHB", 8, h, w, 1) + b"\x01\x11\x00")


SOS = seg(0xDA, b"\x01\x01\x00\x00\x3f\x00")
SCAN = b"\x12\x34\xff\x00\x56\xff\xd0\x78"  # stuffed 0xFF00 and a restart marker


def jpeg(*parts: bytes, w: int = 64, h: int = 48, tail: bytes = EOI) -> bytes:
    return SOI + b"".join(parts) + seg(0xDB, b"\x00" + bytes(64)) + sof(w, h) + SOS + SCAN + tail


def test_exif_with_gps_is_removed_and_structure_is_kept() -> None:
    exif = seg(0xE1, b"Exif\x00\x00" + GPS)
    src = jpeg(exif, seg(0xFE, b"a comment"), seg(0xE2, b"ICC_PROFILE"))
    out = sanitise_jpeg(src)
    assert GPS not in out and b"Exif" not in out and b"comment" not in out
    assert out.startswith(SOI) and out.endswith(EOI)
    assert sof(64, 48) in out and SCAN in out  # frame header and entropy data untouched


def test_every_app_segment_including_jfif_is_dropped() -> None:
    src = jpeg(*(seg(m, b"APP%d" % m) for m in range(0xE0, 0xF0)))
    out = sanitise_jpeg(src)
    assert not any(bytes([0xFF, m]) in out.replace(b"\xff\x00", b"") for m in range(0xE0, 0xF0))


def test_clean_jpeg_passes_through_unchanged() -> None:
    src = jpeg()
    assert sanitise_jpeg(src) == src


def test_progressive_with_two_scans_is_kept() -> None:
    src = SOI + seg(0xDB, b"\x00" + bytes(64)) + sof(10, 10, 0xC2) + SOS + SCAN + SOS + SCAN + EOI
    assert sanitise_jpeg(src) == src


def test_bytes_after_eoi_are_dropped() -> None:
    assert sanitise_jpeg(jpeg(tail=EOI + b"HIDDEN")) == jpeg()


def test_oversized_dimensions_are_rejected() -> None:
    with pytest.raises(PickerError) as e:
        sanitise_jpeg(jpeg(w=MAX_IMAGE_SIDE + 1, h=10))
    assert str(e.value) == BAD_PICTURE
    with pytest.raises(PickerError):
        sanitise_jpeg(jpeg(w=10, h=3000))


def test_exactly_the_limit_is_accepted() -> None:
    assert sanitise_jpeg(jpeg(w=MAX_IMAGE_SIDE, h=MAX_IMAGE_SIDE))


@pytest.mark.parametrize(
    "bad",
    [
        b"",
        b"\x89PNG\r\n\x1a\n" + bytes(100),
        b"<html>",
        SOI,  # nothing else
        SOI + EOI,  # no frame, no scan
        SOI + sof(8, 8) + EOI,  # no scan
        SOI + SOS + SCAN + EOI,  # scan before frame
        SOI + sof(8, 8) + SOS + SCAN,  # no EOI: truncated
        SOI + b"\xff\xe1\x00\x40short",  # segment longer than the data
        SOI + b"\xff\xe1\x00\x01",  # impossible length
        SOI + b"not a marker",
        SOI + sof(8, 8) + sof(8, 8) + SOS + SCAN + EOI,  # two frames
        SOI + sof(8, 8, 0xC3) + SOS + SCAN + EOI,  # lossless
        SOI + sof(8, 8, 0xC9) + SOS + SCAN + EOI,  # arithmetic
        SOI + sof(0, 8) + SOS + SCAN + EOI,  # zero width
        SOI + seg(0xF5, b"x") + sof(8, 8) + SOS + SCAN + EOI,  # reserved marker
        SOI + struct.pack(">BB", 0xFF, 0xC0) + b"\x00\x05\x08\x00",  # truncated SOF
    ],
)
def test_malformed_or_unsupported_input_is_rejected(bad: bytes) -> None:
    with pytest.raises(PickerError) as e:
        sanitise_jpeg(bad)
    assert str(e.value) == BAD_PICTURE
