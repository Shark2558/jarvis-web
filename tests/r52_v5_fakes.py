# tests/r52_v5_fakes.py -- R5.2 V5 (row 84, the speaker check): what its tests share.
#   tiny_speaker_model(dims)  a stand-in speaker-embedding model, written here as ONNX bytes (no
#                             onnx package): feats float32[1, T, 80] -> embs float32[1, dims], the
#                             real slot's input and output (WeSpeaker's export). It pools each mel
#                             band's spread over time and projects it on fixed, centred directions:
#                             enough to tell the synthetic voices apart, nothing like a real model.
#   kaldi_fbank(pcm, window)  a numpy reference of Kaldi's fbank as torchaudio.compliance.kaldi
#                             computes it for WeSpeaker (80 bins, 25 / 10 ms, no dither, CMN after)
#   VOICES_JS                 tests/fixtures/r52_v5/voices.js (synthetic voices, never a recording)
from __future__ import annotations

import hashlib
import math
import struct
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "src/jarvis/api/static"
FIXTURES = ROOT / "tests/fixtures/r52_v5"
VOICES_JS = FIXTURES / "voices.js"
MEL_BINS = 80
FLOAT, INT64 = 1, 7  # TensorProto.DataType
ATTR_INTS = 7  # AttributeProto.AttributeType
ATTR_INT = 2


def _varint(n: int) -> bytes:
    out = bytearray()
    while True:
        b = n & 0x7F
        n >>= 7
        out.append(b | (0x80 if n else 0))
        if not n:
            return bytes(out)


def _key(field: int, wire: int) -> bytes:
    return _varint(field << 3 | wire)


def _len(field: int, payload: bytes) -> bytes:
    return _key(field, 2) + _varint(len(payload)) + payload


def _int(field: int, n: int) -> bytes:
    return _key(field, 0) + _varint(n)


def _str(field: int, text: str) -> bytes:
    return _len(field, text.encode())


def _tensor(name: str, dims: list[int], values: list[float]) -> bytes:
    body = b"".join(_int(1, d) for d in dims) + _int(2, FLOAT) + _str(8, name)
    return body + _len(9, struct.pack(f"<{len(values)}f", *values))


def _value(name: str, dims: list[int | str]) -> bytes:
    shape = b"".join(
        _len(1, _str(2, d) if isinstance(d, str) else _int(1, d)) for d in dims
    )  # TensorShapeProto.dim: Dimension{dim_value | dim_param}
    tensor = _int(1, FLOAT) + _len(2, shape)
    return _str(1, name) + _len(2, _len(1, tensor))


def _node(op: str, inputs: list[str], outputs: list[str], attrs: bytes = b"") -> bytes:
    body = b"".join(_str(1, i) for i in inputs) + b"".join(_str(2, o) for o in outputs)
    return body + _str(3, f"{op}_{outputs[0]}") + _str(4, op) + attrs


def _directions(dims: int, seed: int) -> list[float]:
    """W[80, dims] row-major: fixed +-1 directions, each column centred (no all-bands component)."""
    state = seed
    cols: list[list[float]] = []
    for _ in range(dims):
        col = []
        for _ in range(MEL_BINS):
            state = (state * 1103515245 + 12345) % 2**31
            col.append(1.0 if state >> 16 & 1 else -1.0)
        mean = sum(col) / MEL_BINS
        cols.append([(v - mean) / math.sqrt(MEL_BINS) for v in col])
    return [cols[j][i] for i in range(MEL_BINS) for j in range(dims)]


def tiny_speaker_model(dims: int = 32, seed: int = 7) -> bytes:
    axes = _len(5, _str(1, "axes") + _int(8, 1) + _int(20, ATTR_INTS))
    keep = _len(5, _str(1, "keepdims") + _int(3, 0) + _int(20, ATTR_INT))
    nodes = [
        _node("Mul", ["feats", "feats"], ["sq"]),
        _node("ReduceMean", ["sq"], ["ms"], axes + keep),
        _node("Sqrt", ["ms"], ["spread"]),
        _node("MatMul", ["spread", "W"], ["embs"]),
    ]
    graph = b"".join(_len(1, n) for n in nodes) + _str(2, "tiny-speaker")
    graph += _len(5, _tensor("W", [MEL_BINS, dims], _directions(dims, seed)))
    graph += _len(11, _value("feats", [1, "T", MEL_BINS])) + _len(12, _value("embs", [1, dims]))
    opset = _len(8, _str(1, "") + _int(2, 13))
    return _int(1, 7) + _str(2, "jarvis-tests") + _len(7, graph) + opset


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# ---- the numpy reference (imported lazily: the browser venv has no numpy) ----------------------
def kaldi_fbank(pcm: Any, window: str = "hamming") -> Any:
    """torchaudio.compliance.kaldi.fbank(waveform, num_mel_bins=80, frame_length=25,
    frame_shift=10, dither=0, window_type=window, sample_frequency=16000) on int16-scale samples,
    then each band's mean over time removed (WeSpeaker's CMN)."""
    import numpy as np

    x = np.asarray(pcm, dtype=np.float64)
    size, shift, fft = 400, 160, 512
    count = 1 + (len(x) - size) // shift
    frames = np.stack([x[i * shift : i * shift + size] for i in range(count)])
    frames = frames - frames.mean(axis=1, keepdims=True)
    prev = np.concatenate([frames[:, :1], frames[:, :-1]], axis=1)
    frames = frames - 0.97 * prev
    n = np.arange(size)
    hann = 0.5 - 0.5 * np.cos(2 * np.pi * n / (size - 1))
    win = 0.54 - 0.46 * np.cos(2 * np.pi * n / (size - 1)) if window == "hamming" else hann**0.85
    power = np.abs(np.fft.rfft(frames * win, n=fft)) ** 2

    def mel(f: Any) -> Any:
        return 1127.0 * np.log(1.0 + np.asarray(f) / 700.0)

    low, high = mel(20.0), mel(8000.0)
    delta = (high - low) / (MEL_BINS + 1)
    b = np.arange(MEL_BINS)[:, None]
    left, centre, right = low + b * delta, low + (b + 1) * delta, low + (b + 2) * delta
    m = mel(16000 / fft * np.arange(fft // 2))[None, :]
    up, down = (m - left) / (centre - left), (right - m) / (right - centre)
    banks = np.concatenate([np.maximum(0, np.minimum(up, down)), np.zeros((MEL_BINS, 1))], axis=1)
    logmel = np.log(np.maximum(power @ banks.T, np.finfo(np.float32).eps))
    return logmel - logmel.mean(axis=0, keepdims=True)
