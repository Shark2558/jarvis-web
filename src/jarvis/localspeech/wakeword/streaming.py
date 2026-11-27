# src/jarvis/localspeech/wakeword/streaming.py
"""The console's "Hey Jarvis" pipeline in Python, for training and evals on the kit (R5.2 row 83).

A line-for-line port of static/console-wakeword.js `step()`, `seedHistory()` and `decide()`
(itself a port of openWakeWord 0.6.0's streaming features, Apache-2.0, Copyright 2022 David
Scripka): the verifier is trained on, and the evals score, exactly the embedding windows the
browser computes, including its mulberry32 seed noise. The three ONNX models are `Runner`s
(`runtime.open_console_models` on the kit; plain functions in tests). Needs NumPy (kit only;
never imported by the cloud: `jarvis.localspeech.wakeword.RUNTIME_MODULES`).
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray

from jarvis.localspeech.wakeword.evals import Decider
from jarvis.localspeech.wakeword.formats import (
    DIM,
    FRAME_SAMPLES,
    FRAMES,
    SAMPLE_RATE,
    THRESHOLD,
    WARMUP,
    VerifierFile,
    sigmoid,
)

F32 = NDArray[np.float32]
Runner = Callable[[F32], F32]  # one ONNX model: input tensor -> its first output
MEL_CONTEXT = 160 * 3  # samples of history each melspectrogram step re-reads
MEL_BINS = 32
MEL_WINDOW = 76  # melspectrogram frames per embedding
MEL_STRIDE = 8
INIT_NOISE_SEED = 0x4A415256  # console-wakeword.js INIT_NOISE_SEED
INIT_NOISE_SAMPLES = SAMPLE_RATE * 4
INIT_NOISE_LOW = -1000
INIT_NOISE_SPAN = 2000
_U32 = 0xFFFFFFFF


@dataclass(frozen=True)
class FeatureModels:
    mel: Runner  # [1, n] samples -> [.., frames, 32]
    emb: Runner  # [b, 76, 32, 1] -> [b, .., 96]
    wake: Runner  # [1, 16, 96] -> [1, 1]: today's model, or the owned one


def mulberry32(seed: int, n: int) -> NDArray[np.float64]:
    """console-wakeword.js `mulberry32(seed)`, n draws in [0, 1). Its state only adds a constant
    each draw, so the k-th state is `seed + k * 0x6d2b79f5` and the draws vectorise."""
    k = np.arange(1, n + 1, dtype=np.uint64)
    a = ((seed & _U32) + k * np.uint64(0x6D2B79F5)) & np.uint64(_U32)
    t = ((a ^ (a >> np.uint64(15))) * (a | np.uint64(1))) & np.uint64(_U32)
    u = ((t ^ (t >> np.uint64(7))) * (t | np.uint64(61))) & np.uint64(_U32)
    t = ((t + u) & np.uint64(_U32)) ^ t
    out: NDArray[np.float64] = ((t ^ (t >> np.uint64(14))) & np.uint64(_U32)).astype(
        np.float64
    ) / 4294967296.0
    return out


def _rows(spec: F32) -> F32:
    flat = np.asarray(spec, dtype=np.float32).reshape(-1, MEL_BINS)
    return (flat / np.float32(10) + np.float32(2)).astype(np.float32)


def seed_history(models: FeatureModels) -> F32:
    """The 16 embeddings of 4 s of seed noise every stream starts from (`seedHistory`)."""
    noise = (
        np.floor(mulberry32(INIT_NOISE_SEED, INIT_NOISE_SAMPLES) * INIT_NOISE_SPAN) + INIT_NOISE_LOW
    ).astype(np.float32)
    rows = _rows(models.mel(noise[None, :]))
    starts = list(range(0, rows.shape[0] - MEL_WINDOW + 1, MEL_STRIDE))
    batch = np.stack([rows[s : s + MEL_WINDOW] for s in starts])[..., None].astype(np.float32)
    emb = np.asarray(models.emb(batch), dtype=np.float32).reshape(-1, DIM)
    return emb[-FRAMES:].copy()


class Stream:
    """One listening stream: 1280-sample frames in, (score, window) out."""

    def __init__(self, models: FeatureModels, history: F32 | None = None) -> None:
        self.models = models
        self.history = seed_history(models) if history is None else history.astype(np.float32)
        self.raw = np.zeros(FRAME_SAMPLES + MEL_CONTEXT, dtype=np.float32)
        self.mel = np.ones((MEL_WINDOW, MEL_BINS), dtype=np.float32)
        self.features = self.history.copy()
        self.raw_length = 0
        self.predictions = 0

    def reset(self) -> None:
        """`resetPipeline()`: fresh buffers and `WARMUP` frames that score 0."""
        self.raw_length = 0
        self.mel = np.ones((MEL_WINDOW, MEL_BINS), dtype=np.float32)
        self.features = self.history.copy()
        self.predictions = 0

    def step(self, frame: NDArray[np.int16]) -> tuple[float, F32]:
        """One 80 ms frame -> today's score for it and the window the wake model read."""
        keep = min(self.raw_length, MEL_CONTEXT)
        samples = np.concatenate(
            [self.raw[self.raw_length - keep : self.raw_length], frame.astype(np.float32)]
        )
        self.raw[: samples.shape[0]] = samples
        self.raw_length = samples.shape[0]
        rows = _rows(self.models.mel(samples[None, :]))
        self.mel = np.concatenate([self.mel, rows])[-MEL_WINDOW:]
        emb = self.models.emb(self.mel[None, :, :, None].astype(np.float32))
        emb_rows = np.asarray(emb, dtype=np.float32).reshape(-1, DIM)
        self.features = np.concatenate([self.features, emb_rows])[-FRAMES:]
        window = self.features.copy()
        out = float(np.asarray(self.models.wake(window[None, :, :])).reshape(-1)[0])
        score = 0.0 if self.predictions < WARMUP or not np.isfinite(out) else out
        self.predictions += 1
        return score, window


