# tests/test_r7_b_package.py -- R7 Part B (python review H1): the non-editable install the deploy
# uses must ship every vendored vision file, MANIFEST.json and the licences. The check reads
# pyproject's package-data globs the way setuptools does (a `*` never crosses a folder).
from __future__ import annotations

import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
API = ROOT / "src" / "jarvis" / "api"
VISION = API / "static" / "vendor" / "vision"


def shipped() -> set[Path]:
    cfg = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    globs = cfg["tool"]["setuptools"]["package-data"]["jarvis.api"]
    return {p for g in globs for p in API.glob(g) if p.is_file()}


def test_every_vendored_vision_file_is_in_the_package_data() -> None:
    on_disk = {p for p in VISION.rglob("*") if p.is_file()}
    assert on_disk, "the vendored vision folder is empty"
    assert on_disk - shipped() == set()


def test_the_manifest_and_the_licences_are_shipped() -> None:
    names = {p.relative_to(VISION).as_posix() for p in shipped() if VISION in p.parents}
    assert "r7-1/MANIFEST.json" in names
    assert {n for n in names if n.startswith("LICENSE-")} >= {
        "LICENSE-mediapipe-tasks-vision.txt",
        "LICENSE-tesseract.js.txt",
        "LICENSE-zxing-wasm.txt",
    }
