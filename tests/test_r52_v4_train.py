# tests/test_r52_v4_train.py -- R5.2 V4 (row 83): stage 1 (openWakeWord's custom-verifier method in
# NumPy) and stage 2 (the owned network, its ONNX file and MANIFEST), on fake models and synthetic
# tones only. The ONNX bytes are decoded here field by field and evaluated, so the file says what
# the network computes (tests/browser/test_r52_v4_wake_own.py loads it in onnxruntime-web).
from __future__ import annotations

import math
import struct
from datetime import UTC, datetime
from typing import Any

import pytest

np = pytest.importorskip("numpy")

from jarvis.localspeech.protocol import OWNER_LICENCE, PromptKind, WakeArtifact  # noqa: E402
from jarvis.localspeech.wakeword import fakes, formats, synth  # noqa: E402
from jarvis.localspeech.wakeword.formats import VerifierFile  # noqa: E402
from jarvis.localspeech.wakeword.mlp import Mlp, Recipe  # noqa: E402
from jarvis.localspeech.wakeword.onnx_write import Activation, Dense, mlp_onnx  # noqa: E402
from jarvis.localspeech.wakeword.owned_train import phrase_end, train_owned, voicing  # noqa: E402
from jarvis.localspeech.wakeword.port import WakeClip, WakeJob, WakewordFailed  # noqa: E402
from jarvis.localspeech.wakeword.streaming import Stream, listen, pad  # noqa: E402
from jarvis.localspeech.wakeword.verifier_train import (  # noqa: E402
    fit_logistic,
    other_clips,
    split_wake,
    standardise,
    train_verifier,
)

NOW = datetime(2026, 11, 27, 10, 0, tzinfo=UTC)
SESSION = "vs_0123456789ab"
SMALL = Recipe(hidden=16, epochs=8, batch=256, copies=1, tv_train_s=20, tv_eval_s=30)


def _job(artifact: WakeArtifact, clips: tuple[WakeClip, ...] | None = None) -> WakeJob:
    return WakeJob(artifact=artifact, session_id=SESSION, clips=clips or fakes.session_clips())


def _quiet(progress: list[tuple[float, str]]) -> Any:
    return lambda f, w: progress.append((f, w))


@pytest.fixture(scope="module")
def stream() -> Stream:
    return Stream(fakes.tone_models())


@pytest.fixture(scope="module")
def verifier_run(stream: Stream) -> tuple[Any, list[tuple[float, str]]]:
    seen: list[tuple[float, str]] = []
    trained = train_verifier(
        _job(WakeArtifact.VERIFIER), stream, "e" * 64, fakes.ToneVoices(), _quiet(seen), now=NOW
    )
    return trained, seen


# ---- the logistic regression ------------------------------------------------------------------
def test_fit_reaches_sklearns_optimum_and_folds_the_scaler() -> None:
    rng = np.random.default_rng(1)
    x = rng.normal(0, 1, (400, 6)) * [1, 2, 3, 0.5, 1, 4] + [0, 1, -2, 0, 5, 0]
    y = (x[:, 0] - 0.5 * x[:, 2] + rng.normal(0, 0.5, 400) > 1).astype(float)
    c = 0.05
    w, b = fit_logistic(x, y, c)
    mean, scale = standardise(x)
    z = (x - mean) / scale
    theta = w * scale  # back to the standardised weights
    bias = b + float(np.sum(theta * mean / scale))
    p = 1 / (1 + np.exp(-(z @ theta + bias)))
    grad_w = c * z.T @ (p - y) + theta  # the objective's gradient is zero at its minimum
    grad_b = c * np.sum(p - y)
    assert np.max(np.abs(grad_w)) < 1e-6 and abs(grad_b) < 1e-6
    assert np.allclose(x @ w + b, z @ theta + bias)  # folded == scaled, for every example


def test_a_constant_feature_does_not_break_the_scaler() -> None:
    x = np.hstack([np.ones((50, 1)), np.linspace(-1, 1, 50)[:, None]])
    y = (x[:, 1] > 0).astype(float)
    w, b = fit_logistic(x, y)
    assert np.all(np.isfinite(w)) and math.isfinite(b)


# ---- stage 1 ----------------------------------------------------------------------------------
def test_held_out_clips_are_kept_apart_and_every_fifth_when_too_few() -> None:
    marked = split_wake(_job(WakeArtifact.VERIFIER, fakes.session_clips(wake=15)))
    assert len(marked.held) == 3 and not set(marked.held) & set(marked.train)
    none = split_wake(_job(WakeArtifact.VERIFIER, fakes.session_clips(wake=15, held_every=99)))
    assert len(none.held) == 1 + 2  # wake_00 held by held_every=99, then every 5th of the rest
    with pytest.raises(WakewordFailed, match="at least 10"):
        split_wake(_job(WakeArtifact.VERIFIER, fakes.session_clips(wake=8)))


