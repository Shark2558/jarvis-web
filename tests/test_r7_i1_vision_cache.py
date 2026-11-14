# tests/test_r7_i1_vision_cache.py -- R7 I1 (INTEGRATION-B "Needs I1" 12): `api/console.py`'s
# `vision_files` is checked again whenever the release folder changes on disk (each entry's
# `(mtime_ns, size)`, MANIFEST.json's too), so models pinned later are served with no restart and a
# file swapped after the first look is never served unchecked; an unchanged folder is not hashed
# again on every request.
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

import pytest

from jarvis.api import console

RELEASE = "r9-test"
JS = "application/javascript"


def _write(folder: Path, files: dict[str, bytes]) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    listed = {}
    for name, data in files.items():
        (folder / name).write_bytes(data)
        listed[name] = {"sha256": hashlib.sha256(data).hexdigest(), "type": JS}
    (folder / "MANIFEST.json").write_text(json.dumps({"files": listed}), encoding="utf-8")


@pytest.fixture
def vision(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Any:
    monkeypatch.setattr(console, "_VISION", tmp_path)
    console.vision_files.cache_clear()
    yield tmp_path / RELEASE
    console.vision_files.cache_clear()


def _bump(path: Path) -> None:
    """A later write: the clock may not move between two writes in a test, so move it."""
    st = path.stat()
    os.utime(path, ns=(st.st_atime_ns, st.st_mtime_ns + 1_000_000))


def test_a_model_pinned_later_is_served_without_a_restart(vision: Path) -> None:
    _write(vision, {"engine.js": b"// the engine"})
    assert console.vision_files(RELEASE) == {"engine.js": JS}
    _write(vision, {"engine.js": b"// the engine", "pose.js": b"// the pose model's loader"})
    _bump(vision / "MANIFEST.json")
    assert console.vision_files(RELEASE) == {"engine.js": JS, "pose.js": JS}


def test_a_file_swapped_after_the_first_look_is_never_served_unchecked(vision: Path) -> None:
    _write(vision, {"engine.js": b"// the engine"})
    assert "engine.js" in console.vision_files(RELEASE)
    (vision / "engine.js").write_bytes(b"// something else, same name")
    _bump(vision / "engine.js")
    assert "engine.js" not in console.vision_files(RELEASE)


def test_an_unchanged_folder_is_not_hashed_again(
    vision: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write(vision, {"engine.js": b"// the engine", "worker.js": b"// a worker"})
    assert len(console.vision_files(RELEASE)) == 2
    calls: list[int] = []
    real = hashlib.sha256

    def counting(data: bytes = b"") -> Any:
        calls.append(1)
        return real(data)

    monkeypatch.setattr(console.hashlib, "sha256", counting)
    for _ in range(5):
        assert len(console.vision_files(RELEASE)) == 2
    assert calls == []


def test_a_missing_release_or_manifest_serves_nothing(vision: Path) -> None:
    assert console.vision_files(RELEASE) == {}
    vision.mkdir(parents=True)
    (vision / "engine.js").write_bytes(b"// no manifest")
    assert console.vision_files(RELEASE) == {}
