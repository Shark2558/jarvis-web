# tests/test_voice_wav.py — slice 9 §2: transcribe accepts only RIFF/WAVE PCM 16-bit mono 16 kHz,
# 0.3–60 s; everything else is `bad_audio` before any cloud call.
from __future__ import annotations

import struct

import pytest
from voice_fakes import wav

from jarvis.voice.ports import BadAudio
from jarvis.voice.wav import MAX_SECONDS, MIN_SECONDS, SAMPLE_RATE, parse_wav

ONE_SECOND = SAMPLE_RATE * 2


def test_accepts_16k_mono_pcm16() -> None:
    a = parse_wav(wav(1.5))
    assert a.sample_rate == 16_000 and a.seconds == pytest.approx(1.5)
    assert len(a.pcm) == int(1.5 * ONE_SECOND)


def test_skips_unknown_chunks_such_as_list() -> None:
    extra = b"LIST" + struct.pack("<I", 5) + b"INFOx" + b"\x00"  # odd size: padded to even
    assert parse_wav(wav(0.5, extra_chunks=extra)).seconds == pytest.approx(0.5)


@pytest.mark.parametrize(
    ("blob", "why"),
    [
        (b"", "empty"),
        (b"ID3\x04\x00" + b"\x00" * 100, "mp3"),
        (b"OggS" + b"\x00" * 100, "ogg"),
        (b"RIFF\x10\x00\x00\x00AVI LIST", "not WAVE"),
        (wav(1, channels=2), "stereo"),
        (wav(1, rate=44_100), "44.1 kHz"),
        (wav(1, rate=48_000), "48 kHz"),
        (wav(1, bits=8), "8-bit"),
        (wav(1, fmt=3), "float"),
        (wav(1, fmt=0xFFFE), "extensible"),
        (wav(0.2), "too short"),
        (wav(data=b"\x00" * ((MAX_SECONDS + 1) * ONE_SECOND)), "too long"),
        (wav(data=b"\x00\x00\x00"), "odd data length"),
        (wav(1)[:-100], "truncated data"),
        (wav(1)[:30], "truncated header"),
    ],
)
def test_rejects_everything_else(blob: bytes, why: str) -> None:
    with pytest.raises(BadAudio):
        parse_wav(blob)


def test_rejects_a_file_without_a_data_chunk() -> None:
    blob = wav(1)
    no_data = blob[: blob.index(b"data")]
    no_data = b"RIFF" + struct.pack("<I", len(no_data) - 8) + no_data[8:]
    with pytest.raises(BadAudio):
        parse_wav(no_data)


def test_rejects_a_data_chunk_before_fmt() -> None:
    body = b"\x00" * ONE_SECOND
    data = b"data" + struct.pack("<I", len(body)) + body
    fmt = b"fmt " + struct.pack("<IHHIIHH", 16, 1, 1, 16_000, 32_000, 2, 16)
    payload = b"WAVE" + data + fmt
    with pytest.raises(BadAudio):
        parse_wav(b"RIFF" + struct.pack("<I", len(payload)) + payload)


def test_rejects_a_riff_size_beyond_the_file() -> None:
    blob = bytearray(wav(1))
    blob[4:8] = struct.pack("<I", len(blob) + 1000)
    with pytest.raises(BadAudio):
        parse_wav(bytes(blob))


def test_limits_are_the_plan_values() -> None:
    assert (MIN_SECONDS, MAX_SECONDS, SAMPLE_RATE) == (0.3, 60, 16_000)
    assert parse_wav(wav(data=b"\x00" * (MAX_SECONDS * ONE_SECOND))).seconds == MAX_SECONDS
    assert parse_wav(wav(data=b"\x00" * int(MIN_SECONDS * ONE_SECOND))).seconds == MIN_SECONDS
