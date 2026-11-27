# tests/test_r52_v1_device.py -- R5.2 V1 (plan risk 1): which device the kit uses, and how the
# runtime loaders call their libraries (stand-in modules: the real packages are on the laptop).
# No card, a card that doesn't answer, or "cpu" chosen: the CPU; int8 on the CPU, int8_float16 on
# the card; Kokoro on the card only when onnxruntime offers CUDA.
from __future__ import annotations

import subprocess
import sys
import types
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest

from jarvis.localspeech import device
from jarvis.localspeech.engines import LoadArgs
from jarvis.localspeech.kitconfig import default_dir, default_manifest
from jarvis.localspeech.protocol import Device
from jarvis.localspeech.runtimes import kokoro, whisper

SMI = "3512, 4096, NVIDIA GeForce RTX 3050 Laptop GPU\n"


def test_nvidia_smi_answers_are_read() -> None:
    found = device.parse_smi(SMI)
    assert found == device.DeviceInfo(Device.CUDA, 3512, 4096, "NVIDIA GeForce RTX 3050 Laptop GPU")
    assert device.parse_smi("") is None and device.parse_smi("n/a, n/a") is None
    assert device.parse_smi("-1, 4096") is None


def test_the_card_is_used_only_when_it_answers_and_is_allowed() -> None:
    def answers(args: Sequence[str]) -> str:
        assert list(args)[0] == "nvidia-smi"
        return SMI

    def missing(args: Sequence[str]) -> str:
        raise FileNotFoundError("nvidia-smi")

    def slow(args: Sequence[str]) -> str:
        raise subprocess.TimeoutExpired("nvidia-smi", 4)

    assert device.detect("auto", answers).device is Device.CUDA
    assert device.detect("cpu", answers).device is Device.CPU
    assert device.detect("auto", missing) == device.DeviceInfo(Device.CPU)
    assert device.detect("cuda", slow).device is Device.CPU
    assert device.gpu_free_mb(answers) == 3512 and device.gpu_free_mb(missing) is None


def test_free_memory_is_a_number() -> None:
    assert device.ram_free_mb() >= 0


def test_the_kit_folder_and_its_manifest() -> None:
    assert default_dir().name in ("LocalSpeech", ".jarvis-local-speech")
    assert (
        default_manifest()
        == Path(__file__).resolve().parents[1] / "deploy" / "local-speech" / "models.json"
    )


def _fake_module(monkeypatch: pytest.MonkeyPatch, name: str, **attrs: Any) -> None:
    module = types.ModuleType(name)
    for key, value in attrs.items():
        setattr(module, key, value)
    monkeypatch.setitem(sys.modules, name, module)


def test_whisper_loads_its_pinned_folder_int8_on_the_cpu(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: dict[str, Any] = {}

    class WhisperModel:
        def __init__(self, path: str, **kw: Any) -> None:
            seen.update(path=path, **kw)

    _fake_module(monkeypatch, "faster_whisper", WhisperModel=WhisperModel)
    engine = whisper.load(LoadArgs(tmp_path, Device.CPU, 3))
    assert isinstance(engine, whisper.WhisperEngine)
    assert seen == {
        "path": str(tmp_path),
        "device": "cpu",
        "compute_type": "int8",
        "cpu_threads": 3,
        "local_files_only": True,
    }
    whisper.load(LoadArgs(tmp_path, Device.CUDA, 3))
    assert seen["compute_type"] == "int8_float16" and seen["device"] == "cuda"


def test_kokoro_uses_the_card_only_when_onnxruntime_offers_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / kokoro.MODEL_FILE).write_bytes(b"onnx")
    (tmp_path / kokoro.VOICES_FILE).write_bytes(b"voices")
    sessions: list[list[str]] = []

    class SessionOptions:
        intra_op_num_threads = 0

    class InferenceSession:
        def __init__(self, path: str, sess_options: Any, providers: list[str]) -> None:
            sessions.append(providers)

    class Kokoro:
        @classmethod
        def from_session(cls, session: Any, voices: str) -> Any:
            return types.SimpleNamespace(get_voices=lambda: ["bm_george"])

    offered = {"providers": ["CPUExecutionProvider"]}
    _fake_module(
        monkeypatch,
        "onnxruntime",
        SessionOptions=SessionOptions,
        InferenceSession=InferenceSession,
        get_available_providers=lambda: offered["providers"],
    )
    _fake_module(monkeypatch, "kokoro_onnx", Kokoro=Kokoro)
    assert kokoro.load(LoadArgs(tmp_path, Device.CUDA, 2)).voices == {"bm_george"}
    offered["providers"] = ["CUDAExecutionProvider", "CPUExecutionProvider"]
    kokoro.load(LoadArgs(tmp_path, Device.CUDA, 2))
    kokoro.load(LoadArgs(tmp_path, Device.CPU, 2))
    assert sessions == [
        ["CPUExecutionProvider"],
        ["CUDAExecutionProvider", "CPUExecutionProvider"],
        ["CPUExecutionProvider"],
    ]
