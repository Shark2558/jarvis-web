# tests/test_calls_speech_audio.py — R18 B: PCM16 16 kHz mono helpers (WAV in and out, any rate
# and width to 16 kHz mono) and the phone-line simulation (8 kHz narrowband, G.711 mu-law).
from __future__ import annotations

import struct

import numpy as np
import pytest

from jarvis.calls.speech.audio import (
    FRAME_BYTES,
    SAMPLE_RATE,
    AudioFormatError,
    from_float,
    pcm_from_wav,
    pcm_seconds,
    resample,
    to_float,
    wav_from_pcm,
)
from jarvis.calls.speech.phoneline import (
    PHONE_RATE,
    mulaw_decode,
    mulaw_encode,
    phone_line,
)


def tone(freq: float, seconds: float = 1.0, rate: int = SAMPLE_RATE, amp: float = 0.5) -> bytes:
    t = np.arange(int(seconds * rate)) / rate
    return from_float(amp * np.sin(2 * np.pi * freq * t))


def level_db(pcm: bytes) -> float:
    x = to_float(pcm)[1600:-1600]  # skip the filters' edges
    return float(20 * np.log10(np.sqrt(np.mean(x**2)) + 1e-12))


def wav_bytes(
    samples: bytes, *, rate: int, channels: int = 1, bits: int = 16, fmt: int = 1
) -> bytes:
    block = channels * bits // 8
    fields = struct.pack("<IHHIIHH", 16, fmt, channels, rate, rate * block, block, bits)
    fmt_chunk = b"fmt " + fields
    data = b"data" + struct.pack("<I", len(samples)) + samples
    body = b"WAVE" + fmt_chunk + b"LIST" + struct.pack("<I", 4) + b"INFO" + data
    return b"RIFF" + struct.pack("<I", len(body)) + body


# ---- the format ------------------------------------------------------------------------------


def test_the_format_is_16khz_mono_pcm16_in_20ms_frames() -> None:
    assert SAMPLE_RATE == 16_000
    assert FRAME_BYTES == 640
    assert pcm_seconds(b"\x00" * 32_000) == 1.0


def test_float_round_trip_clips_and_keeps_little_endian() -> None:
    pcm = from_float(np.array([0.0, 1.5, -1.5, 0.25]))
    assert struct.unpack("<4h", pcm) == (0, 32767, -32768, 8192)
    back = to_float(pcm)
    assert back[0] == 0.0 and back[3] == pytest.approx(0.25, abs=1e-4)


def test_odd_length_pcm_is_refused() -> None:
    with pytest.raises(AudioFormatError):
        to_float(b"\x00\x01\x02")


# ---- WAV ---------------------------------------------------------------------------------------


def test_wav_round_trip_at_16khz_is_byte_exact() -> None:
    pcm = tone(440, 0.5)
    assert pcm_from_wav(wav_from_pcm(pcm)) == pcm


def test_wav_header_is_the_canonical_44_bytes() -> None:
    blob = wav_from_pcm(b"\x01\x00" * 10)
    assert blob[:4] == b"RIFF" and blob[8:16] == b"WAVEfmt "
    assert len(blob) == 44 + 20
    assert struct.unpack_from("<HHIIHH", blob, 20) == (1, 1, 16_000, 32_000, 2, 16)


def test_a_22050hz_stereo_wav_becomes_16khz_mono() -> None:
    left = to_float(tone(500, 1.0, rate=22_050))
    stereo = np.stack([left, left], axis=1).reshape(-1)
    blob = wav_bytes(from_float(stereo), rate=22_050, channels=2)
    pcm = pcm_from_wav(blob)
    assert pcm_seconds(pcm) == pytest.approx(1.0, abs=0.01)
    assert level_db(pcm) == pytest.approx(level_db(tone(500)), abs=1.0)


def test_a_float32_wav_is_read() -> None:
    x = (0.5 * np.sin(2 * np.pi * 300 * np.arange(16_000) / 16_000)).astype("<f4")
    pcm = pcm_from_wav(wav_bytes(x.tobytes(), rate=16_000, bits=32, fmt=3))
    assert len(pcm) == 32_000
    assert level_db(pcm) == pytest.approx(level_db(tone(300)), abs=0.5)


