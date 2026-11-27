# src/jarvis/calldesk/vad.py
"""The voice detector (plan section 4 step 4): audio goes to the cloud only while the other person
speaks, which is what keeps speech-to-text inside its free allowance.

No model: each 20 ms frame's level (dBFS) and zero-crossing rate. A frame is speech-like when it is
loud enough (an absolute minimum, and a margin above the line's noise floor) and its crossings sit
in speech's band (hum has almost none, hiss far more). Speech starts after `onset_frames`
speech-like frames in a row (a longer `barge_in_onset_frames` while JARVIS is talking, so a cough
on the line doesn't cut JARVIS off) and ends after `hangover_frames` quiet frames, so a word's tail
and short pauses are kept. The frames just before the start (the pre-roll) go with it, so the first
syllable isn't lost.

The noise floor follows the line: down at once to a quieter frame, up slowly (about 1.5 dB a
second) otherwise, so a steady noise stops counting as speech within seconds. Standard library
only (an `array` of 320 samples, 50 times a second).
"""

from __future__ import annotations

import math
import sys
from array import array
from collections import deque
from dataclasses import dataclass
from itertools import pairwise

from jarvis.calldesk.audio import FRAME_BYTES

FLOOR_DBFS = -100.0  # digital silence
_FULL_SCALE_SQ = 32768.0 * 32768.0


@dataclass(frozen=True)
class VadSettings:
    min_level_dbfs: float = -50.0  # quieter than this is never speech
    margin_db: float = 9.0  # this far above the noise floor
    zcr_min: float = 0.01  # crossings per sample: below is hum
    zcr_max: float = 0.40  # above is hiss
    onset_frames: int = 3  # 60 ms of speech starts a turn
    barge_in_onset_frames: int = 8  # 160 ms while JARVIS speaks
    hangover_frames: int = 20  # 400 ms of quiet ends it
    preroll_frames: int = 10  # 200 ms before the start go with it
    floor_start_dbfs: float = -70.0
    floor_rise_db: float = 0.03  # per frame (1.5 dB a second)

    def __post_init__(self) -> None:
        counts = (
            self.onset_frames,
            self.barge_in_onset_frames,
            self.hangover_frames,
            self.preroll_frames,
        )
        if min(counts) < 1:
            raise ValueError("frame counts must be at least 1")
        if not 0.0 <= self.zcr_min < self.zcr_max <= 1.0:
            raise ValueError("zero-crossing band must be 0 <= min < max <= 1")
        if self.margin_db <= 0 or self.floor_rise_db <= 0:
            raise ValueError("margin and floor rise must be positive")


DEFAULTS = VadSettings()


@dataclass(frozen=True)
class FrameStats:
    level_dbfs: float
    zcr: float


@dataclass(frozen=True)
class Step:
    """What one frame did: the frames to send now (empty while nobody speaks), and whether a turn
    started or stopped on this frame."""

    frames: tuple[bytes, ...] = ()
    started: bool = False
    stopped: bool = False


def frame_stats(frame: bytes) -> FrameStats:
    samples = array("h")
    samples.frombytes(frame)
    if sys.byteorder == "big":
        samples.byteswap()
    n = len(samples)
    if n == 0:
        return FrameStats(FLOOR_DBFS, 0.0)
    energy = sum(s * s for s in samples) / n
    level = 10.0 * math.log10(energy / _FULL_SCALE_SQ) if energy > 0 else FLOOR_DBFS
    crossings = sum(1 for a, b in pairwise(samples) if (a < 0) != (b < 0))
    return FrameStats(max(level, FLOOR_DBFS), crossings / (n - 1) if n > 1 else 0.0)


class VoiceDetector:
    """One per call. `push` takes every 20 ms frame of the loopback recording."""

    def __init__(self, settings: VadSettings = DEFAULTS) -> None:
        self._s = settings
        self.reset()

    def reset(self) -> None:
        self._floor = self._s.floor_start_dbfs
        self._run = 0
        self._quiet_left = 0
        self.speaking = False
        self._preroll: deque[bytes] = deque(maxlen=self._s.preroll_frames)

    @property
    def floor_dbfs(self) -> float:
        return self._floor

    def _speechlike(self, stats: FrameStats) -> bool:
        s = self._s
        loud = stats.level_dbfs >= max(s.min_level_dbfs, self._floor + s.margin_db)
        return loud and s.zcr_min <= stats.zcr <= s.zcr_max

    def _follow_floor(self, level: float) -> None:
        if level < self._floor:
            self._floor = max(level, FLOOR_DBFS)
        else:
            self._floor = min(self._floor + self._s.floor_rise_db, level)

    def push(self, frame: bytes, *, jarvis_speaking: bool = False) -> Step:
        if len(frame) != FRAME_BYTES:
            raise ValueError("a frame is 640 bytes (20 ms of 16 kHz PCM16)")
        stats = frame_stats(frame)
        voiced = self._speechlike(stats)
        self._follow_floor(stats.level_dbfs)
        if self.speaking:
            return self._while_speaking(frame, voiced)
        self._preroll.append(frame)
        self._run = self._run + 1 if voiced else 0
        onset = self._s.barge_in_onset_frames if jarvis_speaking else self._s.onset_frames
        if self._run < onset:
            return Step()
        self.speaking = True
        self._quiet_left = self._s.hangover_frames
        frames = tuple(self._preroll)
        self._preroll.clear()
        return Step(frames=frames, started=True)

    def _while_speaking(self, frame: bytes, voiced: bool) -> Step:
        if voiced:
            self._quiet_left = self._s.hangover_frames
            return Step(frames=(frame,))
        self._quiet_left -= 1
        if self._quiet_left > 0:
            return Step(frames=(frame,))
        self.speaking = False
        self._run = 0
        return Step(stopped=True)


__all__ = ["DEFAULTS", "FLOOR_DBFS", "FrameStats", "Step", "VadSettings", "VoiceDetector"]
