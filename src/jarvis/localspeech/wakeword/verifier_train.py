# src/jarvis/localspeech/wakeword/verifier_train.py
"""Stage 1 (R5.2 row 83, D5): his personal "Hey Jarvis" verifier, trained on the kit.

openWakeWord's custom-verifier method (openwakeword 0.6.0 `custom_verifier_model.py`, Apache-2.0,
Copyright 2022 David Scripka), reimplemented in NumPy so the kit needs no scikit-learn:

- positives: the windows of his "Hey Jarvis" clips where today's model scores at least 0.5, each
  clip read `RUNS` times from a random start within the first frame (`N=5`);
- negatives: every window of his other prompts (`threshold=0.0, N=1`), plus, beyond upstream,
  other speakers' "Hey Jarvis" (the kit's permissively licensed synthetic voices) wherever the
  verifier would be asked (today's score at least `VERIFIER_GATE`);
- `StandardScaler` + `LogisticRegression(C=0.001)`: the same objective, solved by Newton's method,
  the scaler then folded into the weights (`VerifierFile`).

Held-out clips are never trained on; they, and voices kept apart, give the evals. Needs NumPy.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

import numpy as np
from numpy.typing import NDArray

from jarvis.localspeech.protocol import OWNER_LICENCE, ArtifactInfo, WakeArtifact
from jarvis.localspeech.wakeword.evals import WakeEval, verifier_passes
from jarvis.localspeech.wakeword.formats import (
    FEATURES,
    THRESHOLD,
    VERIFIER_GATE,
    VerifierFile,
    compact_evals,
    sha256_hex,
)
from jarvis.localspeech.wakeword.port import (
    MIN_WAKE_CLIPS,
    Progress,
    Voices,
    WakeClip,
    WakeJob,
    WakewordFailed,
)
from jarvis.localspeech.wakeword.streaming import F32, Stream, listen, pad, scan

F64 = NDArray[np.float64]
C = 0.001  # openWakeWord's LogisticRegression(C=0.001)
RUNS = 5  # its N=5 for the positive clips
NEWTON_STEPS = 50
GRAD_TOL = 1e-7
NEGATIVES_MAX = 8_000  # windows kept (the solve is d^2 n)
HELD_MIN = 3  # held-out "Hey Jarvis" clips, else every HELD_EVERY-th one is held out
HELD_EVERY = 5
OTHER_PHRASES = ("Hey Jarvis", "Hey, Jarvis.", "Hey Jarvis!", "Hey Jarvis, are you there?")
NOT_HEARD = (
    "Today's detector did not hear Hey Jarvis in your recordings, so the personal check has "
    "nothing to learn from. Your own model (stage 2) learns your way of saying it."
)


@dataclass(frozen=True)
class Trained:
    data: bytes
    info: ArtifactInfo
    manifest: str = ""


@dataclass(frozen=True)
class Split:
    train: tuple[WakeClip, ...]
    held: tuple[WakeClip, ...]


def split_wake(job: WakeJob) -> Split:
    """His "Hey Jarvis" clips: V3's held-out ones, or every 5th when it marked too few."""
    train, held = job.wake(held_out=False), job.wake(held_out=True)
    if len(held) < HELD_MIN:
        ordered = sorted(train, key=lambda c: c.prompt_id)
        extra = tuple(c for i, c in enumerate(ordered) if i % HELD_EVERY == HELD_EVERY - 1)
        held += extra
        train = tuple(c for c in ordered if c not in extra)
    if len(train) < MIN_WAKE_CLIPS:
        raise WakewordFailed(f"Training needs at least {MIN_WAKE_CLIPS} Hey Jarvis recordings.")
    return Split(train=train, held=held)


def positive_windows(stream: Stream, pcm: bytes, rng: np.random.Generator) -> list[F32]:
    found: list[F32] = []
    padded = pad(pcm)
    for _ in range(RUNS):
        offset = int(rng.integers(0, 1280))
        found += [w for s, w in scan(stream, padded, offset) if s >= THRESHOLD]
    return found


def gated_windows(stream: Stream, pcm: bytes, gate: float = 0.0, *, padded: bool) -> list[F32]:
    """Windows where today's score is at least `gate` (0: every window, as upstream)."""
    return [w for s, w in scan(stream, pad(pcm) if padded else pcm) if s >= gate]


def standardise(x: F64) -> tuple[F64, F64]:
    """StandardScaler: the mean and the population deviation (0 -> 1)."""
    scale = x.std(axis=0)
    return x.mean(axis=0), np.where(scale > 0, scale, 1.0)


def _objective(a: F64, y: F64, theta: F64, c: float) -> float:
    z = a @ theta
    return float(c * np.sum(np.logaddexp(0.0, z) - y * z) + 0.5 * theta[:-1] @ theta[:-1])


def fit_logistic(x: F64, y: F64, c: float = C) -> tuple[F64, float]:
    """sklearn's L2 logistic regression objective, `C * sum(log loss) + |w|^2 / 2` (the intercept
    not penalised), on standardised features; returns the folded weights and bias."""
    mean, scale = standardise(x)
    a = np.hstack([(x - mean) / scale, np.ones((x.shape[0], 1))])
    theta = np.zeros(a.shape[1])
    ridge = np.ones(a.shape[1])
    ridge[-1] = 1e-9
    for _ in range(NEWTON_STEPS):
        p = 1.0 / (1.0 + np.exp(-(a @ theta)))
        grad = c * a.T @ (p - y) + np.append(theta[:-1], 0.0)
        if float(np.max(np.abs(grad))) < GRAD_TOL:
            break
        weighted = a * np.sqrt(c * p * (1 - p))[:, None]
        step = np.linalg.solve(weighted.T @ weighted + np.diag(ridge), grad)
        theta = _backtrack(a, y, theta, step, grad, c)
    w, b = theta[:-1] / scale, float(theta[-1] - np.sum(theta[:-1] * mean / scale))
    return w, b


