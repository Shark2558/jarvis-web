# src/jarvis/localspeech/wakeword/synth.py
"""Synthetic audio for stage 2's training and the wake word's evals (R5.2 row 83, plan 5), made on
the kit at run time and never stored in the repo: sentences spoken by the kit's permissively
licensed voices (`Voices`, V1's engines), with generated music-like tones and noise under them,
the "TV" the false-wake eval listens to; near misses ("Hey Travis"); augmentation for his clips.

The sentences are built here from short word lists written for JARVIS (no corpus, no licence
question) and never contain the wake phrase. Openly licensed recordings are not used: none could
be pinned with a SHA-256 from the build environment (`LEFT_OUT`). Needs NumPy (kit only).
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from typing import Final

import numpy as np
from numpy.typing import NDArray

from jarvis.localspeech.wakeword.formats import SAMPLE_RATE
from jarvis.localspeech.wakeword.port import Voices

WAKE_PHRASES: Final = ("Hey Jarvis", "Hey, Jarvis.", "Hey Jarvis!", "Hey Jarvis?")
NEAR_MISSES: Final = (
    "Hey Travis",
    "Hey Mavis",
    "Hey Harvey",
    "Harvest time",
    "Hey jars",
    "Hey service",
    "Say this",
    "Hey Charles",
    "Nervous",
    "Hey there",
    "Jar of this",
    "Have this",
)
LEFT_OUT: Final = {
    "Google Speech Commands v0.02 (CC BY 4.0)": "its SHA-256 could not be recorded from the "
    "build environment (host not reachable), so it is not downloaded",
}
_SUBJECTS = (
    "the weather",
    "my sister",
    "the old train",
    "our team",
    "the market",
    "a neighbour",
    "the river",
    "this recipe",
    "the new phone",
    "the garden",
    "a small cafe",
    "the bus",
)
_VERBS = (
    "opens",
    "looks",
    "moves",
    "starts",
    "feels",
    "stays",
    "turns",
    "grows",
    "waits",
    "closes",
    "sounds",
    "runs",
)
_ENDS = (
    "early on Sunday",
    "near the station",
    "after the rain",
    "before dinner",
    "in the evening",
    "every morning",
    "by the window",
    "at the corner",
    "on the radio",
    "without a word",
    "for a while",
    "across the road",
)
SPEECH_GAIN: Final = 0.9
_I16 = 32767


def sentences(rng: np.random.Generator, n: int) -> list[str]:
    """`n` plain sentences that never say the wake word."""
    out = []
    for _ in range(n):
        s = f"{rng.choice(_SUBJECTS)} {rng.choice(_VERBS)} {rng.choice(_ENDS)}"
        out.append(s[0].upper() + s[1:] + ".")
    return out


def as_float(pcm: bytes) -> NDArray[np.float64]:
    return np.frombuffer(pcm, dtype="<i2").astype(np.float64)


def as_pcm(x: NDArray[np.float64]) -> bytes:
    return np.clip(np.round(x), -_I16 - 1, _I16).astype("<i2").tobytes()


def noise(
    rng: np.random.Generator, seconds: float, colour: str, level: float
) -> NDArray[np.float64]:
    """White, pink or brown noise at an RMS of `level` (in PCM16 units)."""
    n = int(SAMPLE_RATE * seconds)
    white = rng.normal(0, 1, n)
    if colour == "brown":
        shaped = np.cumsum(white)
        shaped -= np.convolve(shaped, np.ones(400) / 400, mode="same")
    elif colour == "pink":
        spectrum = np.fft.rfft(white)
        spectrum /= np.sqrt(np.maximum(np.arange(spectrum.shape[0]), 1))
        shaped = np.fft.irfft(spectrum, n)
    else:
        shaped = white
    rms = float(np.sqrt(np.mean(shaped**2))) or 1.0
    out: NDArray[np.float64] = shaped / rms * level
    return out


def music(rng: np.random.Generator, seconds: float, level: float) -> NDArray[np.float64]:
    """Chords of harmonics with soft attacks, changing every half to two seconds."""
    n = int(SAMPLE_RATE * seconds)
    out = np.zeros(n)
    at = 0
    while at < n:
        length = min(n - at, int(SAMPLE_RATE * rng.uniform(0.5, 2.0)))
        t = np.arange(length) / SAMPLE_RATE
        root = 110 * 2 ** (rng.integers(0, 24) / 12)
        chord = sum(
            np.sin(2 * np.pi * root * r * h * t) / h for r in (1.0, 1.26, 1.5) for h in (1, 2, 3)
        )
        envelope = np.minimum(1.0, t / 0.05) * np.exp(-t * rng.uniform(0.3, 1.5))
        out[at : at + length] = chord * envelope
        at += length
    rms = float(np.sqrt(np.mean(out**2))) or 1.0
    scaled: NDArray[np.float64] = out / rms * level
    return scaled


def mix(speech: NDArray[np.float64], bed: NDArray[np.float64], snr_db: float) -> bytes:
    """`speech` over `bed` at `snr_db` (the bed is cut or repeated to fit)."""
    if bed.shape[0] < speech.shape[0]:
        bed = np.resize(bed, speech.shape[0])
    bed = bed[: speech.shape[0]]
    s_rms = float(np.sqrt(np.mean(speech**2))) or 1.0
    b_rms = float(np.sqrt(np.mean(bed**2))) or 1.0
    return as_pcm(speech + bed * (s_rms / b_rms) / 10 ** (snr_db / 20))


def augment(pcm: bytes, rng: np.random.Generator) -> bytes:
    """One noisy copy of a clip: gain within +-6 dB, a short shift, a noise or music bed."""
    x = as_float(pcm) * 10 ** (rng.uniform(-6, 6) / 20)
    x = np.concatenate([np.zeros(int(rng.integers(0, 2400))), x])
    seconds = x.shape[0] / SAMPLE_RATE
    bed = (
        music(rng, seconds, 1.0)
        if rng.random() < 0.3
        else noise(rng, seconds, str(rng.choice(["white", "pink", "brown"])), 1.0)
    )
    return mix(x, bed, float(rng.uniform(5, 25)))


def spoken(voices: Voices, names: Sequence[str], texts: Sequence[str]) -> Iterator[bytes]:
    """Every text in every voice (names checked by `Voices`)."""
    for name in names:
        for text in texts:
            yield voices.say(name, text)


def tv(
    voices: Voices, names: Sequence[str], seconds: float, rng: np.random.Generator
) -> Iterator[bytes]:
    """About `seconds` of "TV": sentences and near misses over music or noise, in ~30 s pieces
    (each piece one stream for the evals)."""
    made = 0.0
    while made < seconds:
        texts = sentences(rng, 6) + [str(rng.choice(NEAR_MISSES))]
        voice = str(rng.choice(list(names)))
        speech = np.concatenate([as_float(voices.say(voice, t)) for t in texts]) * SPEECH_GAIN
        piece = speech.shape[0] / SAMPLE_RATE
        bed = music(rng, piece, 1.0) if rng.random() < 0.5 else noise(rng, piece, "pink", 1.0)
        made += piece
        yield mix(speech, bed, float(rng.uniform(3, 20)))


__all__ = [
    "LEFT_OUT",
    "NEAR_MISSES",
    "WAKE_PHRASES",
    "augment",
    "mix",
    "music",
    "noise",
    "sentences",
    "spoken",
    "tv",
]
