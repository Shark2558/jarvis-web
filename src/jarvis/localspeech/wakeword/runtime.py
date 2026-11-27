# src/jarvis/localspeech/wakeword/runtime.py
"""The kit's ONNX runtime for the wake word (R5.2 row 83): the console's three vendored models,
read from the installed package (`jarvis/api/static/wakeword`, never downloaded by the kit),
each checked against its SHA-256 in that folder's MANIFEST.txt before it is loaded, and run with
onnxruntime (MIT), imported only here and only when training starts.

Licence (recorded, plan risk 2): these files are CC BY-NC-SA 4.0 (static/wakeword/LICENSE.txt).
The kit uses them on the owner's own laptop, for his own assistant, exactly as his browser does,
and never serves or ships them; what it trains from their features is his (`LicenseRef-Owner`).
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

import numpy as np

from jarvis.localspeech.wakeword.formats import (
    CONSOLE_MODELS_DIR,
    CURRENT_MODEL,
    EMBEDDING_MODEL,
    MEL_MODEL,
    console_pins,
)
from jarvis.localspeech.wakeword.port import WakewordFailed
from jarvis.localspeech.wakeword.streaming import F32, FeatureModels, Runner

CONSOLE_MODELS: Final = CONSOLE_MODELS_DIR
NO_RUNTIME = "The kit's ONNX runtime is not installed (onnxruntime); reinstall the kit."
CHANGED = "One of the wake-word models on this laptop differs from the pinned file; reinstall."


@dataclass(frozen=True)
class ConsoleModels:
    features: FeatureModels  # with today's wake model
    shas: dict[str, str]  # file name -> SHA-256 (the console's MANIFEST)

    @property
    def feature_shas(self) -> dict[str, str]:
        return {n: self.shas[n] for n in (MEL_MODEL, EMBEDDING_MODEL)}


def verified(folder: Path, name: str, pins: dict[str, str]) -> bytes:
    data = (folder / name).read_bytes()
    if pins.get(name) != hashlib.sha256(data).hexdigest():
        raise WakewordFailed(CHANGED)
    return data


def onnx_runner(data: bytes) -> Runner:
    """One ONNX model as a `Runner` (CPU; the wake word's models are small)."""
    try:
        import onnxruntime  # the kit's runtime, loaded only when training starts
    except ImportError:
        raise WakewordFailed(NO_RUNTIME) from None
    session: Any = onnxruntime.InferenceSession(data, providers=["CPUExecutionProvider"])
    name = session.get_inputs()[0].name

    def run(x: F32) -> F32:
        out: F32 = np.asarray(session.run(None, {name: x.astype(np.float32)})[0], dtype=np.float32)
        return out

    return run


def open_console_models(folder: Path = CONSOLE_MODELS) -> ConsoleModels:
    try:
        pins = console_pins(folder)
        mel, emb, wake = (
            verified(folder, n, pins) for n in (MEL_MODEL, EMBEDDING_MODEL, CURRENT_MODEL)
        )
    except OSError:
        raise WakewordFailed(CHANGED) from None
    features = FeatureModels(mel=onnx_runner(mel), emb=onnx_runner(emb), wake=onnx_runner(wake))
    shas = {n: pins[n] for n in (MEL_MODEL, EMBEDDING_MODEL, CURRENT_MODEL)}
    return ConsoleModels(features=features, shas=shas)


__all__ = ["CONSOLE_MODELS", "ConsoleModels", "onnx_runner", "open_console_models", "verified"]
