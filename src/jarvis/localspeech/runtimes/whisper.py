# src/jarvis/localspeech/runtimes/whisper.py
"""English listening: faster-whisper (MIT) with CTranslate2 (MIT), Whisper weights MIT (plan D2).
`whisper-small` int8 by default, `whisper-medium` int8 when the session shows it is better.
The packages are imported only in `load`, from the pinned files in the slot's folder (no download
from here: `local_files_only`).
"""

from __future__ import annotations

import gc
import math
import os
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any, Final

from jarvis.localspeech.audio import pcm16_to_float
from jarvis.localspeech.engines import Heard, LoadArgs
from jarvis.localspeech.protocol import Device

BEAM: Final = 5
PROMPT_CHARS: Final = 600  # Whisper's prompt is short; the owner's words go first


def language_code(lang: str) -> str:
    """`en-IN` -> `en` (Whisper's codes)."""
    return lang.split("-", 1)[0].lower()


def prompt_of(phrases: Sequence[str]) -> str | None:
    """The owner's words to recognise as Whisper's initial prompt (a spelling hint)."""
    text = ", ".join(p.strip() for p in phrases if p.strip())
    return text[:PROMPT_CHARS] or None


def confidence_of(avg_logprobs: Sequence[float]) -> float:
    if not avg_logprobs:
        return 0.0
    return max(0.0, min(1.0, math.exp(sum(avg_logprobs) / len(avg_logprobs))))


def _cuda_libraries() -> None:
    """On Windows, let CTranslate2 find NVIDIA's cuBLAS / cuDNN wheels (requirements-gpu.txt)."""
    if sys.platform != "win32":
        return
    for base in map(Path, sys.path):
        nvidia = base / "nvidia"
        if nvidia.is_dir():
            for lib in nvidia.glob("*/bin"):
                os.add_dll_directory(str(lib))  # type: ignore[attr-defined,unused-ignore]


class WhisperEngine:
    def __init__(self, model: Any) -> None:
        self._model = model

    def transcribe(self, pcm16k: bytes, lang: str, phrases: Sequence[str]) -> Heard:
        segments, _info = self._model.transcribe(
            pcm16_to_float(pcm16k),
            language=language_code(lang),
            beam_size=BEAM,
            initial_prompt=prompt_of(phrases),
            condition_on_previous_text=False,
            vad_filter=False,
            without_timestamps=True,
        )
        parts = list(segments)
        text = " ".join(str(s.text).strip() for s in parts).strip()
        return Heard(text=text, confidence=confidence_of([float(s.avg_logprob) for s in parts]))

    def close(self) -> None:
        self._model = None
        gc.collect()


def load(args: LoadArgs) -> WhisperEngine:
    from faster_whisper import WhisperModel  # MIT; imported only here

    if args.device is Device.CUDA:
        _cuda_libraries()
    model = WhisperModel(
        str(args.model_dir),
        device=args.device.value,
        compute_type="int8_float16" if args.device is Device.CUDA else "int8",
        cpu_threads=args.threads,
        local_files_only=True,
    )
    return WhisperEngine(model)


__all__ = ["WhisperEngine", "confidence_of", "language_code", "load", "prompt_of"]
