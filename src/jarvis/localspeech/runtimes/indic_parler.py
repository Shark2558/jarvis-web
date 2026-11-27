# src/jarvis/localspeech/runtimes/indic_parler.py
"""Indian-language voice for R18's laptop mode: AI4Bharat Indic Parler-TTS (Apache-2.0, plan D3),
from the pinned files in the slot's folder; its description tokenizer sits in the
`description-tokenizer/` sub-folder (pinned the same way). Imported only in `load`.

Not installed by the kit 1.0.0: its files and its runtime (PyTorch, transformers, parler-tts)
could not be pinned with confirmed SHA-256 when the kit was built (models.json `left_out`).
"""

from __future__ import annotations

import gc
import time
from typing import Any, Final

from jarvis.localspeech.audio import float_to_pcm16
from jarvis.localspeech.engines import LoadArgs, Spoken
from jarvis.localspeech.protocol import Device

VOICE: Final = "calm-male"
DESCRIPTION: Final = (
    "A male speaker delivers clear, calm speech at a moderate pace. "
    "The recording is of very high quality, with no background noise."
)
DESCRIPTION_TOKENIZER: Final = "description-tokenizer"


class IndicParlerEngine:
    def __init__(self, model: Any, prompt_tok: Any, desc_tok: Any, torch: Any, device: str) -> None:
        self._model = model
        self._prompt_tok = prompt_tok
        self._desc_tok = desc_tok
        self._torch = torch
        self._device = device

    @property
    def voices(self) -> frozenset[str]:
        return frozenset({VOICE})

    def synthesize(self, text: str, lang: str, voice: str, rate: float) -> Spoken:
        started = time.monotonic()
        desc = self._desc_tok(DESCRIPTION, return_tensors="pt").to(self._device)
        prompt = self._prompt_tok(text, return_tensors="pt").to(self._device)
        with self._torch.inference_mode():
            generated = self._model.generate(
                input_ids=desc.input_ids,
                attention_mask=desc.attention_mask,
                prompt_input_ids=prompt.input_ids,
                prompt_attention_mask=prompt.attention_mask,
            )
        samples = generated.cpu().numpy().squeeze()
        rate_hz = int(self._model.config.sampling_rate)
        return Spoken(
            float_to_pcm16(samples), rate_hz, VOICE, int((time.monotonic() - started) * 1000)
        )

    def close(self) -> None:
        self._model = None
        gc.collect()


def load(args: LoadArgs) -> IndicParlerEngine:
    import torch  # imported only here
    from parler_tts import ParlerTTSForConditionalGeneration
    from transformers import AutoTokenizer

    device = "cuda:0" if args.device is Device.CUDA and torch.cuda.is_available() else "cpu"
    torch.set_num_threads(args.threads)
    folder = str(args.model_dir)
    model = ParlerTTSForConditionalGeneration.from_pretrained(folder, local_files_only=True)
    prompt_tok = AutoTokenizer.from_pretrained(folder, local_files_only=True)
    desc_tok = AutoTokenizer.from_pretrained(
        str(args.model_dir / DESCRIPTION_TOKENIZER), local_files_only=True
    )
    return IndicParlerEngine(model.to(device), prompt_tok, desc_tok, torch, device)


__all__ = ["IndicParlerEngine", "load"]
