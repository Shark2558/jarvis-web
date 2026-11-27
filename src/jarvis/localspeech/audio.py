# src/jarvis/localspeech/audio.py
"""Audio helpers for the kit (R5.2 V1): every engine speaks PCM16 mono at its own rate and the API
speaks 16 kHz (R18's format), so voices are resampled here. NumPy (BSD-3-Clause, pinned in the
kit's requirements) is imported only when audio is actually resampled or converted.

`Mp3Encoder` is the seam for the console's voice (`TtsRequest.format == "mp3"`): the kit's own
encoder is `jarvis.localspeech.runtimes.mp3` (PyAV, already a faster-whisper dependency).
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING, Final, Protocol

from jarvis.localspeech.protocol import SAMPLE_BYTES, SAMPLE_RATE

if TYPE_CHECKING:  # pragma: no cover
    import numpy as np
    import numpy.typing as npt

TAPS_PER_SIDE: Final = 16  # the low-pass filter's half length, in output samples
INT16_MAX: Final = 32767


class Mp3Encoder(Protocol):
    def encode(self, pcm: bytes, sample_rate: int) -> bytes:
        """PCM16 mono at `sample_rate` -> MP3 bytes."""
        ...


def pcm16_to_float(pcm: bytes) -> npt.NDArray[np.float32]:
    import numpy as np

    if len(pcm) % SAMPLE_BYTES:
        raise ValueError("the audio is not 16-bit samples")
    return np.frombuffer(pcm, dtype="<i2").astype(np.float32) / 32768.0


def float_to_pcm16(samples: npt.ArrayLike) -> bytes:
    import numpy as np

    arr = np.asarray(samples, dtype=np.float32).reshape(-1)
    arr = np.nan_to_num(arr, nan=0.0, posinf=1.0, neginf=-1.0)
    clipped = np.clip(arr, -1.0, 1.0)
    return (clipped * INT16_MAX).astype("<i2").tobytes()


def resample_pcm16(pcm: bytes, src_rate: int, dst_rate: int = SAMPLE_RATE) -> bytes:
    """PCM16 mono from `src_rate` to `dst_rate`: a windowed-sinc low-pass when the rate drops,
    then linear interpolation. Plenty for speech; returns `pcm` itself when the rates match."""
    if src_rate <= 0 or dst_rate <= 0:
        raise ValueError("sample rates are positive")
    if src_rate == dst_rate or not pcm:
        return pcm
    import numpy as np

    x = pcm16_to_float(pcm).astype(np.float64)
    if dst_rate < src_rate:
        x = _lowpass(x, cutoff=0.5 * dst_rate / src_rate)
    n_out = max(1, int(round(len(x) * dst_rate / src_rate)))
    positions = np.arange(n_out, dtype=np.float64) * (src_rate / dst_rate)
    y = np.interp(positions, np.arange(len(x), dtype=np.float64), x)
    return float_to_pcm16(y)


def _lowpass(x: npt.NDArray[np.float64], *, cutoff: float) -> npt.NDArray[np.float64]:
    """A Hann-windowed sinc low-pass at `cutoff` (cycles per input sample, < 0.5)."""
    import numpy as np

    half = max(TAPS_PER_SIDE, int(math.ceil(TAPS_PER_SIDE / (2 * cutoff))))
    n = np.arange(-half, half + 1, dtype=np.float64)
    taps = 2 * cutoff * np.sinc(2 * cutoff * n) * np.hanning(len(n))
    taps /= taps.sum()
    out: npt.NDArray[np.float64] = np.convolve(x, taps, mode="same")
    return out


def silence(seconds: float, rate: int = SAMPLE_RATE) -> bytes:
    return b"\x00\x00" * max(0, int(seconds * rate))


def tone(seconds: float, hz: float = 440.0, rate: int = SAMPLE_RATE, level: float = 0.3) -> bytes:
    """A sine tone as PCM16 (the self-test's and the tests' synthetic audio)."""
    import numpy as np

    t = np.arange(int(seconds * rate), dtype=np.float64) / rate
    return float_to_pcm16(level * np.sin(2 * math.pi * hz * t))


__all__ = [
    "Mp3Encoder",
    "float_to_pcm16",
    "pcm16_to_float",
    "resample_pcm16",
    "silence",
    "tone",
]
