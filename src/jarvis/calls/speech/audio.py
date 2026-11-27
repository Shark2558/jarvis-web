# src/jarvis/calls/speech/audio.py
"""Call audio helpers (R18 B; Layers 2 and 8): JARVIS's one call format and the conversions to it.

The format everywhere in a call (BUILD-BRIEF, contracts): 16 kHz, mono, signed 16-bit
little-endian PCM, in 20 ms frames of 640 bytes. Every hearing adapter takes it and every voice
adapter returns it, whatever its vendor speaks: `pcm_from_wav` reads a vendor's or a test set's
WAV (PCM 16/24/32-bit or float, any channel count and rate, streamed sizes) and returns 16 kHz
mono PCM16; `wav_from_pcm` wraps PCM in the canonical 44-byte header a vendor expects.

Resampling is a windowed-sinc low-pass (Blackman, numpy only) and linear interpolation: plenty
for speech, which is all this carries. Nothing here logs, stores or sends audio.
"""

from __future__ import annotations

import struct

import numpy as np
from numpy.typing import NDArray

SAMPLE_RATE = 16_000
SAMPLE_BYTES = 2
FRAME_MS = 20
FRAME_BYTES = SAMPLE_RATE * SAMPLE_BYTES * FRAME_MS // 1000  # 640
MAX_WAV_BYTES = 64 * 1024 * 1024  # a test clip is ~1 MB; a vendor answer far less
MAX_CHUNKS = 64
_RATES = (4_000, 192_000)
_CHANNELS = (1, 8)
_PCM, _FLOAT, _EXTENSIBLE = 1, 3, 0xFFFE
_STREAMED = (0, 0xFFFFFFFF)  # data sizes an engine writes when it streams the WAV
LOWPASS_TAPS = 129
_FULL_SCALE = 32768.0

Floats = NDArray[np.float64]


class AudioFormatError(ValueError):
    """Audio that is not, and cannot be turned into, 16 kHz mono PCM16 (plain words only)."""


def pcm_seconds(pcm: bytes, rate: int = SAMPLE_RATE) -> float:
    return len(pcm) / (SAMPLE_BYTES * rate)


def to_float(pcm: bytes) -> Floats:
    """PCM16 LE → floats in [-1, 1)."""
    if len(pcm) % SAMPLE_BYTES:
        raise AudioFormatError("PCM16 audio has an even number of bytes.")
    return np.frombuffer(pcm, dtype="<i2").astype(np.float64) / _FULL_SCALE


def from_float(x: NDArray[np.floating] | Floats) -> bytes:
    """Floats → PCM16 LE, rounded and clipped to the 16-bit range."""
    scaled = np.clip(np.rint(np.asarray(x, dtype=np.float64) * _FULL_SCALE), -32768, 32767)
    return scaled.astype("<i2").tobytes()


# ---- filters and resampling ----------------------------------------------------------------


def lowpass_taps(cutoff_hz: float, rate: int, taps: int = LOWPASS_TAPS) -> Floats:
    """A linear-phase low-pass FIR (windowed sinc, Blackman), unity gain at 0 Hz."""
    fc = cutoff_hz / rate
    n = np.arange(taps, dtype=np.float64) - (taps - 1) / 2
    h = 2 * fc * np.sinc(2 * fc * n) * np.blackman(taps)
    return np.asarray(h / h.sum(), dtype=np.float64)


def fir(x: Floats, h: Floats) -> Floats:
    """`x` through `h`, centred (zero delay for a symmetric `h`), the length of `x`."""
    if len(x) == 0:
        return x
    full = np.convolve(x, h)
    start = (len(h) - 1) // 2
    return np.asarray(full[start : start + len(x)], dtype=np.float64)


def resample(x: Floats, src: int, dst: int) -> Floats:
    """`x` at `src` Hz → at `dst` Hz, band-limited to the lower rate's Nyquist (with 10 % room)."""
    if src == dst or len(x) == 0:
        return x
    if src <= 0 or dst <= 0:
        raise AudioFormatError("A sample rate must be positive.")
    if dst < src:
        x = fir(x, lowpass_taps(0.45 * dst, src))
    n_out = max(1, round(len(x) * dst / src))
    t = np.arange(n_out, dtype=np.float64) * (src / dst)
    y = np.interp(t, np.arange(len(x), dtype=np.float64), x)
    if dst > src:
        y = fir(y, lowpass_taps(0.45 * src, dst))
    return np.asarray(y, dtype=np.float64)


# ---- WAV ---------------------------------------------------------------------------------------


