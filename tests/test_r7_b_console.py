# tests/test_r7_b_console.py -- R7 Part B, static checks of the console's camera files
# (docs/plans/r7-mobile.md D0, D11-D14; I0 seams 8, 13, 25):
#   - only console-camera.js asks for a camera (beside the microphone's file), and only it owns the
#     camera-off key; its "cameras off" phrases are R7_PHRASES's, and it registers through R5's one
#     router; nothing has a voice word that turns a camera on
#   - D13: a use case may use none of drawImage ... the storage APIs; the guard catches each of them
#     (and the ways around them), passes a clean use case, and today no use case module exists
#   - the engine's port core is I0's, byte for byte; the tasks load only JARVIS's own files (the
#     release of jarvis.vision.assets, tesseract's worker not from a blob, no CDN, no IndexedDB
#     cache); their label lists are the server schema's
#   - the panel sends a picture only through I0's one door, asks only /v1/vision, and its strings
#     reach the page by textContent; the stylesheet only places things (<= 150 lines)
from __future__ import annotations

import hashlib
import re

import pytest
from r7_fakes_b import CLEAN_USE_CASE, D13_APIS, STATIC, use_case_modules, use_case_problems

from jarvis.vision import assets
from jarvis.vision.results import CODE_FORMATS, OBJECT_LABELS
from jarvis.voice.commands import COMMAND_HINTS, R7_PHRASES

CAMERA, VISION, PANEL, CSS = (
    "console-camera.js",
    "console-vision.js",
    "console-camera-panel.js",
    "console-camera.css",
)
I0_CORE_SHA256 = "9e5ae773787d1121ae76568ed4995e31a68b0e13735902045b8e1f02b68c82c6"
PART_B = "\n// ==== R7 Part B"


def read(name: str) -> str:
    return (STATIC / name).read_text(encoding="utf-8")


def between(text: str, begin: str, end: str) -> str:
    return text[text.index(begin) + len(begin) : text.index(end)]


# ---- the camera's one door -----------------------------------------------------------------------
def test_only_the_camera_door_asks_for_a_camera() -> None:
    asks = re.compile(r"getUserMedia|getDisplayMedia|ImageCapture|facingMode|mediaDevices\s*\[")
    for path in sorted(STATIC.glob("*.js")):
        if path.name in (CAMERA, "console-voice-capture.js", "console-voice-devices.js"):
            continue
        assert not asks.search(path.read_text(encoding="utf-8")), path.name
    cam = read(CAMERA)
    assert cam.count("getUserMedia(") == 1 and "audio: false" in cam
    devices = read("console-voice-devices.js")
    assert "getUserMedia(" not in devices and "video" not in re.findall(
        r"kind === '(\w+)'", devices
    )


def test_the_camera_off_key_belongs_to_the_door_alone() -> None:
    for path in sorted(STATIC.glob("*.js")):
        has = "jarvis_cam_off_v1" in path.read_text(encoding="utf-8")
        assert has == (path.name == CAMERA), path.name


def test_the_door_mirrors_the_microphone_lock() -> None:
    cam = read(CAMERA)
    assert "navigator.userActivation" in cam and "ua.isActive" in cam
    assert "if (S.locked) throw err('camera_off'" in cam
    assert "if (!activated()) throw err('needs_tap'" in cam  # it starts only from a tap
    assert "e.isTrusted" in cam  # a script's own StorageEvent never switches it on
    for stop in ("'visibilitychange'", "'pagehide'", "'freeze'", "IDLE_MS = 10 * 60 * 1000"):
        assert stop in cam, stop


def test_the_cameras_off_phrases_are_the_servers_and_none_turns_it_on() -> None:
    listed = re.findall(
        r"'([^']+)'", between(read(CAMERA), "/*CAMERA-OFF-BEGIN*/", "/*CAMERA-OFF-END*/")
    )
    assert tuple(listed) == R7_PHRASES["camera.off"] and len(listed) == 20
    assert all(p in COMMAND_HINTS for p in listed)
    assert not any(re.search(r"\b(on|start|open)\b", p) for p in listed)
    cam = read(CAMERA)
    assert "C.register('camera.off'" in cam and cam.count("C.register(") == 1
    assert "unlock" not in between(cam, "C.register('camera.off'", "registered = true;")


# ---- D13: a use case never touches a frame ------------------------------------------------
def test_the_guard_passes_a_clean_use_case() -> None:
    assert use_case_problems(CLEAN_USE_CASE) == []


@pytest.mark.parametrize("api", D13_APIS)
def test_the_guard_catches_every_api_the_plan_lists(api: str) -> None:
    call = {
        "import(": "import('./x.js')",
        "JarvisConsole.api": "window.JarvisConsole.api('/v1/x')",
    }.get(api, f"window.{api}(frame)" if api[0].islower() else f"new {api}()")
    assert api in use_case_problems(CLEAN_USE_CASE + "\n" + call), api


@pytest.mark.parametrize(
    "sneak",
    [
        "const f = window['fetch']; f('/v1/x');",
        "globalThis[k](x);",
        "const c = frame.getContext('2d'); c . drawImage(v, 0, 0);",
        "JarvisConsole?.api('/v1/x');",
        "img.toDataURL();",
        "new Worker('/static/x.js');",
        "window.JarvisCamera.frame();",
        "window.JarvisMobile.parts.send.attach([f]);",
        "navigator.sendBeacon('/x', d);",
        "const x = eval('1');",
    ],
)
def test_the_guard_catches_the_ways_around_it(sneak: str) -> None:
    assert use_case_problems(CLEAN_USE_CASE + "\n" + sneak), sneak


