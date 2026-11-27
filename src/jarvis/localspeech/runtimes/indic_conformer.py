# src/jarvis/localspeech/runtimes/indic_conformer.py
"""Indian-language listening for R18's laptop mode: AI4Bharat IndicConformer 600M multilingual
(MIT, plan D3), loaded with its own model code from the pinned files in the slot's folder
(`trust_remote_code` reads only those hashed files: `local_files_only`, nothing is fetched).
R18's language check decides which languages actually use it. Imported only in `load`.

Not installed by the kit 1.0.0: its files and its runtime (PyTorch, torchaudio, transformers)
could not be pinned with confirmed SHA-256 when the kit was built (models.json `left_out`).
"""

from __future__ import annotations

import gc
from collections.abc import Sequence
from typing import Any, Final

from jarvis.localspeech.audio import pcm16_to_float
from jarvis.localspeech.engines import Heard, LoadArgs
from jarvis.localspeech.protocol import Device

DECODER: Final = "ctc"  # the model's faster decoder ("rnnt" is the other)
NO_CONFIDENCE: Final = 0.5  # the model gives no confidence; R18's check scores the text itself


def language_code(lang: str) -> str:
    """`hi-IN` -> `hi` (the model's codes)."""
    return lang.split("-", 1)[0].lower()


class IndicConformerEngine:
    def __init__(self, model: Any, torch: Any, device: str) -> None:
        self._model = model
        self._torch = torch
        self._device = device

    def transcribe(self, pcm16k: bytes, lang: str, phrases: Sequence[str]) -> Heard:
        wav = self._torch.from_numpy(pcm16_to_float(pcm16k)).unsqueeze(0).to(self._device)
        with self._torch.inference_mode():
            text = self._model(wav, language_code(lang), DECODER)
        return Heard(text=str(text).strip(), confidence=NO_CONFIDENCE)

    def close(self) -> None:
        self._model = None
        gc.collect()


def load(args: LoadArgs) -> IndicConformerEngine:
    import torch  # imported only here
    from transformers import AutoModel

    device = "cuda" if args.device is Device.CUDA and torch.cuda.is_available() else "cpu"
    torch.set_num_threads(args.threads)
    model = AutoModel.from_pretrained(
        str(args.model_dir), trust_remote_code=True, local_files_only=True
    ).to(device)
    return IndicConformerEngine(model, torch, device)


__all__ = ["IndicConformerEngine", "language_code", "load"]
