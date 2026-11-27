# tests/test_r52_v4_kit.py -- R5.2 V4 (row 83): the wake word's side of the kit server, as V1 calls
# it (`WakewordKit` from `build_wakeword`): checking a request, one training run at a time, the
# files sealed at rest and read back by hash, the stage 2 keep rule, delete, plain failures, and no
# model runtime loaded until a run starts.
from __future__ import annotations

import base64
import subprocess
import sys
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from jarvis.localspeech.protocol import (
    OWNER_LICENCE,
    ArtifactInfo,
    JobKind,
    KitRefused,
    WakeArtifact,
    WakeModelIn,
    WakeTrainIn,
)
from jarvis.localspeech.wakeword import RUNTIME_MODULES, WakewordKit, build_wakeword
from jarvis.localspeech.wakeword.formats import console_pins, sha256_hex
from jarvis.localspeech.wakeword.port import WakeClip, WakewordFailed
from jarvis.localspeech.wakeword.service import BUSY, FAILED, WakewordService
from jarvis.localspeech.wakeword.store import ArtifactStore

ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 11, 27, 10, 0, tzinfo=UTC)
SESSION = "vs_0123456789ab"


class Sealer:
    """Not encryption: a marker and a byte flip (the real one is V1's clip-store cipher)."""

    MARK = b"SEALED1:"

    def seal(self, data: bytes) -> bytes:
        return self.MARK + bytes(b ^ 0x5A for b in data)

    def unseal(self, data: bytes) -> bytes:
        if not data.startswith(self.MARK):
            raise ValueError("not sealed here")
        return bytes(b ^ 0x5A for b in data[len(self.MARK) :])


def _info(artifact: WakeArtifact, data: bytes, beats: bool | None = True) -> ArtifactInfo:
    return ArtifactInfo(
        artifact=artifact,
        sha256=sha256_hex(data),
        size=len(data),
        trained_at=NOW,
        licence=OWNER_LICENCE,
        beats_current=beats,
    )


def _clips(wake: int = 14) -> tuple[WakeClip, ...]:
    fakes = pytest.importorskip("jarvis.localspeech.wakeword.fakes")
    clips: tuple[WakeClip, ...] = fakes.session_clips(wake=wake)
    return clips


def _console() -> Any:
    fakes = pytest.importorskip("jarvis.localspeech.wakeword.fakes")
    runtime = pytest.importorskip("jarvis.localspeech.wakeword.runtime")
    shas = {"melspectrogram.onnx": "b" * 64, "embedding_model.onnx": "c" * 64}
    return runtime.ConsoleModels(
        features=fakes.tone_models(), shas=shas | {"hey_jarvis_v0.1.onnx": "d" * 64}
    )


def _service(tmp_path: Path, **over: Any) -> WakewordService:
    fakes = pytest.importorskip("jarvis.localspeech.wakeword.fakes")
    mlp = pytest.importorskip("jarvis.localspeech.wakeword.mlp")
    small = mlp.Recipe(hidden=16, epochs=6, copies=1, tv_train_s=15, tv_eval_s=20)
    kwargs: dict[str, Any] = {
        "sealer": Sealer(),
        "voices": fakes.ToneVoices(),
        "models": _console,
        "check": None,
        "recipe": small,
        "clock": lambda: NOW,
    }
    return WakewordService(tmp_path / "wake", **(kwargs | over))


# ---- the interface V1 calls --------------------------------------------------------------------
def test_build_wakeword_is_v1s_one_line_and_satisfies_the_interface(tmp_path: Path) -> None:
    wake: WakewordKit = build_wakeword(tmp_path / "w", sealer=Sealer())
    assert wake.job_kind(WakeArtifact.VERIFIER) is JobKind.VERIFIER
    assert wake.job_kind(WakeArtifact.OWNED) is JobKind.OWNED
    assert wake.status().verifier is None and wake.status().owned is None
    assert wake.delete() == 0
    assert (tmp_path / "w").stat().st_mode & 0o077 == 0  # the kit's folder is the owner's only