@pytest.mark.parametrize(
    "blob",
    [
        b"",
        b"ID3\x04" + b"\x00" * 60,  # an MP3
        b"RIFF\xff\xff\x00\x00WAVE",  # a size past the end
        wav_bytes(b"\x00" * 8, rate=16_000, bits=8),  # 8-bit
        wav_bytes(b"\x00" * 8, rate=16_000, fmt=0x55),  # MP3 inside WAV
        wav_bytes(b"\x00" * 8, rate=0),  # no rate
    ],
)
def test_unreadable_wavs_are_refused(blob: bytes) -> None:
    with pytest.raises(AudioFormatError):
        pcm_from_wav(blob)


def test_a_wav_with_a_streamed_data_size_is_read_to_its_end() -> None:
    """Some engines write 0xFFFFFFFF (or 0) as the data size of a streamed WAV."""
    pcm = tone(440, 0.1)
    blob = bytearray(wav_from_pcm(pcm))
    struct.pack_into("<I", blob, 40, 0xFFFFFFFF)
    assert pcm_from_wav(bytes(blob)) == pcm


# ---- resampling ------------------------------------------------------------------------------


def test_resample_keeps_the_duration_and_the_level() -> None:
    x = to_float(tone(1_000, 1.0, rate=24_000))
    y = resample(x, 24_000, 16_000)
    assert len(y) == 16_000
    assert float(np.sqrt(np.mean(y[800:-800] ** 2))) == pytest.approx(0.5 / np.sqrt(2), rel=0.03)


def test_resample_to_the_same_rate_is_the_input() -> None:
    x = to_float(tone(440, 0.1))
    assert np.array_equal(resample(x, 16_000, 16_000), x)


def test_resample_removes_what_the_lower_rate_cannot_hold() -> None:
    """A 9.5 kHz tone is above 16 kHz audio's 8 kHz limit: it must not fold back in."""
    x = to_float(tone(9_500, 1.0, rate=22_050))
    y = resample(x, 22_050, 16_000)
    assert level_db(from_float(y)) < level_db(tone(9_500, rate=22_050)) - 20


# ---- G.711 mu-law ----------------------------------------------------------------------------


def test_mulaw_known_codes() -> None:
    assert mulaw_encode(np.array([0], dtype=np.int16)).tobytes() == b"\xff"
    codes = np.array([0xFF, 0x7F, 0x80, 0x00], dtype=np.uint8)
    assert mulaw_decode(codes).tolist() == [0, 0, 32124, -32124]


def test_mulaw_round_trip_is_within_its_step_size() -> None:
    x = np.arange(-32768, 32768, 7, dtype=np.int32).astype(np.int16)
    y = mulaw_decode(mulaw_encode(x)).astype(np.int32)
    err = np.abs(y - x.astype(np.int32))
    # the step doubles every segment: at most half a step (+ the clip at 32635)
    assert np.all(err <= np.maximum(8, np.abs(x.astype(np.int32)) // 16) + 140)
    assert np.all(np.sign(y[np.abs(x) > 64]) == np.sign(x[np.abs(x) > 64]))


def test_every_code_decodes_and_encodes_back_to_itself() -> None:
    codes = np.arange(256, dtype=np.uint8)
    again = mulaw_encode(mulaw_decode(codes))
    # all but 0x7F, "minus zero", which decodes to 0 and so comes back as 0xFF
    assert [int(c) for c in codes[again != codes]] == [0x7F]


# ---- the phone line --------------------------------------------------------------------------


def test_phone_line_keeps_the_length_and_the_format() -> None:
    pcm = tone(1_000, 1.0)
    out = phone_line(pcm)
    assert len(out) == len(pcm)
    assert PHONE_RATE == 8_000


def test_phone_line_passes_speech_frequencies() -> None:
    for freq in (500, 1_000, 2_500):
        assert level_db(phone_line(tone(freq))) == pytest.approx(level_db(tone(freq)), abs=2.0)


def test_phone_line_cuts_what_a_phone_cannot_carry() -> None:
    assert level_db(phone_line(tone(6_000))) < level_db(tone(6_000)) - 25
    assert level_db(phone_line(tone(80))) < level_db(tone(80)) - 10


def test_phone_line_adds_codec_noise_but_keeps_the_signal() -> None:
    pcm = tone(1_000, 1.0, amp=0.3)
    out = to_float(phone_line(pcm))[1600:-1600]
    ref = to_float(pcm)[1600:-1600]
    assert not np.array_equal(out, ref)
    assert float(np.corrcoef(out, ref)[0, 1]) > 0.98


def test_phone_line_is_deterministic_and_handles_tiny_input() -> None:
    pcm = tone(700, 0.3)
    assert phone_line(pcm) == phone_line(pcm)
    assert phone_line(b"") == b""
    assert len(phone_line(b"\x10\x00" * 3)) == 6
