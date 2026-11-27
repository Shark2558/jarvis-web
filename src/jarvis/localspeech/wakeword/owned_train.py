# src/jarvis/localspeech/wakeword/owned_train.py
"""Stage 2 (R5.2 row 83, D5): a "Hey Jarvis" model trained by and owned by the owner, on the kit,
when he chooses (2-3 hours unattended; most of it is speech synthesis and reading audio).

Like openWakeWord's own training (Apache-2.0 code; not its CC BY-NC-SA data) it learns a small
dense network on the frozen embedding windows: positives are his "Hey Jarvis" clips (and noisy
copies) and the kit's permissively licensed voices saying it; negatives are his other prompts,
near misses, and synthetic "TV" (`synth`). The network is written as ONNX in the console's
format (`onnx_write`), checked against the kit's own ONNX runtime when given `check`, and
compared with today's model on his held-out clips and on `WAKE_BARS.tv_audio_hours` of
synthetic TV from voices it never trained on: `beats_current` only when it passes every bar and
is no worse (`evals.beats`). Needs NumPy (kit only).
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, replace
from datetime import datetime

import numpy as np
from numpy.typing import NDArray

from jarvis.localspeech.protocol import OWNER_LICENCE, ArtifactInfo, WakeArtifact
from jarvis.localspeech.wakeword import synth
from jarvis.localspeech.wakeword.evals import WAKE_BARS, WakeEval, beats
from jarvis.localspeech.wakeword.formats import (
    FEATURES,
    FRAME_SAMPLES,
    DataSource,
    ModelCard,
    compact_evals,
    sha256_hex,
)
from jarvis.localspeech.wakeword.mlp import Mlp, Recipe
from jarvis.localspeech.wakeword.onnx_write import mlp_onnx
from jarvis.localspeech.wakeword.port import Progress, Voices, WakeJob, WakewordFailed, split_wake
from jarvis.localspeech.wakeword.streaming import F32, Runner, Stream, listen, pad, scan
from jarvis.localspeech.wakeword.verifier_train import Trained

POS_SPAN = 4  # windows after the phrase's last loud frame that count as "Hey Jarvis"
VOICED = 0.3  # a frame is loud at this share of the clip's 95th-percentile level
CHECK_TOLERANCE = 1e-4
NO_VOICES = "Your own model needs the laptop's voices (Kokoro or Piper) installed in the kit."


@dataclass(frozen=True)
class Voicing:
    train: tuple[str, ...]
    test: tuple[str, ...]
    sources: tuple[DataSource, ...]


def voicing(voices: Voices | None) -> Voicing:
    """The kit's voices, every third kept apart for the false-wake eval (at least one each)."""
    infos = sorted(voices.voices(), key=lambda v: v.voice) if voices is not None else []
    if len(infos) < 2:
        raise WakewordFailed(NO_VOICES)
    test = tuple(v.voice for v in infos[2::3]) or (infos[-1].voice,)
    train = tuple(v.voice for v in infos if v.voice not in test)
    sources = tuple(
        DataSource(name=f"voice {v.voice}", licence=v.licence, detail="synthetic speech")
        for v in infos
    )
    return Voicing(train=train, test=test, sources=sources)


def phrase_end(pcm: bytes) -> int | None:
    """The last loud 80 ms frame of a clip (where "Hey Jarvis" ends), or None if it is quiet."""
    x = synth.as_float(pcm)
    n = x.shape[0] // FRAME_SAMPLES
    if n == 0:
        return None
    rms = np.sqrt(np.mean(x[: n * FRAME_SAMPLES].reshape(n, FRAME_SAMPLES) ** 2, axis=1))
    level = float(np.percentile(rms, 95))
    loud = np.nonzero(rms >= max(VOICED * level, 1.0))[0]
    return int(loud[-1]) if loud.size and level > 0 else None


def positive_windows(stream: Stream, pcm: bytes, offset: int = 0) -> list[F32]:
    padded = pad(pcm)
    end = phrase_end(padded[offset * 2 :])
    if end is None:
        return []
    rows = scan(stream, padded, offset)
    return [w for _, w in rows[end : end + POS_SPAN + 1]]


def all_windows(stream: Stream, pcm: bytes, every: int = 1) -> list[F32]:
    return [w for i, (_, w) in enumerate(scan(stream, pcm)) if i % every == 0]


def _stack(windows: Sequence[F32]) -> NDArray[np.float32]:
    return np.stack([w.reshape(FEATURES) for w in windows]).astype(np.float32)