def test_stage_1_learns_his_voice_and_rejects_other_speakers(
    verifier_run: tuple[Any, list[tuple[float, str]]], stream: Stream
) -> None:
    trained, seen = verifier_run
    v = VerifierFile.parse(trained.data)
    assert trained.info.artifact is WakeArtifact.VERIFIER
    assert trained.info.licence == OWNER_LICENCE and v.licence == OWNER_LICENCE
    assert trained.info.sha256 == formats.sha256_hex(trained.data)
    assert trained.info.beats_current is True
    assert trained.info.evals["miss_rate"] == 0.0 and trained.info.evals["other_reject"] >= 0.9
    assert trained.info.evals["today_other_reject"] < 0.5  # today's detector wakes for anyone
    assert v.embedding_sha256 == "e" * 64 and v.clips == 11
    mine, other = pad(fakes.tone(fakes.OWNER_HZ, 0.9, seed=77)), pad(fakes.tone(1450, 0.9))
    assert listen(stream, mine, verifier=v) == 1 and listen(stream, other, verifier=v) == 0
    assert listen(stream, other) == 1  # without the verifier the other speaker wakes it
    assert seen[-1][0] == 1.0 and all(0 <= f <= 1 for f, _ in seen)


def test_stage_1_is_deterministic(stream: Stream) -> None:
    def run() -> bytes:
        trained = train_verifier(
            _job(WakeArtifact.VERIFIER),
            stream,
            "e" * 64,
            fakes.ToneVoices(),
            lambda f, w: None,
            now=NOW,
        )
        return trained.data

    assert run() == run()


def test_stage_1_says_so_when_todays_detector_never_hears_him(stream: Stream) -> None:
    quiet = tuple(
        c.model_copy(update={"pcm": fakes.tone(fakes.OWNER_HZ, 0.9, amplitude=500)})
        if c.kind is PromptKind.WAKE
        else c
        for c in fakes.session_clips()
    )
    with pytest.raises(WakewordFailed, match="did not hear Hey Jarvis"):
        train_verifier(
            _job(WakeArtifact.VERIFIER, quiet), stream, "e" * 64, None, lambda f, w: None, now=NOW
        )


def test_without_voices_the_verifier_is_trained_but_not_applied(stream: Stream) -> None:
    trained = train_verifier(
        _job(WakeArtifact.VERIFIER), stream, "e" * 64, None, lambda f, w: None, now=NOW
    )
    assert trained.info.beats_current is False  # other speakers were not measured
    assert "other_reject" not in trained.info.evals


def test_other_speakers_keep_every_third_voice_for_the_test() -> None:
    train, test, notes = other_clips(fakes.ToneVoices())
    assert len(test) == 2 * 4 and len(train) == 4 * 4 and notes == []
    one_train, one_test, one_notes = other_clips(fakes.ToneVoices((1200.0,)))
    assert len(one_train) == 3 and len(one_test) == 1 and "one synthetic voice" in one_notes[0]
    assert other_clips(None)[2] == ["no synthetic voices: other speakers were not measured"]


# ---- the ONNX file ----------------------------------------------------------------------------
def _varint(b: bytes, i: int) -> tuple[int, int]:
    out = shift = 0
    while True:
        c = b[i]
        i += 1
        out |= (c & 0x7F) << shift
        shift += 7
        if c < 0x80:
            return out, i


def _fields(b: bytes) -> list[tuple[int, Any]]:
    out: list[tuple[int, Any]] = []
    i = 0
    while i < len(b):
        key, i = _varint(b, i)
        field, wire = key >> 3, key & 7
        value: Any
        if wire == 0:
            value, i = _varint(b, i)
        elif wire == 2:
            n, i = _varint(b, i)
            value, i = b[i : i + n], i + n
        else:
            raise AssertionError(f"unexpected wire type {wire}")
        out.append((field, value))
    return out


def _decode(model: bytes) -> dict[str, Any]:
    top = _fields(model)
    graph = dict(top)[7]
    g = _fields(graph)
    nodes = [
        dict((f, v) for f, v in _fields(n) if f in (3, 4))
        | {
            "in": [v.decode() for f, v in _fields(n) if f == 1],
            "attrs": [_fields(v) for f, v in _fields(n) if f == 5],
        }
        for f, n in g
        if f == 1
    ]
    inits = {}
    for f, t in g:
        if f == 5:
            tf = _fields(t)
            dims = [v for k, v in tf if k == 1]
            raw = dict(tf)[9]
            inits[dict(tf)[8].decode()] = np.frombuffer(raw, dtype="<f4").reshape(dims)
    return {"top": top, "nodes": nodes, "inits": inits, "graph": g}