def _backtrack(a: F64, y: F64, theta: F64, step: F64, grad: F64, c: float) -> F64:
    base, t = _objective(a, y, theta, c), 1.0
    while t > 1e-6:
        moved = theta - t * step
        if _objective(a, y, moved, c) <= base - 1e-4 * t * float(grad @ step):
            return moved
        t /= 2
    return theta - t * step


def other_clips(voices: Voices | None) -> tuple[list[bytes], list[bytes], list[str]]:
    """Other speakers' "Hey Jarvis": (to train on, to test with, notes). Every third voice is
    kept apart for the test; a single voice gives the test its last phrase only."""
    if voices is None or not voices.voices():
        return [], [], ["no synthetic voices: other speakers were not measured"]
    names = sorted(v.voice for v in voices.voices())
    if len(names) == 1:
        said = [voices.say(names[0], p) for p in OTHER_PHRASES]
        return said[:-1], said[-1:], ["one synthetic voice: other speakers measured on it"]
    test = set(names[2::3]) or {names[-1]}
    train = [voices.say(n, p) for n in names if n not in test for p in OTHER_PHRASES]
    held = [voices.say(n, p) for n in sorted(test) for p in OTHER_PHRASES]
    return train, held, []


def evaluate(
    stream: Stream,
    verifier: VerifierFile | None,
    held: Sequence[WakeClip],
    others: Sequence[bytes],
    negatives: Sequence[bytes] = (),
) -> WakeEval:
    misses = sum(listen(stream, pad(c.pcm), verifier=verifier) == 0 for c in held)
    accepted = sum(listen(stream, pad(pcm), verifier=verifier) > 0 for pcm in others)
    wakes = sum(listen(stream, pad(pcm), verifier=verifier) for pcm in negatives)
    seconds = sum(len(pcm) / 32_000 for pcm in negatives)
    return WakeEval(
        clips=len(held),
        misses=misses,
        others=len(others),
        others_accepted=accepted,
        false_wakes=wakes,
        negative_seconds=seconds,
    )


def _examples(
    stream: Stream, split: Split, job: WakeJob, others: Sequence[bytes], seed: int
) -> tuple[F64, F64]:
    rng = np.random.default_rng(seed)
    pos = [w for c in split.train for w in positive_windows(stream, c.pcm, rng)]
    if not pos:
        raise WakewordFailed(NOT_HEARD)
    neg = [
        w for c in job.speech(held_out=False) for w in gated_windows(stream, c.pcm, padded=False)
    ]
    neg += [w for pcm in others for w in gated_windows(stream, pcm, VERIFIER_GATE, padded=True)]
    if not neg:
        raise WakewordFailed("Training needs some of your other recordings too.")
    if len(neg) > NEGATIVES_MAX:
        neg = [neg[int(i)] for i in sorted(rng.choice(len(neg), NEGATIVES_MAX, replace=False))]
    x = np.stack([w.reshape(FEATURES) for w in pos + neg]).astype(np.float64)
    y = np.concatenate([np.ones(len(pos)), np.zeros(len(neg))])
    return x, y


def train_verifier(
    job: WakeJob,
    stream: Stream,
    embedding_sha256: str,
    voices: Voices | None,
    progress: Progress,
    *,
    now: datetime,
    seed: int = 0,
) -> Trained:
    """The whole stage 1 run: windows, the fit, the file, the evals."""
    split = split_wake(job)
    progress(0.05, "Making other speakers' Hey Jarvis with the laptop's voices.")
    train_others, test_others, notes = other_clips(voices)
    progress(0.2, "Reading your recordings.")
    x, y = _examples(stream, split, job, train_others, seed)
    progress(0.6, "Learning your voice's Hey Jarvis.")
    w, b = fit_logistic(x, y)
    draft = VerifierFile(
        embedding_sha256=embedding_sha256,
        weights=tuple(float(v) for v in w),
        bias=b,
        trained_at=now,
        clips=len(split.train),
    )
    progress(0.8, "Checking it on recordings it never saw.")
    speech = [c.pcm for c in job.speech(held_out=True)]
    before = evaluate(stream, None, split.held, test_others, speech)
    after = evaluate(stream, draft, split.held, test_others, speech)
    evals = compact_evals(before.as_evals("today_", counts=False) | after.as_evals())
    final = draft.model_copy(update={"evals": evals})
    data = final.to_bytes()
    info = ArtifactInfo(
        artifact=WakeArtifact.VERIFIER,
        sha256=sha256_hex(data),
        size=len(data),
        trained_at=now,
        licence=OWNER_LICENCE,
        evals=evals,
        beats_current=verifier_passes(after) and after.false_wakes <= before.false_wakes,
    )
    progress(1.0, "Done." if not notes else f"Done ({notes[0]}).")
    return Trained(data=data, info=info)


__all__ = [
    "C",
    "RUNS",
    "Split",
    "Trained",
    "evaluate",
    "fit_logistic",
    "gated_windows",
    "other_clips",
    "positive_windows",
    "split_wake",
    "standardise",
    "train_verifier",
]
