# tests/test_r8_a_assets.py -- R8 builder A, row 216 (docs/plans/r8-vision.md 4.2, 4.11, 4.12, D4,
# D8, D9; ADR-50): the model pins. The browser compares every model file's bytes with the SUMS8
# block of console-vision-r8.js, which `scripts/vision_assets.py sums` fills from the manifests and
# `check` holds equal to them; pinning r7-1 and r8-1 in either order keeps both manifests' licence
# sums true; a model whose storage address fails comes from its model page's address; the object
# model's licence is still to be read (D9's fallback serves `objects`); the CI job ships SUMS8.
# Fake downloads only: this workspace can't reach the model hosts, and nothing here is a model.
from __future__ import annotations

import hashlib
import importlib.util
import json
import re
import shutil
import sys
from pathlib import Path
from types import ModuleType

import pytest

from jarvis.vision import assets

ROOT = Path(__file__).resolve().parents[1]
FAKE = {
    assets.POSE_MODEL: b"FAKE pose lite",
    assets.OBJECT_MODEL: b"FAKE object model",
    assets.HAND_MODEL: b"FAKE hand",
    assets.POSE_FULL_MODEL: b"FAKE pose full",
}


def _script() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "vision_assets_r8a", ROOT / "scripts" / "vision_assets.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # a dataclass module must be importable by its own name
    spec.loader.exec_module(module)
    return module


def _fake(url: str) -> bytes:
    return FAKE[url.rsplit("/", 1)[-1].replace("efficientdet_lite0_int8", "efficientdet_lite0")]


def _copy(tmp_path: Path) -> tuple[Path, Path]:
    folder = tmp_path / "vision"
    shutil.copytree(assets.FOLDER, folder)
    js = tmp_path / "console-vision-r8.js"
    shutil.copy(assets.R8_JS, js)
    return folder, js


def _pin(va: ModuleType, folder: Path, release: str, licence: str | None) -> None:
    files = dict(json.loads((folder / release / "MANIFEST.json").read_text())["files"])
    files.update(va.fetch_models(folder, release, licence, fetch=_fake))
    va.write_manifest(folder, release, files)


# ---- the SUMS8 block -----------------------------------------------------------------------------
def test_the_shipped_sums_block_equals_the_manifests() -> None:
    va = _script()
    assert va.read_sums(assets.R8_JS) == va.pinned_sums(assets.FOLDER) == {}  # none pinned yet
    assert va.sums_problems(assets.FOLDER, assets.R8_JS) == []
    assert va.main(["check"]) == 0 and va.main(["check", "--release", "r8-1"]) == 0


def test_sums_writes_the_pins_and_check_holds_the_block_to_them(tmp_path: Path) -> None:
    va = _script()
    folder, js = _copy(tmp_path)
    _pin(va, folder, assets.RELEASE, None)
    _pin(va, folder, assets.R8_RELEASE, None)
    assert va.sums_problems(folder, js) != []  # pinned, but the block is still empty
    assert va.main(["check", "--folder", str(folder), "--js", str(js)]) == 1
    assert va.main(["sums", "--folder", str(folder), "--js", str(js)]) == 0
    want = {
        f"r7-1/{assets.POSE_MODEL}": hashlib.sha256(FAKE[assets.POSE_MODEL]).hexdigest(),
        f"r8-1/{assets.HAND_MODEL}": hashlib.sha256(FAKE[assets.HAND_MODEL]).hexdigest(),
        f"r8-1/{assets.POSE_FULL_MODEL}": hashlib.sha256(FAKE[assets.POSE_FULL_MODEL]).hexdigest(),
    }
    assert va.read_sums(js) == want
    assert va.main(["check", "--folder", str(folder), "--js", str(js)]) == 0
    assert va.main(["check", "--release", "r8-1", "--folder", str(folder), "--js", str(js)]) == 0
    text = js.read_text(encoding="utf-8")
    assert (
        text.isascii()
        and text.replace(json.dumps(want, sort_keys=True), "{}") == assets.R8_JS.read_text()
    )
    js.write_text(text.replace(want[f"r8-1/{assets.HAND_MODEL}"], "0" * 64), encoding="utf-8")
    assert va.sums_problems(folder, js) == [
        "console-vision-r8.js: its SUMS8 block differs from the manifests (run `sums`)"
    ]
    js.write_text("export const nothing = 1;\n", encoding="utf-8")
    assert "missing or unreadable" in va.sums_problems(folder, js)[0]
    with pytest.raises(SystemExit, match="no SUMS8 block"):
        va.write_sums(folder, js)


def test_the_browser_compares_every_model_with_sums8_before_use() -> None:
    js = assets.R8_JS.read_text(encoding="utf-8")
    body = js[js.index("async function pinned(") : js.index("function stamp(")]
    assert (
        "if (!want || (await kit.sha256hex(bytes)) !== want) throw new Error(kit.NOT_INSTALLED);"
        in body
    )
    for load in (
        "kit.model(kit.POSE_MODEL)",
        "kit.model8(kit.POSE_FULL_MODEL)",
        "kit.model8(kit.HAND_MODEL)",
    ):
        assert "await pinned(kit, " in js and load in js
        assert re.search(r"pinned\(kit, R[78], kit\.\w+, await " + re.escape(load) + r"\)", js), (
            load
        )