def _layers(rng: Any, sizes: list[int]) -> list[Dense]:
    out = []
    for i, (a, b) in enumerate(zip(sizes, sizes[1:], strict=False)):
        act: Activation = "sigmoid" if i == len(sizes) - 2 else "relu"
        out.append(
            Dense(rng.normal(0, 0.05, a * b).tolist(), rng.normal(0, 0.1, b).tolist(), a, b, act)
        )
    return out


def test_the_onnx_file_is_the_consoles_format_and_computes_the_network() -> None:
    rng = np.random.default_rng(3)
    layers = _layers(rng, [formats.FEATURES, 8, 4, 1])
    data = mlp_onnx(layers, metadata={"licence": OWNER_LICENCE})
    d = _decode(data)
    top = dict(d["top"])
    assert top[1] == 7  # IR version, as today's model
    assert _fields(top[8]) == [(2, 13)]  # opset 13, default domain
    assert [n[4].decode() for n in d["nodes"]] == [
        "Flatten",
        "Gemm",
        "Relu",
        "Gemm",
        "Relu",
        "Gemm",
        "Sigmoid",
    ]
    io = {f: _fields(v) for f, v in d["graph"] if f in (11, 12)}
    assert dict(io[11])[1] == b"features" and dict(io[12])[1] == b"score"
    assert b"LicenseRef-Owner" in data
    x = rng.normal(0, 1, (1, formats.FRAMES, formats.DIM)).astype(np.float32)
    h = x.reshape(1, -1)
    for i, layer in enumerate(layers, start=1):
        w, b = d["inits"][f"dense{i}.weight"], d["inits"][f"dense{i}.bias"]
        assert w.shape == (layer.n_out, layer.n_in)  # PyTorch's layout, transB=1
        z = h @ w.T + b
        h = 1 / (1 + np.exp(-z)) if layer.activation == "sigmoid" else np.maximum(z, 0)
    want = x.reshape(1, -1)
    for layer in layers:
        w = np.array(layer.weight, dtype=np.float32).reshape(layer.n_out, layer.n_in)
        z = want @ w.T + np.array(layer.bias, dtype=np.float32)
        want = 1 / (1 + np.exp(-z)) if layer.activation == "sigmoid" else np.maximum(z, 0)
    assert float(h[0, 0]) == pytest.approx(float(want[0, 0]), abs=1e-6)


@pytest.mark.parametrize(
    "sizes,acts",
    [
        ([10, 1], ["sigmoid"]),
        ([formats.FEATURES, 2], ["sigmoid"]),
        ([formats.FEATURES, 4, 1], ["sigmoid", "sigmoid"]),
    ],
)
def test_the_writer_refuses_networks_the_console_cannot_run(
    sizes: list[int], acts: list[str]
) -> None:
    layers = [
        Dense([0.0] * (a * b), [0.0] * b, a, b, "sigmoid" if act == "sigmoid" else "relu")
        for (a, b), act in zip(zip(sizes, sizes[1:], strict=False), acts, strict=True)
    ]
    with pytest.raises(ValueError):
        mlp_onnx(layers)


def test_a_layer_must_match_its_shape_and_be_finite() -> None:
    with pytest.raises(ValueError, match="shape"):
        Dense([0.0] * 3, [0.0], 2, 1, "sigmoid")
    with pytest.raises(ValueError, match="finite"):
        Dense([math.nan, 0.0], [0.0], 2, 1, "sigmoid")
    assert struct.calcsize("<f") == 4


# ---- stage 2 ----------------------------------------------------------------------------------
def test_the_network_learns_and_its_folded_layers_are_its_maths() -> None:
    rng = np.random.default_rng(5)
    x = rng.normal(0, 1, (600, formats.FEATURES)).astype(np.float32)
    y = (x[:, 0] + x[:, 1] > 0).astype(np.float32)
    mlp = Mlp.fit(x, y, Recipe(hidden=8, epochs=15, batch=64))
    assert float(np.mean((mlp.predict(x) > 0.5) == (y > 0.5))) > 0.9
    h = x[:3]
    for layer in mlp.dense():
        w = np.array(layer.weight, dtype=np.float32).reshape(layer.n_out, layer.n_in)
        z = h @ w.T + np.array(layer.bias, dtype=np.float32)
        h = 1 / (1 + np.exp(-z)) if layer.activation == "sigmoid" else np.maximum(z, 0)
    assert np.allclose(h[:, 0], mlp.predict(x[:3]), atol=1e-4)
    with pytest.raises(ValueError, match="both kinds"):
        Mlp.fit(x, np.ones(600, dtype=np.float32), Recipe(hidden=4, epochs=1))


