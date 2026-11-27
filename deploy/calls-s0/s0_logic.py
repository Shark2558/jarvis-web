"""R18 S0 (docs/plans/r18-calls.md, section 10): the laptop test's pure helpers.

Nothing here touches Windows, a sound device or the network, so the repository's tests can run
it anywhere. `s0_check.py` (Windows only) records and plays the audio and calls these helpers to
judge it and to write the report the owner pastes back into the chat.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field

import numpy as np
from numpy.typing import NDArray

FloatArray = NDArray[np.float32]

FRAME_S = 0.02  # 20 ms analysis frames
FLOOR_DBFS = -100.0  # what digital silence reads as
ACTIVE_MARGIN_DB = 12.0  # a frame is "active" this far above the noise floor
MIN_ACTIVE_FRACTION = 0.15  # at least this share of frames must be active to count as heard
MIN_PEAK_DBFS = -45.0  # and the loudest frame must reach this level
HIGH_BAND_HZ = 4000.0  # a narrowband (8 kHz) call carries nothing above this
NARROWBAND_MAX_RATIO = 0.005  # high-band energy share at or below this: narrowband
WIDEBAND_MIN_RATIO = 0.01  # at or above this: wideband (an HD call)

CABLE_PLAYBACK = "CABLE Input"  # VB-CABLE's speaker side: JARVIS plays into it
CABLE_RECORDING = "CABLE Output"  # VB-CABLE's microphone side: Phone Link sends it into the call

# The standard key tones (low, high) in Hz.
DTMF_HZ: dict[str, tuple[int, int]] = {
    "1": (697, 1209),
    "2": (697, 1336),
    "3": (697, 1477),
    "4": (770, 1209),
    "5": (770, 1336),
    "6": (770, 1477),
    "7": (852, 1209),
    "8": (852, 1336),
    "9": (852, 1477),
    "*": (941, 1209),
    "0": (941, 1336),
    "#": (941, 1477),
}


@dataclass(frozen=True)
class Levels:
    """How a recording sounds, in numbers a person can read."""

    peak_dbfs: float
    noise_floor_dbfs: float
    active_fraction: float
    high_band_ratio: float

    @property
    def heard(self) -> bool:
        """True when the recording holds something like speech, not silence or hiss."""
        return self.peak_dbfs >= MIN_PEAK_DBFS and self.active_fraction >= MIN_ACTIVE_FRACTION

    @property
    def band(self) -> str:
        """The call's audio width, judged from its energy above 4 kHz."""
        if not self.heard:
            return "unknown (nothing heard)"
        if self.high_band_ratio <= NARROWBAND_MAX_RATIO:
            return "narrowband (8 kHz, a normal call)"
        if self.high_band_ratio >= WIDEBAND_MIN_RATIO:
            return "wideband (16 kHz, an HD call)"
        return "unclear"

    def line(self) -> str:
        return (
            f"peak {self.peak_dbfs:.1f} dBFS, noise floor {self.noise_floor_dbfs:.1f} dBFS, "
            f"speech in {self.active_fraction:.0%} of the time, {self.band}"
        )


def to_mono(samples: NDArray[np.floating] | NDArray[np.integer]) -> FloatArray:
    """Float samples in -1..1, one channel (the average of the channels)."""
    arr = np.asarray(samples)
    if np.issubdtype(arr.dtype, np.integer):
        scale = float(np.iinfo(arr.dtype).max)
        arr = arr.astype(np.float32) / scale
    arr = arr.astype(np.float32, copy=False)
    if arr.ndim == 2:
        arr = arr.mean(axis=1, dtype=np.float32)
    if arr.ndim != 1:
        raise ValueError(f"expected 1 or 2 dimensions, got {arr.ndim}")
    return arr


def frame_dbfs(mono: FloatArray, rate: int) -> FloatArray:
    """The level of each 20 ms frame in dBFS (full scale = 0)."""
    if rate <= 0:
        raise ValueError("rate must be positive")
    size = max(1, int(rate * FRAME_S))
    count = len(mono) // size
    if count == 0:
        return np.full(1, FLOOR_DBFS, dtype=np.float32)
    frames = mono[: count * size].reshape(count, size)
    rms = np.sqrt(np.mean(np.square(frames, dtype=np.float64), axis=1))
    with np.errstate(divide="ignore"):
        levels = 20.0 * np.log10(rms)
    return np.maximum(levels, FLOOR_DBFS).astype(np.float32)


