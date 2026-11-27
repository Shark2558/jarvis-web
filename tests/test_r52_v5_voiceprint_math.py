# tests/test_r52_v5_voiceprint_math.py -- R5.2 V5 (row 84, docs/plans/r5-2-voice.md 3.5): the
# speaker check's arithmetic (static/console-voiceprint-math.js) run by node: Kaldi's filterbank
# against a numpy reference, and the whole pipeline (features -> model on the vendored
# onnxruntime-web -> print -> cosine -> verdict) on synthetic voices with a stand-in model. The
# real model's accuracy (equal error rate <= 5 %) is measured on the laptop.
from __future__ import annotations

import json
import math
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest
from r52_v5_fakes import FIXTURES, ROOT, kaldi_fbank, tiny_speaker_model

HARNESS = FIXTURES / "voiceprint_node.mjs"
TINY_THRESHOLD = 0.85  # the stand-in model's cut between the synthetic owner and the others


def _node(tmp_path: Path, request: dict[str, Any]) -> dict[str, Any]:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed")
    path = tmp_path / "request.json"
    path.write_text(json.dumps(request), encoding="utf-8")
    run = subprocess.run(
        [node, str(HARNESS), str(ROOT), str(path)],
        capture_output=True,
        text=True,
        timeout=240,
        check=False,
    )
    if run.returncode != 0:
        raise AssertionError(run.stderr[-3000:])
    out: dict[str, Any] = json.loads(run.stdout.strip().splitlines()[-1])
    return out


def _signal(seconds: float, seed: int = 3) -> list[int]:
    """Two tones, a glide and a little noise (a fixed LCG): deterministic, int16 scale."""
    state, out = seed, []
    for i in range(int(16000 * seconds)):
        t = i / 16000
        state = (state * 1103515245 + 12345) % 2**31
        noise = (state / 2**31 - 0.5) * 300
        v = 4000 * math.sin(2 * math.pi * 440 * t) + 2500 * math.sin(2 * math.pi * 2300 * t)
        v += 1500 * math.sin(2 * math.pi * (300 + 900 * t) * t) + noise
        out.append(max(-32768, min(32767, round(v))))
    return out


@pytest.mark.parametrize("window", ["hamming", "povey"])
def test_the_filterbank_matches_kaldi_as_torchaudio_computes_it(
    tmp_path: Path, window: str
) -> None:
    np = pytest.importorskip("numpy")
    pcm = _signal(1.0)
    got = _node(tmp_path, {"cmd": "fbank", "pcm": pcm, "window": window})
    want = kaldi_fbank(pcm, window)
    assert got["frames"] == want.shape[0] == 1 + (16000 - 400) // 160  # 98: snip edges
    feats = np.asarray(got["data"]).reshape(got["frames"], 80)
    assert np.max(np.abs(feats - want)) < 2e-3
    assert np.max(np.abs(feats.mean(axis=0))) < 1e-4  # each band's mean is removed


def test_a_tone_lands_in_its_own_mel_band_and_silence_is_floored_not_minus_infinity(
    tmp_path: Path,
) -> None:
    tone = [round(8000 * math.sin(2 * math.pi * 1000 * i / 16000)) for i in range(8000)]
    pcm = [0] * 8000 + tone  # half a second of silence, then the tone: CMN keeps the contrast
    got = _node(tmp_path, {"cmd": "fbank", "pcm": pcm, "window": "hamming"})
    rows = [got["data"][f * 80 : (f + 1) * 80] for f in range(got["frames"])]
    last = rows[-1]
    mel = 1127 * math.log(1 + 1000 / 700)
    low, high = 1127 * math.log(1 + 20 / 700), 1127 * math.log(1 + 8000 / 700)
    band = round((mel - low) / ((high - low) / 81)) - 1
    assert abs(last.index(max(last)) - band) <= 1
    assert all(math.isfinite(v) for row in rows for v in row)


@pytest.fixture(scope="module")
def voices(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    tmp = tmp_path_factory.mktemp("voices")
    model = tmp / "tiny.onnx"
    model.write_bytes(tiny_speaker_model())
    probe = [["owner", s, 1.5] for s in range(100, 112)]
    probe += [["other", s, 1.5] for s in range(200, 212)] + [
        ["tv", s, 1.5] for s in range(300, 312)
    ]
    probe += [["owner", 400, 0.4]]
    request = {"cmd": "voices", "model": str(model), "threshold": TINY_THRESHOLD, "enrol": [1]}
    return _node(tmp, {**request, "probe": probe})


def test_a_minute_of_reading_makes_a_print_from_its_voiced_pieces(voices: dict[str, Any]) -> None:
    p = voices["print"]
    assert p["count"] == 20 and p["dims"] == 32  # 60 s in 3 s pieces, each with enough voice
    assert p["selfMin"] > TINY_THRESHOLD < p["selfMean"]


def test_the_owner_is_recognised_and_another_voice_or_the_tv_is_not(
    voices: dict[str, Any],
) -> None:
    probes = [p for p in voices["probes"] if p["seconds"] == 1.5]
    by = {s: [p for p in probes if p["speaker"] == s] for s in ("owner", "other", "tv")}
    assert {p["verdict"] for p in by["owner"]} == {"owner"}, by["owner"]
    assert {p["verdict"] for p in by["other"] + by["tv"]} == {"other"}
    margin = min(p["score"] for p in by["owner"]) - max(p["score"] for p in by["other"] + by["tv"])
    assert margin > 0.05


def test_a_clip_with_too_little_voice_is_short_never_the_owner(voices: dict[str, Any]) -> None:
    short = [p for p in voices["probes"] if p["seconds"] == 0.4]
    assert short and short[0]["voiced"] < 400 and short[0]["verdict"] == "short"