def test_the_phrase_end_is_its_last_loud_frame() -> None:
    clip = fakes.silence(1.28) + fakes.tone(fakes.OWNER_HZ, 0.64) + fakes.silence(1.28)
    assert phrase_end(clip) == 23  # frames 16..23 are loud
    assert phrase_end(fakes.silence(1)) is None and phrase_end(b"") is None


def test_stage_2_needs_two_voices() -> None:
    with pytest.raises(WakewordFailed, match="voices"):
        voicing(fakes.ToneVoices((1200.0,)))
    with pytest.raises(WakewordFailed, match="voices"):
        voicing(None)


def test_stage_2_trains_an_owned_model_that_beats_todays_on_synthetic_tv(stream: Stream) -> None:
    seen: list[tuple[float, str]] = []
    checks: list[int] = []
    trained = train_owned(
        _job(WakeArtifact.OWNED),
        stream,
        {formats.MEL_MODEL: "b" * 64},
        fakes.ToneVoices(),
        _quiet(seen),
        now=NOW,
        recipe=SMALL,
        check=lambda data: _counted(checks, data),
    )
    info = trained.info
    assert info.artifact is WakeArtifact.OWNED and info.licence == OWNER_LICENCE
    assert info.sha256 == formats.sha256_hex(trained.data) and info.size == len(trained.data)
    assert info.beats_current is True and info.evals["miss_rate"] == 0.0
    assert formats.manifest_sha256(trained.manifest) == info.sha256
    assert (
        "licence:   LicenseRef-Owner" in trained.manifest
        and "voice tone-1000 [MIT]" in trained.manifest
    )
    assert checks == [len(trained.data)]
    assert seen[-1] == (1.0, "Done: it beats today's model.")


def _counted(checks: list[int], data: bytes) -> Any:
    checks.append(len(data))
    return _numpy_runner(data)


def _numpy_runner(data: bytes) -> Any:
    d = _decode(data)
    layers = sorted(k for k in d["inits"] if k.endswith(".weight"))

    def run(x: Any) -> Any:
        h = np.asarray(x, dtype=np.float32).reshape(1, -1)
        for i in range(1, len(layers) + 1):
            z = h @ d["inits"][f"dense{i}.weight"].T + d["inits"][f"dense{i}.bias"]
            h = 1 / (1 + np.exp(-z)) if i == len(layers) else np.maximum(z, 0)
        return h

    return run


def test_stage_2_refuses_a_written_file_that_does_not_check_out(stream: Stream) -> None:
    with pytest.raises(WakewordFailed, match="did not check out"):
        train_owned(
            _job(WakeArtifact.OWNED),
            stream,
            {},
            fakes.ToneVoices(),
            lambda f, w: None,
            now=NOW,
            recipe=SMALL,
            check=lambda data: lambda x: np.array([[0.123]]),
        )


# ---- synthetic audio ---------------------------------------------------------------------------
def test_synthetic_sentences_never_say_the_wake_word() -> None:
    rng = np.random.default_rng(0)
    said = synth.sentences(rng, 300) + list(synth.NEAR_MISSES)
    assert not any("jarvis" in s.lower() for s in said)
    assert all("jarvis" in p.lower() for p in synth.WAKE_PHRASES)


def test_mixing_and_augmenting_keep_valid_16_bit_audio() -> None:
    rng = np.random.default_rng(0)
    clip = fakes.tone(fakes.OWNER_HZ, 0.5)
    noisy = synth.augment(clip, rng)
    assert len(noisy) % 2 == 0 and len(noisy) >= len(clip)
    for colour in ("white", "pink", "brown"):
        n = synth.noise(rng, 0.5, colour, 1000.0)
        assert float(np.sqrt(np.mean(n**2))) == pytest.approx(1000.0, rel=1e-6)
    speech = synth.as_float(clip)
    mixed = synth.as_float(synth.mix(speech, synth.noise(rng, 0.2, "white", 1.0), 20.0))
    residual = mixed - speech
    snr = 20 * np.log10(np.sqrt(np.mean(speech**2)) / np.sqrt(np.mean(residual**2)))
    assert snr == pytest.approx(20.0, abs=0.5)


def test_synthetic_tv_lasts_about_as_long_as_asked() -> None:
    rng = np.random.default_rng(0)
    pieces = list(synth.tv(fakes.ToneVoices(), ["tone-1000"], 20.0, rng))
    seconds = sum(len(p) for p in pieces) / 32_000
    assert 20.0 <= seconds < 40.0


def test_openly_licensed_sets_that_could_not_be_pinned_are_recorded_as_left_out() -> None:
    assert any("CC BY 4.0" in name for name in synth.LEFT_OUT)
    assert all("SHA-256" in why for why in synth.LEFT_OUT.values())