def high_band_ratio(mono: FloatArray, rate: int, active: NDArray[np.bool_]) -> float:
    """The share of the active frames' energy above 4 kHz (0 when nothing is active)."""
    size = max(1, int(rate * FRAME_S))
    count = len(active)
    if count == 0 or not active.any() or rate / 2 <= HIGH_BAND_HZ:
        return 0.0
    frames = mono[: count * size].reshape(count, size)[active]
    spectrum = np.abs(np.fft.rfft(frames * np.hanning(size), axis=1)) ** 2
    freqs = np.fft.rfftfreq(size, d=1.0 / rate)
    speech = (freqs >= 300.0) & (freqs <= 8000.0)
    total = float(spectrum[:, speech].sum())
    if total <= 0.0:
        return 0.0
    high = float(spectrum[:, speech & (freqs > HIGH_BAND_HZ)].sum())
    return high / total


def analyse(samples: NDArray[np.floating] | NDArray[np.integer], rate: int) -> Levels:
    """Judge a recording: loudness, how much of it is speech-like, and its width."""
    mono = to_mono(samples)
    levels = frame_dbfs(mono, rate)
    floor = float(np.percentile(levels, 10))
    active = levels >= max(floor + ACTIVE_MARGIN_DB, MIN_PEAK_DBFS - ACTIVE_MARGIN_DB)
    return Levels(
        peak_dbfs=float(np.max(levels)),
        noise_floor_dbfs=floor,
        active_fraction=float(active.mean()),
        high_band_ratio=high_band_ratio(mono, rate, active) if len(mono) else 0.0,
    )


def dtmf_tone(
    digit: str, rate: int, *, tone_s: float = 0.25, gap_s: float = 0.15, amplitude: float = 0.4
) -> FloatArray:
    """One key tone ("press 1") followed by a short silence, ready to play."""
    if digit not in DTMF_HZ:
        raise ValueError(f"not a phone key: {digit!r}")
    if rate <= 0 or not 0.0 < amplitude <= 0.5:
        raise ValueError("rate must be positive and amplitude in (0, 0.5]")
    low, high = DTMF_HZ[digit]
    t = np.arange(int(rate * tone_s), dtype=np.float64) / rate
    tone = amplitude * (np.sin(2 * np.pi * low * t) + np.sin(2 * np.pi * high * t))
    ramp = min(len(tone) // 2, int(rate * 0.005))  # 5 ms fades: no clicks
    if ramp:
        fade = np.linspace(0.0, 1.0, ramp)
        tone[:ramp] *= fade
        tone[-ramp:] *= fade[::-1]
    gap = np.zeros(int(rate * gap_s))
    return np.concatenate([tone, gap]).astype(np.float32)


def find_device(names: Iterable[str], wanted: str) -> str | None:
    """The first device name containing `wanted`, ignoring case; None when there is none."""
    needle = wanted.casefold()
    return next((name for name in names if needle in name.casefold()), None)


@dataclass
class Report:
    """What the test found. It holds device names and results only: no phone numbers, no audio."""

    windows: str = ""
    python: str = ""
    speakers: list[str] = field(default_factory=list)
    microphones: list[str] = field(default_factory=list)
    default_speaker: str = ""
    default_microphone: str = ""
    cable_found: bool = False
    hands_free: list[str] = field(default_factory=list)
    test_a: Levels | None = None
    test_a_carrier: str = ""
    test_b: str = "not run"
    test_c: str = "not run"
    mic_restored: str = "not checked"
    notes: list[str] = field(default_factory=list)

    def verdict_a(self) -> str:
        if self.test_a is None:
            return "NOT RUN"
        return "PASS" if self.test_a.heard else "FAIL"

    def text(self, when: str) -> str:
        lines = [
            "JARVIS calls - laptop test (S0) report",
            f"When: {when}",
            f"Windows: {self.windows}",
            f"Python: {self.python}",
            f"VB-CABLE found: {'yes' if self.cable_found else 'NO'}",
            f"Default speaker: {self.default_speaker}",
            f"Default microphone: {self.default_microphone}",
            *_listed("Speakers", self.speakers),
            *_listed("Microphones", self.microphones),
            *_listed("Hands-free (phone) devices", self.hands_free),
            f"Test A - JARVIS hears the call: {self.verdict_a()}",
        ]
        if self.test_a is not None:
            lines.append(f"  {self.test_a.line()}")
        if self.test_a_carrier:
            lines.append(f"  The call played on: {self.test_a_carrier}")
        lines += [
            f"Test B - JARVIS speaks into the call: {self.test_b}",
            f"Test C - a phone menu reacts to key tones: {self.test_c}",
            f"Microphone switched back: {self.mic_restored}",
            *(f"Note: {note}" for note in self.notes),
        ]
        return "\n".join(lines)


def _listed(title: str, names: Sequence[str]) -> list[str]:
    if not names:
        return [f"{title}: none"]
    return [f"{title}:", *(f"  - {name}" for name in names)]
