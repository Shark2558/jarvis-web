# src/jarvis/calls/speech/phoneline.py
"""The phone-line simulation for the language check (R18 B; plan 5.3, numpy only).

A mobile call carries narrowband speech: 300–3,400 Hz, sampled at 8 kHz, coded with G.711
(mu-law here, as on Indian networks' PCM legs). `phone_line` turns a clean 16 kHz clip into what
JARVIS would hear over such a call and back into JARVIS's 16 kHz format:

    16 kHz → band-pass 300–3,400 Hz → 8 kHz → G.711 mu-law encode → decode → 16 kHz

The band-pass is the difference of two windowed-sinc low-passes (linear phase, no delay), so the
output lines up sample for sample with the input and has its length. Deterministic: no noise is
added beyond the codec's own quantisation. The codec follows ITU-T G.711 (bias 0x84, clip 32,635,
eight segments, inverted code bits).
"""

from __future__ import annotations

import numpy as np
from numpy.typing import NDArray

from jarvis.calls.speech.audio import SAMPLE_RATE, fir, from_float, lowpass_taps, to_float

PHONE_RATE = 8_000
BAND_LOW_HZ = 300.0
BAND_HIGH_HZ = 3_400.0
RECON_HZ = 3_600.0  # the receiver's reconstruction filter at 16 kHz
BAND_TAPS = 401  # ±120 Hz transitions at 16 kHz
_BIAS = 0x84
_CLIP = 32_635
_FACTOR = SAMPLE_RATE // PHONE_RATE


def mulaw_encode(samples: NDArray[np.int16]) -> NDArray[np.uint8]:
    """G.711 mu-law codes of 16-bit samples."""
    x = samples.astype(np.int32)
    sign = np.where(x < 0, 0x80, 0)
    mag = np.minimum(np.abs(x), _CLIP) + _BIAS
    _, e = np.frexp(mag.astype(np.float64))  # mag = m · 2**e, m in [0.5, 1): e - 8 is the segment
    exponent = np.clip(e.astype(np.int32) - 8, 0, 7)
    mantissa = (mag >> (exponent + 3)) & 0x0F
    return np.asarray(~(sign | (exponent << 4) | mantissa) & 0xFF, dtype=np.uint8)


def mulaw_decode(codes: NDArray[np.uint8]) -> NDArray[np.int16]:
    """16-bit samples of G.711 mu-law codes."""
    c = ~codes.astype(np.int32) & 0xFF
    exponent = (c >> 4) & 0x07
    t = (((c & 0x0F) << 3) + _BIAS) << exponent
    return np.asarray(np.where(c & 0x80, _BIAS - t, t - _BIAS), dtype=np.int16)


def _band(rate: int) -> NDArray[np.float64]:
    high = lowpass_taps(BAND_HIGH_HZ, rate, BAND_TAPS)
    low = lowpass_taps(BAND_LOW_HZ, rate, BAND_TAPS)
    return np.asarray(high - low, dtype=np.float64)


def phone_line(pcm16k: bytes) -> bytes:
    """16 kHz mono PCM16 as heard after a narrowband G.711 call; same length and format."""
    x = to_float(pcm16k)
    if len(x) == 0:
        return b""
    narrow = fir(x, _band(SAMPLE_RATE))[::_FACTOR]  # band-limited below 4 kHz: no aliasing
    coded = np.frombuffer(from_float(narrow), dtype="<i2").astype(np.int16)
    heard = mulaw_decode(mulaw_encode(coded)).astype(np.float64) / 32768.0
    up = np.zeros(len(heard) * _FACTOR, dtype=np.float64)
    up[::_FACTOR] = heard * _FACTOR  # zero-stuffing loses 1/FACTOR of the level: put it back
    wide = fir(up, lowpass_taps(RECON_HZ, SAMPLE_RATE, BAND_TAPS))
    out = np.zeros(len(x), dtype=np.float64)
    n = min(len(x), len(wide))
    out[:n] = wide[:n]
    return from_float(out)


__all__ = [
    "BAND_HIGH_HZ",
    "BAND_LOW_HZ",
    "PHONE_RATE",
    "mulaw_decode",
    "mulaw_encode",
    "phone_line",
]
