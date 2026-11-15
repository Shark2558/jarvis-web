# tests/test_r13_d_assets.py -- R13 Part D (docs/plans/r13-wardrobe.md D8, M8): the wardrobe's
# three on-device models and their load-time self-checks.
#   - the manifest records a reference for EVERY task (I0 left face and person to D): embed's exact
#     output digest, face's top scores on the ramp and person's one detection on the drawn
#     silhouette, each with its tolerance; `scripts/wardrobe_assets.py manifest` writes exactly
#     that file from the pins without the network, and refuses a vendored file that differs
#   - the engine's own references (console-vision.js SELF13) are the manifest's
#   - in Node, on the VENDORED onnxruntime-web: each model's self-check input (the engine's own
#     SELFCHECK arithmetic) gives the manifest's reference; a drawn face fires UltraFace and a
#     drawn silhouette fires SSD's "person" through the engine's own decoders (WARDROBE-PURE); a
#     drawn striped shirt keeps its candidate under rotation and folding (INV-06's real half)
from __future__ import annotations

import importlib.util
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "src" / "jarvis" / "api" / "static"
R13_1 = STATIC / "vendor" / "vision" / "r13-1"
MODELS_JS = ROOT / "tests" / "fixtures" / "r13" / "models.mjs"


def _script() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "wardrobe_assets_d", ROOT / "scripts" / "wardrobe_assets.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _manifest() -> dict[str, Any]:
    out: dict[str, Any] = json.loads((R13_1 / "MANIFEST.json").read_text(encoding="utf-8"))
    return out


def test_every_wardrobe_model_has_its_self_check_reference() -> None:
    files = _manifest()["files"]
    embed = files["mobilenetv2-int8-embed.onnx"]["selfcheck"]
    assert embed["sha256"] == "e5b53d7e5bf35dda17217bb1feed42f900451b5fe1f2db3eca1f50442bf15abd"
    face = files["version-RFB-320.onnx"]["selfcheck"]
    assert face["input"] == "((i % 251) / 250) * 2 - 1 over float32[1, 3, 240, 320]"
    assert len(face["top"]) == 5 and face["tol"] == 0.002
    assert all(0.0 < v < 0.2 for v in face["top"]) and face["top"] == sorted(face["top"])[::-1]
    person = files["ssd_mobilenet_v1_12-int8.onnx"]["selfcheck"]
    assert "silhouette" in person["input"] and "uint8[1, 300, 300, 3]" in person["input"]
    assert person["class"] == 1 and 0.9 < person["score"] < 1.0 and person["tol"] == 0.03
    assert len(person["box"]) == 4 and all(0.0 <= v <= 1.0 for v in person["box"])


def test_the_script_writes_exactly_the_vendored_manifest() -> None:
    script = _script()
    assert script.problems() == []
    assert (R13_1 / "MANIFEST.json").read_bytes() == script.manifest_bytes(script.MODELS)


def test_the_manifest_command_refuses_a_vendored_file_that_differs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    script = _script()
    folder = tmp_path / "r13-1"
    folder.mkdir()
    for m in script.MODELS:
        (folder / m.name).write_bytes(b"not the model")
    monkeypatch.setattr(script, "FOLDER", folder)
    with pytest.raises(SystemExit, match="refused"):
        script.main(["manifest"])
    assert not (folder / "MANIFEST.json").exists()


def test_the_engines_references_are_the_manifests() -> None:
    js = (STATIC / "console-vision.js").read_text(encoding="utf-8")
    raw = js[js.index("/*SELF13-BEGIN*/") + len("/*SELF13-BEGIN*/") : js.index("/*SELF13-END*/")]
    got = json.loads(raw)
    files = _manifest()["files"]
    embed = files["mobilenetv2-int8-embed.onnx"]
    assert got["embed"] == {"sha256": embed["selfcheck"]["sha256"], "model": embed["model"]}
    face = files["version-RFB-320.onnx"]["selfcheck"]
    assert got["face"] == {"top": face["top"], "tol": face["tol"]}
    person = files["ssd_mobilenet_v1_12-int8.onnx"]["selfcheck"]
    want = {k: person[k] for k in ("class", "score", "box", "tol")}
    assert got["person"] == want
    assert re.search(r"const INT8_SCALE = 0\.019110053777694702;", js)


def _node(script: Path, *args: str) -> dict[str, Any]:
    node = shutil.which("node")
    if node is None:
        raise RuntimeError("node is not installed")
    run = subprocess.run(
        [node, str(script), *args], capture_output=True, text=True, timeout=240, check=False
    )
    if run.returncode != 0:
        raise AssertionError(run.stderr[-3000:])
    out: dict[str, Any] = json.loads(run.stdout.strip().splitlines()[-1])
    return out


@pytest.fixture(scope="module")
def real() -> dict[str, Any]:
    return _node(MODELS_JS, str(ROOT))


def test_the_real_models_reproduce_the_manifests_references(real: dict[str, Any]) -> None:
    assert real["selfcheck"] == {"embed": True, "face": True, "person": True}, real
    assert real["embed_dims"] == 1280 and real["embed_b64"] == 1708


def test_a_drawn_face_and_a_drawn_silhouette_are_found(real: dict[str, Any]) -> None:
    assert real["face"]["found"] is True and real["face"]["count"] == 1
    assert real["person"]["found"] is True and real["person"]["count"] >= 1
    assert real["clean_face"]["found"] is False and real["clean_person"]["found"] is False


def test_inv_06_a_striped_shirt_keeps_its_candidate_under_rotation_and_folding(
    real: dict[str, Any],
) -> None:
    for view in ("rotated", "folded", "back"):
        best = real["inv06"][view]
        assert best["top"] == "striped", (view, best)  # the same piece is candidate 1
        assert best["margin"] > 0.05, (view, best)  # ahead of the next piece
    assert real["inv06"]["other_top"] != "striped"
