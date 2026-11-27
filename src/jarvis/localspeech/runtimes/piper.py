# src/jarvis/localspeech/runtimes/piper.py
"""The light fallback voice: Piper (plan D2), one `.onnx` voice and its `.onnx.json` in the slot's
folder. Imported only in `load`.

Not installed by the kit 1.0.0: today's `piper-tts` package (1.3 and later) is GPL-3.0-or-later,
so it is left out of the pinned requirements until a permissive build or the owner's choice;
Kokoro on the CPU and Google cover its place. This module is ready for it (piper-tts's
`PiperVoice.load` / `synthesize` API).
"""

from __future__ import annotations

import gc
import re
import time
from typing import Any, Final

from jarvis.localspeech.engines import LoadArgs, Spoken
from jarvis.localspeech.protocol import Device

_NOT_VOICE = re.compile(r"[^a-z0-9_-]+")
MAX_VOICE: Final = 40


def voice_id(stem: str) -> str:
    """`en_GB-alan-medium` -> `en_gb-alan-medium` (the API's voice ids are lower case)."""
    return _NOT_VOICE.sub("-", stem.lower())[:MAX_VOICE].strip("-") or "piper"


class PiperEngine:
    def __init__(self, voice: Any, name: str) -> None:
        self._voice = voice
        self._name = name

    @property
    def voices(self) -> frozenset[str]:
        return frozenset({self._name})

    def synthesize(self, text: str, lang: str, voice: str, rate: float) -> Spoken:
        from piper import SynthesisConfig

        started = time.monotonic()
        chunks = list(
            self._voice.synthesize(text, syn_config=SynthesisConfig(length_scale=1 / rate))
        )
        pcm = b"".join(c.audio_int16_bytes for c in chunks)
        rate_hz = int(chunks[0].sample_rate) if chunks else int(self._voice.config.sample_rate)
        return Spoken(pcm, rate_hz, self._name, int((time.monotonic() - started) * 1000))

    def close(self) -> None:
        self._voice = None
        gc.collect()


def load(args: LoadArgs) -> PiperEngine:
    from piper import PiperVoice  # imported only here

    models = sorted(args.model_dir.glob("*.onnx"))
    if not models:
        raise FileNotFoundError("no Piper voice in the slot's folder")
    model = models[0]
    config = model.with_name(model.name + ".json")
    voice = PiperVoice.load(
        str(model), config_path=str(config), use_cuda=args.device is Device.CUDA
    )
    return PiperEngine(voice, voice_id(model.stem))


__all__ = ["PiperEngine", "load", "voice_id"]