def examples(
    stream: Stream,
    job: WakeJob,
    voices: Voices,
    voiced: Voicing,
    recipe: Recipe,
    progress: Progress,
) -> tuple[NDArray[np.float32], NDArray[np.float32]]:
    rng = np.random.default_rng(recipe.seed)
    split = split_wake(job)
    pos: list[F32] = []
    for clip in split.train:
        pos += positive_windows(stream, clip.pcm)
        for _ in range(recipe.copies):
            pos += positive_windows(
                stream, synth.augment(clip.pcm, rng), int(rng.integers(0, 1280))
            )
    progress(0.15, "Making Hey Jarvis in the laptop's voices.")
    for said in synth.spoken(voices, voiced.train, synth.WAKE_PHRASES):
        pos += positive_windows(stream, said) + positive_windows(stream, synth.augment(said, rng))
    if not pos:
        raise WakewordFailed("No Hey Jarvis was found in the recordings to learn from.")
    progress(0.3, "Making near misses and synthetic TV to learn what is not Hey Jarvis.")
    neg = [w for c in job.speech(held_out=False) for w in all_windows(stream, c.pcm)]
    for said in synth.spoken(voices, voiced.train, synth.NEAR_MISSES):
        neg += all_windows(stream, pad(said))
    for piece in synth.tv(voices, voiced.train, recipe.tv_train_s, rng):
        neg += all_windows(stream, piece, every=2)
    x = np.concatenate([_stack(pos), _stack(neg)])
    y = np.concatenate([np.ones(len(pos)), np.zeros(len(neg))]).astype(np.float32)
    return x, y


def checked(
    data: bytes, mlp: Mlp, x: NDArray[np.float32], check: Callable[[bytes], Runner]
) -> None:
    """The written ONNX must give the trained network's scores (the kit's own runtime)."""
    runner = check(data)
    for row in x[:: max(1, x.shape[0] // 16)][:16]:
        got = float(np.asarray(runner(row.reshape(1, 16, 96))).reshape(-1)[0])
        if abs(got - float(mlp.predict(row[None, :])[0])) > CHECK_TOLERANCE:
            raise WakewordFailed("The new model did not check out after writing; nothing changed.")


def compare(
    stream: Stream, owned: Runner, held: Iterable[bytes], tv: Iterable[bytes]
) -> tuple[WakeEval, WakeEval]:
    """Today's model and the owned one on the same held-out clips and the same TV."""
    mine = Stream(replace(stream.models, wake=owned), history=stream.history)
    clips = list(held)
    seconds, wakes_now, wakes_mine = 0.0, 0, 0
    for piece in tv:
        seconds += len(piece) / 32_000
        wakes_now += listen(stream, piece)
        wakes_mine += listen(mine, piece)

    def result(s: Stream, wakes: int) -> WakeEval:
        misses = sum(listen(s, pad(c)) == 0 for c in clips)
        return WakeEval(
            clips=len(clips), misses=misses, negative_seconds=seconds, false_wakes=wakes
        )

    return result(stream, wakes_now), result(mine, wakes_mine)


def _record(
    data: bytes,
    job: WakeJob,
    voiced: Voicing,
    feature_models: dict[str, str],
    results: tuple[WakeEval, WakeEval],
    now: datetime,
) -> Trained:
    """The file, its ArtifactInfo and its MANIFEST, from (today's, the owned model's) evals."""
    current, owned = results
    wins = beats(owned, current, WAKE_BARS)
    evals = compact_evals(owned.as_evals())
    mine = DataSource(
        name="his recordings",
        licence=OWNER_LICENCE,
        detail=f"{len(job.wake(held_out=False))} Hey Jarvis and his other prompts",
    )
    made = DataSource(name="generated noise and music", licence=OWNER_LICENCE, detail="synth.py")
    card = ModelCard(
        sha256=sha256_hex(data),
        size=len(data),
        trained_at=now,
        feature_models=feature_models,
        sources=(mine, *voiced.sources, made),
        evals=evals,
        current_evals=compact_evals(current.as_evals(counts=False)),
        beats_current=wins,
    )
    info = ArtifactInfo(
        artifact=WakeArtifact.OWNED,
        sha256=card.sha256,
        size=card.size,
        trained_at=now,
        licence=OWNER_LICENCE,
        evals=evals,
        beats_current=wins,
    )
    return Trained(data=data, info=info, manifest=card.text())


def train_owned(
    job: WakeJob,
    stream: Stream,
    feature_models: dict[str, str],
    voices: Voices | None,
    progress: Progress,
    *,
    now: datetime,
    recipe: Recipe | None = None,
    check: Callable[[bytes], Runner] | None = None,
) -> Trained:
    """The whole stage 2 run: data, the network, the ONNX file, its evals and MANIFEST."""
    recipe = recipe or Recipe()
    if voices is None:
        raise WakewordFailed(NO_VOICES)
    voiced = voicing(voices)
    x, y = examples(stream, job, voices, voiced, recipe, lambda f, w: progress(f * 0.5, w))
    progress(0.5, "Training your own model.")
    mlp = Mlp.fit(x, y, recipe, lambda f: progress(0.5 + 0.25 * f, "Training your own model."))
    data = mlp_onnx(mlp.dense(), metadata={"licence": OWNER_LICENCE, "name": "hey_jarvis_owned"})
    if check is not None:
        checked(data, mlp, x, check)
    progress(0.8, "Comparing it with today's model on audio it never heard.")
    tv = synth.tv(voices, voiced.test, recipe.tv_eval_s, np.random.default_rng(recipe.seed + 1))
    held = [c.pcm for c in split_wake(job).held]
    trained = _record(
        data, job, voiced, feature_models, compare(stream, mlp.runner(), held, tv), now
    )
    wins = trained.info.beats_current
    progress(1.0, "Done: it beats today's model." if wins else "Done: today's model stays.")
    return trained


__all__ = ["POS_SPAN", "Voicing", "compare", "phrase_end", "train_owned", "voicing"]