def wav_from_pcm(pcm: bytes, rate: int = SAMPLE_RATE) -> bytes:
    """PCM16 mono in the canonical 44-byte RIFF/WAVE header."""
    if len(pcm) % SAMPLE_BYTES:
        raise AudioFormatError("PCM16 audio has an even number of bytes.")
    fmt = struct.pack("<HHIIHH", _PCM, 1, rate, rate * SAMPLE_BYTES, SAMPLE_BYTES, 16)
    body = b"WAVE" + b"fmt " + struct.pack("<I", len(fmt)) + fmt
    body += b"data" + struct.pack("<I", len(pcm)) + pcm
    return b"RIFF" + struct.pack("<I", len(body)) + body


def _fmt(body: bytes) -> tuple[int, int, int, int]:
    """(format, channels, rate, bits) of a `fmt ` chunk; the extensible form's sub-format."""
    if len(body) < 16:
        raise AudioFormatError("The recording's format block is cut short.")
    fmt, channels, rate, _byte_rate, _align, bits = struct.unpack_from("<HHIIHH", body)
    if fmt == _EXTENSIBLE:
        if len(body) < 26:
            raise AudioFormatError("The recording's format block is cut short.")
        (fmt,) = struct.unpack_from("<H", body, 24)  # the sub-format GUID's first two bytes
    return fmt, channels, rate, bits


def _samples(data: bytes, fmt: int, bits: int, channels: int) -> Floats:
    if fmt == _PCM and bits == 16:
        x = np.frombuffer(data[: len(data) // 2 * 2], dtype="<i2").astype(np.float64) / 32768.0
    elif fmt == _PCM and bits == 24:
        raw = np.frombuffer(data[: len(data) // 3 * 3], dtype=np.uint8).reshape(-1, 3)
        ints = raw[:, 0].astype(np.int32) | raw[:, 1].astype(np.int32) << 8
        ints |= raw[:, 2].astype(np.int32) << 16
        x = np.where(ints >= 1 << 23, ints - (1 << 24), ints).astype(np.float64) / float(1 << 23)
    elif fmt == _PCM and bits == 32:
        x = np.frombuffer(data[: len(data) // 4 * 4], dtype="<i4").astype(np.float64) / 2.0**31
    elif fmt == _FLOAT and bits in (32, 64):
        dtype = "<f4" if bits == 32 else "<f8"
        size = bits // 8
        x = np.frombuffer(data[: len(data) // size * size], dtype=dtype).astype(np.float64)
        x = np.nan_to_num(x, nan=0.0, posinf=1.0, neginf=-1.0)
    else:
        raise AudioFormatError("Only PCM (16, 24 or 32-bit) or float WAV recordings are read.")
    whole = len(x) // channels * channels
    return np.asarray(x[:whole].reshape(-1, channels).mean(axis=1), dtype=np.float64)


def _chunks(blob: bytes) -> tuple[tuple[int, int, int, int] | None, bytes | None]:
    end = len(blob)
    pos, fmt, data = 12, None, None
    for _ in range(MAX_CHUNKS):
        if pos + 8 > end:
            break
        cid = blob[pos : pos + 4]
        (size,) = struct.unpack_from("<I", blob, pos + 4)
        start = pos + 8
        if cid == b"data":
            stop = end if size in _STREAMED or start + size > end else start + size
            data = blob[start:stop]
            break  # the samples come last in every WAV an engine writes
        if start + size > end:
            raise AudioFormatError("The recording is cut short.")
        if cid == b"fmt ":
            fmt = _fmt(blob[start : start + size])
        pos = start + size + (size & 1)
    return fmt, data


def pcm_from_wav(blob: bytes) -> bytes:
    """A WAV recording → 16 kHz mono PCM16 (byte-exact when it already is)."""
    if len(blob) > MAX_WAV_BYTES:
        raise AudioFormatError("The recording is too large.")
    if len(blob) < 12 or blob[:4] != b"RIFF" or blob[8:12] != b"WAVE":
        raise AudioFormatError("Not a WAV recording.")
    fmt, data = _chunks(blob)
    if fmt is None or data is None:
        raise AudioFormatError("Not a WAV recording.")
    kind, channels, rate, bits = fmt
    if not _RATES[0] <= rate <= _RATES[1] or not _CHANNELS[0] <= channels <= _CHANNELS[1]:
        raise AudioFormatError("The recording's rate or channel count is not usable.")
    if kind == _PCM and bits == 16 and channels == 1 and rate == SAMPLE_RATE:
        return data[: len(data) // 2 * 2]
    x = _samples(data, kind, bits, channels)
    return from_float(resample(x, rate, SAMPLE_RATE))


__all__ = [
    "FRAME_BYTES",
    "FRAME_MS",
    "MAX_WAV_BYTES",
    "SAMPLE_BYTES",
    "SAMPLE_RATE",
    "AudioFormatError",
    "Floats",
    "fir",
    "from_float",
    "lowpass_taps",
    "pcm_from_wav",
    "pcm_seconds",
    "resample",
    "to_float",
    "wav_from_pcm",
]
