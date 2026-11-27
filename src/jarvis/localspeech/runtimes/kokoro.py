# src/jarvis/localspeech/runtimes/kokoro.py
"""English voice: Kokoro-82M (Apache-2.0 weights) through kokoro-onnx and onnxruntime (MIT), a
British male voice by default (`bm_george`, plan D2). Imported only in `load`, from the pinned
model and voices files in the slot's folder.

kokoro-onnx turns text into phonemes with espeak-ng (`phonemizer`, `espeakng-loader`: GPL-3.0);
that is fine for the owner's own laptop and is listed in the kit's README as a question to settle
before any launch, like today's wake-word model.
"""

from __future__ import annotations

import gc
import re
import time
from pathlib import Path
from typing import Any, Final

from jarvis.localspeech.audio import float_to_pcm16
from jarvis.localspeech.engines import LoadArgs, Spoken
from jarvis.localspeech.protocol import VOICE_ID, Device

MODEL_FILE: Final = "kokoro-v1.0.onnx"
VOICES_FILE: Final = "voices-v1.0.bin"
BRITISH_PREFIXES: Final = ("bm_", "bf_")  # Kokoro's British English voices
LANG: Final = "en-gb"
_VOICE = re.compile(VOICE_ID)


def british_voices(names: list[str] | tuple[str, ...]) -> frozenset[str]:
    return frozenset(n for n in names if n.startswith(BRITISH_PREFIXES) and _VOICE.fullmatch(n))


def _one(folder: Path, name: str) -> Path:
    path = folder / name
    if not path.is_file():
        raise FileNotFoundError(name)
    return path


class KokoroEngine:
    def __init__(self, kokoro: Any) -> None:
        self._kokoro = kokoro
        self._voices = british_voices(list(kokoro.get_voices()))
        if not self._voices:
            raise RuntimeError("the voices file has no British voice")

    @property
    def voices(self) -> frozenset[str]:
        return self._voices

    def synthesize(self, text: str, lang: str, voice: str, rate: float) -> Spoken:
        started = time.monotonic()
        samples, sample_rate = self._kokoro.create(text, voice=voice, speed=rate, lang=LANG)
        pcm = float_to_pcm16(samples)
        return Spoken(pcm, int(sample_rate), voice, int((time.monotonic() - started) * 1000))

    def close(self) -> None:
        self._kokoro = None
        gc.collect()


def load(args: LoadArgs) -> KokoroEngine:
    import onnxruntime as ort  # MIT; imported only here
    from kokoro_onnx import Kokoro

    model = _one(args.model_dir, MODEL_FILE)
    voices = _one(args.model_dir, VOICES_FILE)
    available = set(ort.get_available_providers())
    providers = ["CPUExecutionProvider"]
    if args.device is Device.CUDA and "CUDAExecutionProvider" in available:
        providers.insert(0, "CUDAExecutionProvider")
    options = ort.SessionOptions()
    options.intra_op_num_threads = args.threads
    session = ort.InferenceSession(str(model), sess_options=options, providers=providers)
    return KokoroEngine(Kokoro.from_session(session, str(voices)))


__all__ = ["KokoroEngine", "british_voices", "load"]
