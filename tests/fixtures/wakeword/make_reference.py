"""Reference "Hey Jarvis" scores from the real Python openWakeWord, for the browser parity test.

tests/browser/test_wakeword.py feeds these same clips, 1280 samples at a time, through the
JavaScript port (static/console-wakeword.js) and asserts every per-frame score is within 0.02 of
the scores written here. CI never runs this script: it reads the committed
reference_scores.json, so it needs neither openwakeword nor numpy.

Regenerate (only after changing the clips, the models or the pipeline) in a separate venv:

    python3.11 -m venv /tmp/venv-oww
    /tmp/venv-oww/bin/pip install openwakeword==0.6.0 --no-deps
    /tmp/venv-oww/bin/pip install onnxruntime==1.30.0 numpy scipy scikit-learn tqdm requests
    /tmp/venv-oww/bin/python -I tests/fixtures/wakeword/make_reference.py [--synth]

--synth first re-creates the speech clips with ffmpeg's libflite source (an ffmpeg built with
--enable-libflite). The clips are synthetic speech made for this test (CMU Flite voices, BSD-style
licence; no recording of a real person). Silence and noise are generated here.

One deliberate difference from openwakeword.Model: it seeds its 16-frame embedding history with
4 s of numpy random noise in [-1000, 1000). The port draws that noise from mulberry32 with a fixed
seed instead (deterministic, same distribution), so this script installs the very same noise into
the Python preprocessor after every reset. Everything else is openwakeword's own code path:
Model.predict on consecutive 1280-sample frames.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import wave
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
MODELS = HERE.parents[2] / "src/jarvis/api/static/wakeword"
FRAME = 1280
PAD = 16000  # 1 s of silence before and after every clip, as openwakeword's predict_clip does
NOISE_SEED = 0x4A415256  # "JARV"; must equal INIT_NOISE_SEED in console-wakeword.js
NOISE_SAMPLES = 16000 * 4
WEATHER = "The weather today is mild with a light breeze from the west."

# name -> (kind, voice, text, tempo). Positives must be detected; negatives must not be.
SPEECH = {
    "pos_kal": ("positive", "kal", "Hey Jarvis", 1.0),
    "pos_kal16_slow": ("positive", "kal16", "Hey Jarvis", 0.85),
    "pos_awb_comma": ("positive", "awb", "Hey, Jarvis.", 1.0),
    "pos_rms": ("positive", "rms", "Hey Jarvis", 1.0),
    "pos_slt_slow": ("positive", "slt", "Hey Jarvis", 0.85),
    "neg_kal_weather": ("negative", "kal", WEATHER, 1.0),
    "neg_slt_weather": ("negative", "slt", WEATHER, 1.0),
    # near miss: one frame scores above 0.5, so it must be rejected by the 2-frame rule
    "neg_awb_travis": ("negative", "awb", "Hey Travis, have you seen Marcus?", 1.0),
}
SYNTHETIC = {
    "neg_silence": "2 s of digital silence",
    "neg_noise": "3 s of white noise, mulberry32 seed 7, uniform in [-2000, 2000)",
}


def mulberry32(seed: int, n: int) -> np.ndarray:
    """The same generator as the JavaScript port: n floats in [0, 1)."""
    a = seed & 0xFFFFFFFF
    out = np.empty(n, dtype=np.float64)
    for i in range(n):
        a = (a + 0x6D2B79F5) & 0xFFFFFFFF
        t = ((a ^ (a >> 15)) * (a | 1)) & 0xFFFFFFFF
        t = (((t + (((t ^ (t >> 7)) * (t | 61)) & 0xFFFFFFFF)) & 0xFFFFFFFF) ^ t) & 0xFFFFFFFF
        out[i] = ((t ^ (t >> 14)) & 0xFFFFFFFF) / 4294967296.0
    return out


def uniform_int16(seed: int, n: int, low: int, high: int) -> np.ndarray:
    return (np.floor(mulberry32(seed, n) * (high - low)) + low).astype(np.int16)


def read_wav(path: Path) -> np.ndarray:
    with wave.open(str(path), "rb") as f:
        if (f.getframerate(), f.getnchannels(), f.getsampwidth()) != (16000, 1, 2):
            raise ValueError(f"{path.name}: need 16 kHz mono 16-bit PCM")
        return np.frombuffer(f.readframes(f.getnframes()), dtype="<i2").copy()


def write_wav(path: Path, data: np.ndarray) -> None:
    with wave.open(str(path), "wb") as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(16000)
        f.writeframes(data.astype("<i2").tobytes())


def synth(name: str, voice: str, text: str, tempo: float) -> None:
    src = f"flite=text='{text}':voice={voice}"
    subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i", src]
        + ["-af", f"atempo={tempo},aresample=16000", "-ac", "1", "-c:a", "pcm_s16le"]
        + ["-fflags", "+bitexact", "-flags:a", "+bitexact", str(HERE / f"{name}.wav")],
        check=True,
    )


def make_synthetic() -> None:
    write_wav(HERE / "neg_silence.wav", np.zeros(16000 * 2, dtype=np.int16))
    write_wav(HERE / "neg_noise.wav", uniform_int16(7, 16000 * 3, -2000, 2000))


def source_of(name: str) -> str:
    if name in SPEECH:
        _, voice, text, tempo = SPEECH[name]
        return f"ffmpeg libflite voice={voice} text={text!r} atempo={tempo} -> 16 kHz mono s16"
    return SYNTHETIC[name]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--synth", action="store_true", help="re-create the clips first")
    args = ap.parse_args()
    if args.synth:
        for name, (_, voice, text, tempo) in SPEECH.items():
            synth(name, voice, text, tempo)
        make_synthetic()

    import onnxruntime
    import openwakeword

    model = openwakeword.Model(
        wakeword_models=[str(MODELS / "hey_jarvis_v0.1.onnx")],
        inference_framework="onnx",
        melspec_model_path=str(MODELS / "melspectrogram.onnx"),
        embedding_model_path=str(MODELS / "embedding_model.onnx"),
    )
    pre = model.preprocessor
    noise = uniform_int16(NOISE_SEED, NOISE_SAMPLES, -1000, 1000)
    clips: dict[str, dict[str, object]] = {}
    for name in [*SPEECH, *SYNTHETIC]:
        kind = SPEECH[name][0] if name in SPEECH else "negative"
        pcm = read_wav(HERE / f"{name}.wav")
        audio = np.concatenate([np.zeros(PAD, np.int16), pcm, np.zeros(PAD, np.int16)])
        model.reset()
        pre.feature_buffer = pre._get_embeddings(noise)  # the port's deterministic history
        n = len(audio) // FRAME
        scores = [
            float(model.predict(audio[i * FRAME : (i + 1) * FRAME])["hey_jarvis_v0.1"])
            for i in range(n)
        ]
        clips[name] = {
            "file": f"{name}.wav",
            "kind": kind,
            "source": source_of(name),
            "sha256": hashlib.sha256((HERE / f"{name}.wav").read_bytes()).hexdigest(),
            "frames": n,
            "scores": [round(s, 6) for s in scores],
        }
        print(
            f"{name:18s} frames={n:3d} max={max(scores):.4f} above={sum(s >= 0.5 for s in scores)}"
        )

    out = {
        "generator": "tests/fixtures/wakeword/make_reference.py",
        "openwakeword": openwakeword.__dict__.get("__version__", "0.6.0"),
        "onnxruntime": onnxruntime.__version__,
        "numpy": np.__version__,
        "models": {
            p.name: hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(MODELS.glob("*.onnx"))
        },
        "frame_samples": FRAME,
        "pad_samples": PAD,
        "init_noise": {
            "prng": "mulberry32",
            "seed": NOISE_SEED,
            "samples": NOISE_SAMPLES,
            "range": [-1000, 1000],
            "head": [int(v) for v in noise[:8]],
        },
        "clips": clips,
    }
    (HERE / "reference_scores.json").write_text(json.dumps(out, indent=1) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
