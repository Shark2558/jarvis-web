# tests/test_r7_i1_book.py -- R7 I1 (INTEGRATION-B "Needs I1" 2 and 3): the build book knows Part
# B's vision libraries. `libs.VENDORED` gains zxing-cpp (Apache-2.0, the reader inside zxing-wasm's
# .wasm), and each vision library's version comes from the newest release's MANIFEST.json (its
# files' `source`); THIRD_PARTY.json names each vision file's licence from that MANIFEST (the
# licences sit one folder up), never "JARVIS's own".
from __future__ import annotations

import json
from pathlib import Path

from jarvis.buildbook.gen import libs, snapshot
from jarvis.buildbook.gen.repo import Repo

ROOT = Path(__file__).resolve().parents[1]
VISION = "src/jarvis/api/static/vendor/vision/"


def _repo() -> Repo:
    return Repo.from_git(ROOT)


def _manifest() -> dict:
    return json.loads((ROOT / VISION / "r7-1" / "MANIFEST.json").read_text(encoding="utf-8"))


def test_zxing_cpp_is_a_known_vendored_library() -> None:
    assert libs.VENDORED["vendor/vision/LICENSE-zxing-cpp.txt"][0] == "zxing-cpp"
    assert libs.VENDORED["vendor/vision/LICENSE-zxing-cpp.txt"][2:] == ("vendored", "vision")


def test_the_vision_libraries_carry_the_versions_their_manifest_records() -> None:
    found = {lib.name: lib for lib in libs.libraries(_repo(), lambda name: "MIT")}
    assert found["MediaPipe Tasks Vision"].version == "1.2.3"
    assert found["tesseract.js"].version == "7.0.0"
    assert found["tesseract.js-core"].version == "6.1.2"
    assert found["zxing-wasm"].version == "3.1.6"
    assert found["Tesseract English data"].version == "4.1.0"  # tessdata_fast's tag
    # zxing-cpp is inside zxing-wasm's reader: the manifest names no version of its own
    assert found["zxing-cpp"].version == "" and found["zxing-cpp"].licence == "Apache-2.0"
    assert found["MediaPipe Tasks Vision"].licence == "Apache-2.0"
    assert "MediaPipe pose and object models" not in found  # their licence has not arrived


def test_third_party_names_each_vision_files_licence_from_its_manifest() -> None:
    repo = _repo()
    files = _manifest()["files"]
    for name, entry in files.items():
        rel = f"{VISION}r7-1/{name}"
        want = libs.licence_from_text((ROOT / VISION / entry["licence"]).read_text("utf-8"))
        assert want != snapshot.OWN, name
        assert snapshot._licence(repo, rel) == want, name
    assert snapshot._licence(repo, f"{VISION}r7-1/zxing_reader.wasm") == "Apache-2.0"
    assert snapshot._licence(repo, f"{VISION}r7-1/zxing-reader.iife.js") == "MIT"
