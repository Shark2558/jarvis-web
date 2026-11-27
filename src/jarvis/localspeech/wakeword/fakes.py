# src/jarvis/localspeech/wakeword/fakes.py
"""Deterministic stand-ins for the wake word's tests and CI mock evals (plan 5: real models only on
the laptop), like `jarvis.localspeech.memory.MemoryKit`. No recording, no model file: synthetic
tones only.

- `tone_models()`: three `Runner`s shaped like the console's ONNX models. Loud audio makes today's
  "detector" fire; the embeddings carry loudness and pitch (zero crossings), so a verifier can
  learn a voice: the owner is `OWNER_HZ`, other speakers higher.
- `words()`, `ToneVoices`: speech as tone patterns, one per word, at a speaker's pitch.
- `session_clips()`: a voice session's clips (his "Hey Jarvis" and other prompts).
Needs NumPy (kit and tests only).
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence

import numpy as np

from jarvis.localspeech.protocol import PromptKind
from jarvis.localspeech.wakeword.formats import DIM, SAMPLE_RATE
from jarvis.localspeech.wakeword.port import VoiceInfo, WakeClip
from jarvis.localspeech.wakeword.streaming import F32, MEL_BINS, MEL_CONTEXT, FeatureModels

OWNER_HZ = 300.0
OTHER_HZ = (1000.0, 1100.0, 1200.0, 1300.0, 1400.0, 1500.0)
LOUD = 8000.0
SOFT = 2500.0
_CHUNK = 160
_HALF = DIM // 2
_GAIN = np.linspace(0.5, 1.5, _HALF, dtype=np.float32)


def tone(hz: float, seconds: float, amplitude: float = LOUD, *, seed: int = 0) -> bytes:
    """A sine with a little deterministic noise, as 16 kHz mono PCM16."""
    t = np.arange(int(SAMPLE_RATE * seconds)) / SAMPLE_RATE
    noise = np.random.default_rng(seed).normal(0, amplitude * 0.02, t.shape[0])
    wave = amplitude * np.sin(2 * np.pi * hz * t) + noise
    return np.clip(wave, -32768, 32767).astype("<i2").tobytes()


def silence(seconds: float) -> bytes:
    return b"\0\0" * int(SAMPLE_RATE * seconds)


def words(text: str, hz: float, *, seed: int = 0) -> bytes:
    """Speech in the fake world: each word a tone whose length, pitch step and gap come from the
    word (so "Hey Travis" never sounds like "Hey Jarvis"), at the speaker's pitch `hz`."""
    out = []
    for i, word in enumerate(text.lower().split()):
        d = hashlib.sha256(word.strip(".,!?").encode()).digest()[1:4]  # no near miss collides
        seconds, step, gap = 0.18 + 0.04 * (d[0] % 8), 1 + (d[1] % 6) / 10, 0.06 + 0.02 * (d[2] % 4)
        out.append(tone(hz * step, seconds, seed=seed + i) + silence(gap))
    return b"".join(out)


def bursts(hz: float, count: int, amplitude: float = SOFT, *, seed: int = 0) -> bytes:
    """Short syllable-like bursts: his other prompts."""
    return b"".join(tone(hz, 0.12, amplitude, seed=seed + i) + silence(0.1) for i in range(count))


def session_clips(
    wake: int = 14, speech: int = 12, *, held_every: int = 5, hz: float = OWNER_HZ
) -> tuple[WakeClip, ...]:
    """A voice session's clips: his "Hey Jarvis" (loud tones) and other prompts (soft bursts),
    every `held_every`-th held out."""
    clips = [
        WakeClip(
            prompt_id=f"wake_{i:02d}",
            kind=PromptKind.WAKE,
            pcm=words("Hey Jarvis", hz, seed=i),
            held_out=i % held_every == 0,
        )
        for i in range(wake)
    ]
    clips += [
        WakeClip(
            prompt_id=f"cmd_{i:02d}",
            kind=PromptKind.COMMAND,
            pcm=bursts(hz, 6, seed=100 + i),
            held_out=i % held_every == 0,
        )
        for i in range(speech)
    ]
    return tuple(clips)


def _mel(x: F32) -> F32:
    samples = np.asarray(x, dtype=np.float32).reshape(-1)
    n = max(0, (samples.shape[0] - MEL_CONTEXT) // _CHUNK)
    rows = np.zeros((n, MEL_BINS), dtype=np.float32)
    for j in range(n):
        chunk = samples[MEL_CONTEXT + j * _CHUNK : MEL_CONTEXT + (j + 1) * _CHUNK]
        rms = float(np.sqrt(np.mean(chunk.astype(np.float64) ** 2))) / LOUD
        zcr = float(np.mean(np.signbit(chunk[1:]) != np.signbit(chunk[:-1])))
        rows[j, : MEL_BINS // 2] = (rms - 2) * 10  # the stream applies /10 + 2
        rows[j, MEL_BINS // 2 :] = (zcr * 10 - 2) * 10
    return rows[None, None, :, :]


def _emb(x: F32) -> F32:
    batch = np.asarray(x, dtype=np.float32)[..., 0]  # [b, 76, 32]
    energy = batch[:, -8:, 0].mean(axis=1)
    pitch = batch[:, -8:, MEL_BINS // 2].mean(axis=1)
    out = np.concatenate([energy[:, None] * _GAIN, pitch[:, None] * _GAIN], axis=1)
    return out.astype(np.float32)[:, None, None, :]


def _wake(x: F32) -> F32:
    energy = float(np.asarray(x, dtype=np.float32)[0, -6:, 0].mean()) / float(_GAIN[0])
    return np.array([[1.0 / (1.0 + np.exp(-30.0 * (energy - 0.35)))]], dtype=np.float32)


def tone_models() -> FeatureModels:
    return FeatureModels(mel=_mel, emb=_emb, wake=_wake)


class ToneVoices:
    """`Voices` for tests: each voice a pitch; what it says lasts as long as the words."""

    def __init__(self, pitches: Sequence[float] = OTHER_HZ) -> None:
        self._pitch = {f"tone-{int(hz)}": hz for hz in pitches}
        self.said: list[str] = []  # voice names only

    def voices(self) -> tuple[VoiceInfo, ...]:
        return tuple(VoiceInfo(voice=v, licence="MIT") for v in sorted(self._pitch))

    def say(self, voice: str, text: str) -> bytes:
        self.said.append(voice)
        return words(text, self._pitch[voice], seed=len(self.said))


__all__ = [
    "LOUD",
    "OTHER_HZ",
    "OWNER_HZ",
    "SOFT",
    "ToneVoices",
    "bursts",
    "session_clips",
    "silence",
    "tone",
    "tone_models",
    "words",
]
