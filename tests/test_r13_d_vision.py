# tests/test_r13_d_vision.py -- R13 Part D (docs/plans/r13-wardrobe.md D7-D9): the wardrobe's four
# vision tasks in console-vision.js's Part B section.
#   - the colour list is the server's (jarvis.vision.results.COLOUR_NAMES), in its order
#   - the engine's pure arithmetic, run as it is in Node (tests/fixtures/r13/pure.mjs): every named
#     colour reads as itself; half navy and half white is "multicolour" naming the larger; mostly
#     navy is navy; UltraFace's boxes pass NMS (two overlapping faces are one); SSD's boxes are
#     read ymin-xmin-ymax-xmax, only class 1 at >= 0.5, only `count` of them; a fingerprint is
#     1,708 base64 characters; the fp32 fallback quantizes with the int8 scale, clamped to a byte
#   - the four tasks' checks are the server's schemas (WARDROBE_DATA): a well-formed result of each
#     passes jarvis.vision.results.parse_result(wardrobe=True), the shapes the tasks return
#   - each wardrobe model loads only through its self-check; a mismatch is "not installed"
from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest

from jarvis.vision.results import COLOUR_NAMES, parse_result

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "src" / "jarvis" / "api" / "static"
VISION = (STATIC / "console-vision.js").read_text(encoding="utf-8")
PART_D = VISION[VISION.index("// ==== R13 Part D") : VISION.index("sealRegistry();\n")]


@pytest.fixture(scope="module")
def pure() -> dict[str, Any]:
    node = shutil.which("node")
    if node is None:
        raise RuntimeError("node is not installed")
    run = subprocess.run(
        [node, str(ROOT / "tests" / "fixtures" / "r13" / "pure.mjs"), str(ROOT)],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert run.returncode == 0, run.stderr[-2000:]
    out: dict[str, Any] = json.loads(run.stdout.strip().splitlines()[-1])
    return out


def test_the_colour_list_is_the_servers(pure: dict[str, Any]) -> None:
    assert tuple(pure["names"]) == COLOUR_NAMES


def test_every_named_colour_reads_as_itself(pure: dict[str, Any]) -> None:
    assert pure["colours"] == {name: name for name in COLOUR_NAMES}
    assert pure["white"] == {"name": "white", "share": 1}
    assert pure["empty"] == {"name": "grey", "share": 0}


def test_two_colours_half_and_half_are_multicolour_and_mostly_one_is_that_one(
    pure: dict[str, Any],
) -> None:
    stripes = pure["stripes"]
    assert stripes["name"] == "multicolour" and stripes["second"] in ("navy", "white")
    assert 0.45 <= stripes["share"] <= 0.55
    assert pure["mostly_navy"]["name"] == "navy" and "second" not in pure["mostly_navy"]


def test_the_face_boxes_pass_nms_and_the_cap(pure: dict[str, Any]) -> None:
    faces = pure["faces"]
    assert faces["found"] is True and faces["count"] == 2  # the overlapping pair is one face
    assert faces["boxes"][0] == {"x": 0.1, "y": 0.1, "w": 0.2, "h": 0.3}  # the best first
    assert faces["boxes"][1] == {"x": 0.6, "y": 0.5, "w": 0.2, "h": 0.3}
    assert pure["faces_max1"] == 1


def test_the_person_boxes_are_class_one_above_half_in_tf_order(pure: dict[str, Any]) -> None:
    people = pure["people"]
    assert people["count"] == 2  # class 37 and the 0.49 one are not people
    assert people["boxes"][0] == {"x": 0.2, "y": 0.1, "w": 0.4, "h": 0.8}
    assert people["boxes"][1] == {"x": 0.05, "y": 0.5, "w": 0.2, "h": 0.2}
    assert pure["people_count2"] == 1  # only `count` detections are read


def test_a_fingerprint_is_1708_characters_and_the_fallback_quantizes(pure: dict[str, Any]) -> None:
    assert pure["b64"] == "AP8BAg==" and pure["b64_len"] == 1708
    assert pure["quantized"] == [0, 0, 0, 1, 52, 255]


def test_the_self_check_inputs_are_fixed_arithmetic(pure: dict[str, Any]) -> None:
    assert pure["ramp"] == [-1, -0.992, -0.984, -1]  # (i % 251) / 250 * 2 - 1
    assert pure["silhouette"] == {"bytes": 270_000, "sky": [190, 210, 235], "ink": [35, 30, 30]}
    assert pure["chw"] == [2.249, -2.036, -1.804]  # (v / 255 - mean) / std, ImageNet's


def _result(task: str, data: dict[str, Any]) -> dict[str, Any]:
    return {
        "task": task,
        "v": 1,
        "at": 1763280000,
        "ms": 120,
        "device": "phone",
        "ok": True,
        "data": data,
        "quality": {"light": 0.5, "sharp": 0.4},
    }


def test_the_shapes_the_tasks_return_are_the_servers(pure: dict[str, Any]) -> None:
    assert parse_result(_result("colour", pure["stripes"]), wardrobe=True) is not None
    assert parse_result(_result("colour", pure["white"]), wardrobe=True) is not None
    assert parse_result(_result("face", pure["faces"]), wardrobe=True) is not None
    assert parse_result(_result("person", pure["people"]), wardrobe=True) is not None
    embed = {"v": "A" * 1708, "dims": 1280, "model": "mnv2-int8-1"}
    assert parse_result(_result("embed", embed), wardrobe=True) is not None


def test_the_checks_hold_the_tasks_to_those_shapes() -> None:
    checks = PART_D[PART_D.index("const CHECKS13 = {") : PART_D.index("// ---- one runtime")]
    assert "d.v.length === EMBED_B64 && B64.test(d.v)" in checks
    assert "d.dims === EMBED_DIMS && EMBED_MODELS.includes(d.model)" in checks
    assert "COLOUR_NAMES.includes(d.name) || d.name === 'multicolour'" in checks
    assert "person: foundOk" in checks and "face: foundOk" in checks
    assert "d.count <= BOXES_MAX" in PART_D and "BOXES_MAX = 20" in PART_D
    assert "PERSON_MIN = 0.5, FACE_MIN = 0.7, NMS_IOU = 0.3" in PART_D


def test_each_model_is_kept_only_after_its_self_check() -> None:
    start, end = PART_D.index("async function open13("), PART_D.index("async function sha256hex")
    body = PART_D[start:end]
    refuse = "if (!ok) { try { await s.release(); } catch (_) {} throw new Error(NOT_INSTALLED); }"
    assert refuse in body and "sessions[id] = { o, s };" in body
    assert body.index("if (!ok)") < body.index("sessions[id]")
    models = (("embed", "EMBED_MODEL"), ("person", "PERSON_MODEL"), ("face", "FACE_MODEL"))
    for task, model in models:
        assert f"load: guard(() => open13('{task}', {model}, CHECKS_AT_LOAD.{task}))" in PART_D
    assert "if (!(crypto && crypto.subtle)) return '';" in PART_D  # no digest: fails closed
    assert "logSeverityLevel: 3" in PART_D  # UltraFace's initializer warnings stay off the console
    assert "window.addEventListener('pagehide', unload13);" in PART_D


def test_the_part_d_section_keeps_the_engines_house_rules() -> None:
    assert VISION.isascii() and len(VISION.splitlines()) <= 800
    for bad in ("innerHTML", "eval(", "new Function", "console.log", "localStorage", "indexedDB"):
        assert bad not in PART_D, bad
    assert not re.search(r"https?://", PART_D)