def test_no_use_case_module_breaks_the_rule() -> None:
    # R7 builds the engine, not a use case (Appendix A); R8-R10's modules land in this check
    for path in use_case_modules():
        assert use_case_problems(path.read_text(encoding="utf-8")) == [], path.name


# ---- the engine -----------------------------------------------------------------------------
def test_the_port_core_is_i0s_byte_for_byte() -> None:
    raw = (STATIC / VISION).read_bytes()
    core = raw[: raw.index(PART_B.encode())]
    assert hashlib.sha256(core).hexdigest() == I0_CORE_SHA256  # a contract: INTEGRATION-B.md


def test_the_tasks_load_only_jarvis_own_files() -> None:
    js = read(VISION)
    tasks = js[js.index(PART_B) :]
    assert f"const BASE = '/static/vendor/vision/{assets.RELEASE}/';" in tasks
    assert "workerBlobURL: false" in tasks and "cacheMethod: 'none'" in tasks
    assert "gzip: false" in tasks and "locateFile" in tasks
    assert "https://" not in js and "http://" not in js and "jsdelivr" not in js
    named = set(re.findall(r"BASE \+ '([A-Za-z0-9._-]+)'", tasks))
    named |= {assets.POSE_MODEL, assets.OBJECT_MODEL}
    # the worker reads eng.traineddata from langPath, the core its .wasm beside itself
    assert "langPath: BASE," in tasks
    named |= {"eng.traineddata", "tesseract-core-simd-lstm.wasm"}
    needed = {f for files in assets.TASK_FILES.values() for f in files}
    assert named == needed
    assert f"POSE_MODEL = '{assets.POSE_MODEL}'" in tasks
    assert f"OBJECT_MODEL = '{assets.OBJECT_MODEL}'" in tasks
    for fetched in re.findall(r"fetch\(([^,)]+)", tasks):
        assert fetched.startswith("BASE + "), fetched  # a task fetches only its own model file


def test_the_label_lists_are_the_server_schemas() -> None:
    js = read(VISION)
    labels = re.sub(r"'\s*\+\s*'", "", between(js, "/*LABELS-BEGIN*/(", ")/*LABELS-END*/"))
    assert tuple(labels.strip("'").split(" ")) == OBJECT_LABELS
    codes = re.findall(r"'([a-z0-9_]+)'", between(js, "/*CODES-BEGIN*/", "/*CODES-END*/"))
    assert tuple(codes) == CODE_FORMATS


def test_each_task_registers_through_the_port() -> None:
    js = read(VISION)
    assert (
        "[textTask, codeTask, objectsTask, poseTask, qualityTask].forEach((t) => register(t));"
        in js
    )
    for task in ("text", "code", "objects", "pose", "quality"):
        assert f"id: '{task}', v: 1, input: 'both'" in js, task
    assert "rate: 15" in js and "rate: 5" in js  # pose <= 15 a second, objects <= 5 (D13)


# ---- the panel ------------------------------------------------------------------------------
def test_the_panel_sends_a_picture_only_through_the_one_door() -> None:
    js = read(PANEL)
    banned = ("fetch(", "XMLHttpRequest", "sendBeacon", "WebSocket", "JarvisAttach", "JarvisChat")
    banned += ("/v1/vault", "/v1/attach", "getUserMedia", "localStorage", "indexedDB")
    for bad in banned:
        assert bad not in js, bad
    assert "const Door = () => (M && M.parts && M.parts.send) || null;" in js
    sends = re.findall(r"door\.(ask|vault|attach)\(", js)
    assert sorted(sends) == ["ask", "attach", "vault"]
    for call in re.findall(r"M\.api\(([^,)]+)", js):
        assert call.strip().startswith("P"), call  # only /v1/vision and its results
    assert "door.canAsk()" in js and "JarvisBrainMode" in js


def test_the_panel_asks_nothing_before_sign_in() -> None:
    js = read(PANEL)
    for fn in ("async function loadStatus()", "async function loadResults()"):
        body = js[js.index(fn) : js.index("\n}", js.index(fn))]
        assert "if (!signedIn()" in body, fn
    assert "function keep()" in js and "if (!S.result || !signedIn()) return;" in js


@pytest.mark.parametrize("name", [CAMERA, VISION, PANEL])
def test_the_house_rules_hold(name: str) -> None:
    js = read(name)
    assert js.isascii() and len(js.splitlines()) <= 800
    for bad in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", "eval(",
                "new Function", "console.log"):  # fmt: skip
        assert bad not in js, (name, bad)


def test_the_stylesheet_only_places_things() -> None:
    css = read(CSS)
    assert len(css.splitlines()) <= 150 and css.isascii()
    rules = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    assert not re.search(
        r"#[0-9a-fA-F]{3,8}\b|rgba?\(|hsla?\(|font-family|box-shadow|@font-face", rules
    )
    for radius in re.findall(r"border-radius:([^;}]+)", rules):
        assert radius.startswith("var(--r-"), radius
    for colour in re.findall(r"(?<![-\w])(?:color|background):([^;}]+)", rules):
        assert colour.startswith("var(--"), colour