def test_prepare_needs_ten_hey_jarvis_clips_and_says_how_many(tmp_path: Path) -> None:
    wake = build_wakeword(tmp_path, sealer=Sealer())
    req = WakeTrainIn(artifact=WakeArtifact.VERIFIER, session_id=SESSION)
    with pytest.raises(KitRefused) as refused:
        wake.prepare(req, _clips(wake=6))
    assert refused.value.code == "not_found" and "that session has 6" in refused.value.words
    with pytest.raises(KitRefused, match="no recordings"):
        wake.prepare(req, ())
    job = wake.prepare(req, _clips())
    assert job.session_id == SESSION and len(job.clips) == 26


def test_one_run_at_a_time(tmp_path: Path) -> None:
    started, release = threading.Event(), threading.Event()

    def slow_models() -> Any:
        started.set()
        release.wait(5)
        raise WakewordFailed("stopped by the test")

    wake = _service(tmp_path, models=slow_models)
    req = WakeTrainIn(artifact=WakeArtifact.VERIFIER, session_id=SESSION)
    job = wake.prepare(req, _clips())
    errors: list[str] = []
    worker = threading.Thread(target=lambda: _capture(wake, job, errors))
    worker.start()
    assert started.wait(5)
    with pytest.raises(KitRefused) as busy:
        wake.prepare(req, _clips())
    assert busy.value.code == "busy" and busy.value.words == BUSY
    with pytest.raises(WakewordFailed, match="already training"):
        wake.train(job, lambda f, w: None)
    release.set()
    worker.join(5)
    assert errors == ["stopped by the test"]
    assert wake.prepare(req, _clips()).artifact is WakeArtifact.VERIFIER  # free again


def _capture(wake: WakewordService, job: Any, errors: list[str]) -> None:
    try:
        wake.train(job, lambda f, w: None)
    except WakewordFailed as exc:
        errors.append(exc.words)


def test_an_unexpected_error_fails_the_job_in_fixed_words(tmp_path: Path) -> None:
    def broken() -> Any:
        raise RuntimeError("audio bytes and a secret path")

    wake = _service(tmp_path, models=broken)
    job = wake.prepare(WakeTrainIn(artifact=WakeArtifact.OWNED, session_id=SESSION), _clips())
    with pytest.raises(WakewordFailed) as failed:
        wake.train(job, lambda f, w: None)
    assert failed.value.words == FAILED and "secret" not in failed.value.words


# ---- training through the service --------------------------------------------------------------
def test_stage_1_through_the_service_is_stored_sealed_and_served_by_hash(tmp_path: Path) -> None:
    wake = _service(tmp_path)
    job = wake.prepare(WakeTrainIn(artifact=WakeArtifact.VERIFIER, session_id=SESSION), _clips())
    steps: list[float] = []
    info = wake.train(job, lambda f, w: steps.append(f))
    assert info.beats_current is True and steps[0] == 0.0 and steps[-1] == 1.0
    assert wake.status().verifier == info and wake.status().owned is None
    sealed = (tmp_path / "wake" / "wakeword-verifier.sealed").read_bytes()
    assert sealed.startswith(Sealer.MARK) and b"jarvis-wake-verifier" not in sealed
    model = wake.model(WakeModelIn(artifact=WakeArtifact.VERIFIER))
    assert model.format == "json" and model.licence == OWNER_LICENCE
    assert model.sha256 == info.sha256 and sha256_hex(model.data_bytes()) == info.sha256
    with pytest.raises(KitRefused) as missing:
        wake.model(WakeModelIn(artifact=WakeArtifact.OWNED))
    assert missing.value.code == "not_found"
    assert wake.delete() == 1 and wake.status().verifier is None


def test_stage_2_through_the_service_keeps_its_manifest(tmp_path: Path) -> None:
    wake = _service(tmp_path)
    job = wake.prepare(WakeTrainIn(artifact=WakeArtifact.OWNED, session_id=SESSION), _clips())
    info = wake.train(job, lambda f, w: None)
    model = wake.model(WakeModelIn(artifact=WakeArtifact.OWNED))
    assert model.format == "onnx" and model.sha256 == info.sha256
    assert f"sha256 {info.sha256} {info.size} hey_jarvis_owned.onnx" in model.manifest
    assert "melspectrogram.onnx" in model.manifest and "LicenseRef-Owner" in model.manifest


