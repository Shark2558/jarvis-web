# tests/test_r52_v1_runtimes.py -- R5.2 V1: the runtime adapters without their packages. Whisper's
# language codes, prompt (the owner's words) and confidence; Kokoro's British voices; Piper's voice
# ids; each adapter driven through a stand-in for its library's object; the audio helpers.
# The real models run only on the laptop (the kit's self-test).
from __future__ import annotations

import math
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from jarvis.localspeech.engines import LoadArgs, SttEngine, TtsEngine
from jarvis.localspeech.protocol import VOICE_ID, Device
from jarvis.localspeech.runtimes import indic_conformer as conformer
from jarvis.localspeech.runtimes import kokoro, piper, whisper


def test_whisper_codes_prompt_and_confidence() -> None:
    assert whisper.language_code("en-IN") == "en"
    assert whisper.prompt_of(["JARVIS", " ", "Ananya"]) == "JARVIS, Ananya"
    assert whisper.prompt_of([]) is None
    assert len(whisper.prompt_of(["x" * 39] * 50) or "") == whisper.PROMPT_CHARS
    assert whisper.confidence_of([]) == 0.0
    assert whisper.confidence_of([math.log(0.8), math.log(0.8)]) == pytest.approx(0.8)
    assert whisper.confidence_of([5.0]) == 1.0


class FakeWhisperModel:
    def __init__(self) -> None:
        self.kwargs: dict[str, Any] = {}

    def transcribe(self, audio: Any, **kwargs: Any) -> tuple[Any, Any]:
        self.kwargs = kwargs
        segments = [
            SimpleNamespace(text=" Call ", avg_logprob=-0.1),
            SimpleNamespace(text="Ananya.", avg_logprob=-0.3),
        ]
        return iter(segments), SimpleNamespace(language="en")


def test_the_whisper_engine_passes_the_language_and_words() -> None:
    pytest.importorskip("numpy")
    model = FakeWhisperModel()
    engine = whisper.WhisperEngine(model)
    assert isinstance(engine, SttEngine)
    heard = engine.transcribe(b"\x00\x00" * 16_000, "en-IN", ("Ananya",))
    assert heard.text == "Call Ananya." and heard.confidence == pytest.approx(math.exp(-0.2))
    assert model.kwargs["language"] == "en" and model.kwargs["initial_prompt"] == "Ananya"
    assert model.kwargs["condition_on_previous_text"] is False
    engine.close()


class FakeKokoro:
    def get_voices(self) -> list[str]:
        return ["af_heart", "bm_george", "bm_lewis", "bf_emma", "BM_Bad"]

    def create(self, text: str, **kw: Any) -> tuple[Any, int]:
        import numpy as np

        self.kw = kw
        return np.zeros(2400, dtype=np.float32), 24_000


def test_the_kokoro_engine_offers_british_voices_and_speaks() -> None:
    pytest.importorskip("numpy")
    fake = FakeKokoro()
    engine = kokoro.KokoroEngine(fake)
    assert isinstance(engine, TtsEngine)
    assert engine.voices == {"bm_george", "bm_lewis", "bf_emma"}
    spoken = engine.synthesize("Hello sir.", "en-IN", "bm_george", 1.2)
    assert (spoken.sample_rate, len(spoken.pcm), spoken.voice) == (24_000, 4800, "bm_george")
    assert fake.kw == {"voice": "bm_george", "speed": 1.2, "lang": "en-gb"}


def test_a_voices_file_without_a_british_voice_is_refused() -> None:
    class American(FakeKokoro):
        def get_voices(self) -> list[str]:
            return ["af_heart"]

    with pytest.raises(RuntimeError):
        kokoro.KokoroEngine(American())


def test_piper_voice_ids_fit_the_protocol() -> None:
    import re

    for stem in ("en_GB-alan-medium", "en_GB-northern_english_male-medium", "Ünïcode voice" * 5):
        assert re.fullmatch(VOICE_ID, piper.voice_id(stem))
    assert piper.voice_id("en_GB-alan-medium") == "en_gb-alan-medium"


def test_the_indic_conformer_codes() -> None:
    assert conformer.language_code("hi-IN") == "hi" and conformer.language_code("kok-IN") == "kok"


def test_the_loaders_fail_plainly_without_their_files(tmp_path: Path) -> None:
    args = LoadArgs(tmp_path, Device.CPU, 1, "bm_george")
    with pytest.raises((FileNotFoundError, ImportError)):
        kokoro.load(args)
    with pytest.raises((FileNotFoundError, ImportError)):
        piper.load(args)


def test_resampling_keeps_the_length_and_the_tone() -> None:
    np = pytest.importorskip("numpy")
    from jarvis.localspeech.audio import pcm16_to_float, resample_pcm16, tone

    voice = tone(1.0, hz=300.0, rate=24_000)
    down = resample_pcm16(voice, 24_000, 16_000)
    assert len(down) == 2 * 16_000
    x = pcm16_to_float(down)
    spectrum = np.abs(np.fft.rfft(x))
    assert abs(int(np.argmax(spectrum)) - 300) <= 1  # 1 Hz bins over one second
    assert resample_pcm16(voice, 24_000, 24_000) is voice
    high = tone(1.0, hz=10_000.0, rate=24_000)  # above the new Nyquist: filtered away
    assert float(np.abs(pcm16_to_float(resample_pcm16(high, 24_000, 16_000))).max()) < 0.05
    with pytest.raises(ValueError):
        resample_pcm16(voice, 0, 16_000)


def test_float_audio_is_clipped_into_pcm16() -> None:
    pytest.importorskip("numpy")
    from jarvis.localspeech.audio import float_to_pcm16, pcm16_to_float

    pcm = float_to_pcm16([2.0, -2.0, 0.0, float("nan")])
    assert list(pcm16_to_float(pcm).round(3)) == [1.0, -1.0, 0.0, 0.0]
    with pytest.raises(ValueError):
        pcm16_to_float(b"\x00")