def frames(pcm: bytes, offset: int = 0) -> Iterator[NDArray[np.int16]]:
    """Whole 1280-sample frames of 16 kHz PCM16, from sample `offset` (a partial tail is
    dropped, as the console keeps it for the next chunk)."""
    samples = np.frombuffer(pcm, dtype="<i2")[offset:]
    for at in range(0, samples.shape[0] - FRAME_SAMPLES + 1, FRAME_SAMPLES):
        yield samples[at : at + FRAME_SAMPLES]


def pad(pcm: bytes, seconds: float = 1.0) -> bytes:
    """Silence on both sides, as openWakeWord's `predict_clip` and the parity fixtures do."""
    silence = b"\0\0" * int(SAMPLE_RATE * seconds)
    return silence + pcm + silence


def scan(stream: Stream, pcm: bytes, offset: int = 0) -> list[tuple[float, F32]]:
    """Every frame's (score, window) of one clip, from a fresh stream (no wake decisions)."""
    stream.reset()
    return [stream.step(f) for f in frames(pcm, offset)]


def rescorer(verifier: VerifierFile) -> Callable[[float, F32], float]:
    """`VerifierFile.score` with NumPy's dot product (the evals read hours of audio)."""
    weights = np.asarray(verifier.weights, dtype=np.float64)

    def score(base: float, window: F32) -> float:
        if base < verifier.gate:
            return base
        z = verifier.bias + float(np.dot(weights, window.reshape(-1).astype(np.float64)))
        return sigmoid(z)

    return score


def listen(
    stream: Stream,
    pcm: bytes,
    *,
    verifier: VerifierFile | None = None,
    threshold: float = THRESHOLD,
) -> int:
    """How many times the console would wake on this audio: `pump()` + `decide()`, with the
    verifier after today's score and a reset after every wake."""
    stream.reset()
    decider = Decider(threshold=threshold)
    rescore = rescorer(verifier) if verifier is not None else None
    wakes = 0
    for frame in frames(pcm):
        base, window = stream.step(frame)
        score = rescore(base, window) if rescore is not None else base
        if decider.feed(score):
            wakes += 1
            stream.reset()
    return wakes


__all__ = [
    "FeatureModels",
    "Runner",
    "Stream",
    "frames",
    "listen",
    "mulberry32",
    "pad",
    "rescorer",
    "scan",
    "seed_history",
]