def test_a_worse_owned_model_never_replaces_one_that_beat_todays(tmp_path: Path) -> None:
    wake = _service(tmp_path)
    good = b"good model bytes"
    wake.store.put(good, _info(WakeArtifact.OWNED, good, beats=True))
    job = wake.prepare(WakeTrainIn(artifact=WakeArtifact.OWNED, session_id=SESSION), _clips())
    worse = _service(tmp_path, recipe=_never_beats())
    words: list[str] = []
    info = worse.train(job, lambda f, w: words.append(w))
    assert info.beats_current is False
    kept = worse.status().owned
    assert kept is not None and kept.sha256 == sha256_hex(good)
    assert words[-1] == "Done: your earlier model stays (it did better)."


def _never_beats() -> Any:
    mlp = pytest.importorskip("jarvis.localspeech.wakeword.mlp")
    return mlp.Recipe(hidden=2, epochs=0, copies=0, tv_train_s=1, tv_eval_s=20)  # untrained


# ---- the store ---------------------------------------------------------------------------------
def test_a_tampered_or_foreign_file_reads_as_missing(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path, Sealer())
    data = b'{"weights": []}'
    store.put(data, _info(WakeArtifact.VERIFIER, data))
    assert store.get(WakeArtifact.VERIFIER) is not None
    path = tmp_path / "wakeword-verifier.sealed"
    path.write_bytes(path.read_bytes()[:-3] + b"xyz")
    assert store.get(WakeArtifact.VERIFIER) is None
    path.write_bytes(b"plain, not sealed")
    assert store.get(WakeArtifact.VERIFIER) is None
    with pytest.raises(ValueError, match="does not match"):
        store.put(b"other", _info(WakeArtifact.VERIFIER, data))


def test_a_record_for_the_other_artifact_is_refused(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path, Sealer())
    data = b"x"
    store.put(data, _info(WakeArtifact.OWNED, data))
    (tmp_path / "wakeword-owned.sealed").rename(tmp_path / "wakeword-verifier.sealed")
    assert store.get(WakeArtifact.VERIFIER) is None
    assert base64.b64encode(data)  # nothing else to check: it never reaches the console


# ---- the runtime: pinned files, lazy imports ----------------------------------------------------
def test_the_kit_reads_the_consoles_files_only_by_their_pinned_hashes() -> None:
    runtime = pytest.importorskip("jarvis.localspeech.wakeword.runtime")
    folder = runtime.CONSOLE_MODELS
    pins = console_pins(folder)
    for name in ("melspectrogram.onnx", "embedding_model.onnx", "hey_jarvis_v0.1.onnx"):
        assert sha256_hex(runtime.verified(folder, name, pins)) == pins[name]
    with pytest.raises(WakewordFailed, match="differs from the pinned file"):
        runtime.verified(folder, "hey_jarvis_v0.1.onnx", pins | {"hey_jarvis_v0.1.onnx": "0" * 64})


def test_a_kit_without_onnxruntime_says_so_in_plain_words() -> None:
    runtime = pytest.importorskip("jarvis.localspeech.wakeword.runtime")
    try:
        import onnxruntime  # noqa: F401
    except ImportError:
        with pytest.raises(WakewordFailed, match="onnxruntime"):
            runtime.onnx_runner(b"")
    else:
        pytest.skip("onnxruntime is installed here")


def test_the_light_modules_load_no_model_runtime() -> None:
    code = (
        "import sys\n"
        "import jarvis.localspeech.wakeword, jarvis.localspeech.wakeword.service\n"
        "import jarvis.localspeech.wakeword.formats, jarvis.localspeech.wakeword.evals\n"
        "import jarvis.localspeech.wakeword.store, jarvis.localspeech.wakeword.port\n"
        "bad = [m for m in ('numpy', 'onnxruntime', 'openwakeword') if m in sys.modules]\n"
        "kit = [m for m in sys.modules if m in jarvis.localspeech.wakeword.RUNTIME_MODULES]\n"
        "print(bad, kit)\n"
    )
    out = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        check=True,
        env={"PYTHONPATH": str(ROOT / "src")},
        timeout=60,
    )
    assert out.stdout.strip() == "[] []"
    assert "jarvis.localspeech.wakeword.streaming" in RUNTIME_MODULES