# ---- pinning in either order; the mirrors -------------------------------------------------------
@pytest.mark.parametrize("order", [("r7-1", "r8-1"), ("r8-1", "r7-1")])
def test_pinning_both_releases_in_either_order_keeps_every_licence_sum(
    tmp_path: Path, order: tuple[str, str]
) -> None:
    va = _script()
    folder, _ = _copy(tmp_path)
    for release in order:
        _pin(va, folder, release, "Apache-2.0")  # the workflow passes the same licence to both
    assert va.check(folder, assets.RELEASE) == [] and va.check(folder, assets.R8_RELEASE) == []
    plain, _ = _copy(tmp_path / "without")  # and with no object licence at all
    for release in order:
        _pin(va, plain, release, None)
    assert va.check(plain, assets.RELEASE) == [] and va.check(plain, assets.R8_RELEASE) == []
    words = (folder / va.MODELS_LICENCE).read_text(encoding="utf-8")
    for name in (*FAKE,):
        assert f"{name}: Apache-2.0 (from https://storage.googleapis.com/" in words, name


def test_a_failed_storage_address_falls_back_to_the_model_pages_address(tmp_path: Path) -> None:
    va = _script()
    folder, _ = _copy(tmp_path)
    asked: list[str] = []

    def storage_down(url: str) -> bytes:
        asked.append(url)
        if url.startswith("https://storage.googleapis.com/"):
            raise SystemExit(f"could not fetch {url}: HTTP Error 403")
        return _fake(url)

    files = va.fetch_models(folder, assets.R8_RELEASE, None, fetch=storage_down)
    assert files[assets.HAND_MODEL]["source"].startswith("https://huggingface.co/litert-community/")
    assert len(asked) == 4  # each model: its storage address, then its page's
    plain = va.Source("model", url="https://storage.googleapis.com/x/y.task", name="y.task")
    with pytest.raises(SystemExit, match="403"):
        va.fetch_model(plain, storage_down)  # no mirror: the failure is said


def test_every_model_names_the_page_that_gave_its_addresses() -> None:
    va = _script()
    models = [s for s in va.SOURCES if s.kind == "model"]
    assert {s.name for s in models} == set(FAKE)
    for s in models:
        assert s.url.startswith("https://storage.googleapis.com/mediapipe-models/"), s.name
        assert s.mirror.startswith("https://huggingface.co/litert-community/MediaPipe-"), s.name
        assert s.page.startswith(
            "https://developers.google.com/edge/mediapipe/solutions/vision/"
        ), s.name
    for release in (assets.RELEASE, assets.R8_RELEASE):
        doc = json.loads((assets.FOLDER / release / "MANIFEST.json").read_text(encoding="utf-8"))
        assert doc["models"] == va._pending_models(doc["files"], release), release


def test_the_object_models_licence_is_still_to_be_read_and_says_why() -> None:
    va = _script()
    doc = json.loads((assets.FOLDER / assets.RELEASE / "MANIFEST.json").read_text(encoding="utf-8"))
    entry = doc["models"][assets.OBJECT_MODEL]
    assert (
        entry["licence"] == "to be read"
        and "D9's fallback (SSD-MobileNet v1" in entry["licence_note"]
    )
    assert "links no model card" in entry["licence_note"]
    assert [s.name for s in va.plan_models(None)] == [assets.POSE_MODEL]  # never fetched unread


# ---- what the server says is installed ----------------------------------------------------------
def test_installed_answers_digits_and_which_pose_model() -> None:
    r7 = {n: "x" for n in (*assets.MEDIAPIPE, assets.POSE_MODEL)}
    assert "digits" not in assets.installed(r7)  # R7's answer unchanged without r8-1
    assert assets.installed(r7, None, {})["digits"] is True  # segment arithmetic: no file
    assert (
        assets.why("digits", r7, None, {}) == ""
        and assets.why("hands", r7, None, {}) == "not installed"
    )
    assert assets.why("hands", r7, None, {assets.HAND_MODEL: "x"}) == ""
    assert assets.pose_model(r7) == "lite" and assets.pose_model(r7, {}) == "lite"
    assert assets.pose_model(r7, {assets.POSE_FULL_MODEL: "x"}) == "full"
    assert assets.pose_model({}, {assets.POSE_FULL_MODEL: "x"}) == ""  # no MediaPipe runtime
    assert assets.pose_model({n: "x" for n in assets.MEDIAPIPE}) == ""  # no pose model at all


# ---- the CI job ---------------------------------------------------------------------------------
def test_the_workflow_fills_sums8_on_a_copy_checks_it_and_ships_it() -> None:
    wf = (ROOT / ".github" / "workflows" / "vision-models.yml").read_text(encoding="utf-8")
    assert "src/jarvis/api/static/console-vision-r8.js" in wf.split("permissions:")[0]  # a trigger
    sums = wf.index(
        "vision_assets.py sums --folder /tmp/vision-one --js /tmp/vision-one/console-vision-r8.js"
    )
    check = wf.index(
        "vision_assets.py check --folder /tmp/vision-one --js /tmp/vision-one/console-vision-r8.js"
    )
    assert wf.index("for run in one two; do") < sums < check
    assert wf.rstrip().endswith("/tmp/vision-one/console-vision-r8.js")  # in the 7-day artifact
    assert re.search(r"^permissions:\n  contents: read$", wf, re.M) and "secrets." not in wf
    for use in re.findall(r"uses: (\S+)", wf):
        assert re.fullmatch(r"[\w./-]+@[0-9a-f]{40}", use), use
