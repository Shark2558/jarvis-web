# evals/r7/vision.py
"""R7 eval, Part B (`vision`): the camera and the vision engine (plan D11-D14). Mock only: the
console's real camera door, engine and Camera panel run in Node on tests/fixtures/r7/b_dom.js (a
fake camera whose every frame is a planted pixel pattern, R5's real voice router, a spy on every
way to send bytes); the server's real schema and store run on MemoryDocs.

    only_the_door_asks      only console-camera.js (beside the microphone's file) asks for a camera
    locked_means_off        locked: no live track and no ask; unlock() from script is false; a
                            hidden page stops it; the "Camera on" chip shows exactly while live
    cameras_off_by_voice    "cameras off" in its 20 phrasings locks; "turn the camera on" does not
    no_picture_leaves       during a live run and a photo look no request body carries picture
                            bytes, no upload route is called, the picture door is never used; Keep
                            sends the result alone; the three buttons go through the one door
    ask_only_when_it_sees   "Ask the AI about this photo" is not offered while the brain can't see
    results_only            a use case receives frozen plain Results; the static guard catches
                            every API D13 lists, from drawImage to the storage APIs
    schema_drops            a result outside its schema is dropped by the engine and by the store
    kept_sealed             a kept result is sealed (no read text in the document) and opens only
                            under its own key
    vendored_pinned         every vendored file matches its recorded SHA-256; without their models
                            pose and objects are "not installed"

Three negative controls; each must fail the cases named in EXPECTED (a suite that cannot fail
proves nothing):
    upload_in_look       the panel's look path uploads the frame it looked at
    lock_check_removed   console-camera.js starts the camera while locked
    schema_checks_off    the engine's and the store's schema checks let everything through
"""

from __future__ import annotations

import asyncio
import importlib.util
import json
import re
import sys
from collections.abc import Awaitable, Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from types import ModuleType
from typing import Any

from r7_fakes_b import (
    CLEAN_USE_CASE,
    D13_APIS,
    LABEL_TEXT,
    OTHER_KEY,
    STATIC,
    UID,
    quality_result,
    result,
    run_dom,
    store,
    text_result,
    use_case_problems,
)

from jarvis.storage.docs import MemoryDocs
from jarvis.vision import assets
from jarvis.vision import store as store_mod
from jarvis.vision.results import Result
from jarvis.vision.store import Dropped, VisionUnavailable
from jarvis.voice.commands import R7_PHRASES

PART = "vision"
BUILT = True
ROOT = Path(__file__).resolve().parents[2]
CONTROLS = ("upload_in_look", "lock_check_removed", "schema_checks_off")
EXPECTED: dict[str, tuple[str, ...]] = {
    "upload_in_look": ("no_picture_leaves",),
    "lock_check_removed": ("locked_means_off",),
    "schema_checks_off": ("schema_drops",),
}
UPLOADS = ("/v1/attachments", "/v1/vault", "/v1/chat", "/v1/files", "/app/share", "/phone/")
ASK = "Ask the AI about this photo (about ₹0.30)"
LOOK = [{"op": "open"}, {"op": "task", "task": "quality"}]
_active: set[str] = set()
Case = Callable[[], Awaitable[list[str]]]

# ---- the controls, as changed copies of the real files (never written to disk) -------------------
LOCK_CHECK = "  if (S.locked) throw err('camera_off', OFF_TEXT);\n"
STREAM_ON = "(r) => show(r, false));"
UPLOAD = (
    "(r) => { show(r, false); const f = S.view && S.view.frame(); if (f) M.api('/v1/attachments', "
    "{ body: { pixels: Array.from(f.getContext('2d').getImageData(0, 0, 2, 2).data) } }); });"
)
LOOK_AT = "  try { show(await V.run(S.task, source), !!S.photo);"
LOOK_UPLOAD = (
    "  M.api('/v1/attachments', { body: { pixels: Array.from(source.getContext('2d')"
    ".getImageData(0, 0, 2, 2).data) } });\n" + LOOK_AT
)
CORE_CHECK = "const ok = !!data && typeof task.check === 'function' && task.check(data) === true;"


def _src(name: str) -> str:
    return (STATIC / name).read_text(encoding="utf-8")


def _swap(text: str, old: str, new: str) -> str:
    if old not in text:
        raise RuntimeError(f"a control no longer applies: {old[:40]!r}")
    return text.replace(old, new)


def sources() -> dict[str, str]:
    """The console files as the active control changes them (the real ones with none active)."""
    out: dict[str, str] = {}
    if "upload_in_look" in _active:
        panel = _swap(_src("console-camera-panel.js"), STREAM_ON, UPLOAD)
        out["console-camera-panel.js"] = _swap(panel, LOOK_AT, LOOK_UPLOAD)
    if "lock_check_removed" in _active:
        out["console-camera.js"] = _swap(_src("console-camera.js"), LOCK_CHECK, "")
    if "schema_checks_off" in _active:
        out["console-vision.js"] = _swap(
            _src("console-vision.js"), CORE_CHECK, "const ok = !!data;"
        )
    return out


def _lax(raw: object) -> Result | None:  # the store's check, with the task's schema switched off
    return Result.model_construct(**raw) if isinstance(raw, dict) else None


@contextmanager
def server_controls() -> Iterator[None]:
    real = store_mod.parse_result
    if "schema_checks_off" in _active:
        store_mod.parse_result = _lax  # type: ignore[assignment]
    try:
        yield
    finally:
        store_mod.parse_result = real


def dom(script: str, **payload: Any) -> dict[str, Any]:
    return run_dom(script, sources=sources(), **payload)


def press(label: str) -> dict[str, str]:
    return {"op": "press", "label": label}


def leaks(out: dict[str, Any]) -> list[str]:
    plant = out["plant"]
    bad = []
    for req in out["net"]:
        carries = any(plant[k] in req["body"] for k in ("ascii", "base64", "numbers"))
        upload = req["path"].startswith(UPLOADS) or req["kind"] == "chat"
        if carries or req["binary"] or upload:
            bad.append(f"{req['kind']} {req['method']} {req['path']}")
    return bad


# ---- the cases -----------------------------------------------------------------------------------
async def only_the_door_asks() -> list[str]:
    asks = re.compile(r"getUserMedia|getDisplayMedia|ImageCapture|facingMode")
    allowed = {"console-camera.js", "console-voice-capture.js", "console-voice-devices.js"}
    bad = [
        p.name
        for p in sorted(STATIC.glob("*.js"))
        if p.name not in allowed and asks.search(p.read_text(encoding="utf-8"))
    ]
    return [f"{name} asks for a camera" for name in bad]


async def locked_means_off() -> list[str]:
    steps = [{"op": "lock"}, {"op": "start", "tap": True}, {"op": "unlock", "tap": False},
             {"op": "unlock", "tap": True}, {"op": "start", "tap": True}, {"op": "hide"},
             {"op": "start", "tap": True}, {"op": "lock"}]  # fmt: skip
    got = dom("camera", steps=steps)["steps"]
    fails = []
    if got[1]["asked"] or got[1]["liveTracks"] or got[1]["ok"]:
        fails.append("a locked camera was asked for, or went live")
    if got[2]["ok"] or not got[2]["locked"]:
        fails.append("unlock() from script switched it on")
    if not got[3]["ok"] or not got[4]["live"] or not got[4]["chip"]:
        fails.append("a tap did not switch it on, or the chip did not show while live")
    if got[5]["live"] or got[5]["liveTracks"] or got[5]["chip"]:
        fails.append("a hidden page left the camera on")
    if got[7]["live"] or got[7]["liveTracks"] or got[7]["chip"]:
        fails.append("the lock left a track live")
    return fails


async def cameras_off_by_voice() -> list[str]:
    steps: list[dict[str, Any]] = []
    for phrase in R7_PHRASES["camera.off"]:
        steps += [{"op": "unlock", "tap": True}, {"op": "start", "tap": True},
                  {"op": "voice", "text": f"Jarvis, {phrase}"}]  # fmt: skip
    steps += [
        {"op": "voice", "text": "Jarvis, turn the camera on"},
        {"op": "voice", "text": "cameras on"},
    ]
    got = dom("camera", steps=steps)["steps"]
    said = zip(R7_PHRASES["camera.off"], got[2::3], strict=False)
    fails = [
        f"{p!r} did not lock" for p, s in said if not (s["ok"] and s["locked"] and not s["live"])
    ]
    if len(R7_PHRASES["camera.off"]) != 20:
        fails.append("not 20 phrasings")
    fails += [f"voice switched it on: {s}" for s in got[-2:] if s["ok"] or not s["locked"]]
    return fails


async def no_picture_leaves() -> list[str]:
    fails = []
    run = [press("Start the camera"), {"op": "wait", "ms": 1200}, {"op": "mark", "name": "kept"}]
    live = dom("look", steps=[*LOOK, *run, press("Keep"), press("Stop")])
    fails += [f"live run: {x}" for x in leaks(live)] + [
        f"live run used the door: {d}" for d in live["door"]
    ]
    kept = live["net"][live["marks"]["kept"]["net"] :]
    if [(r["method"], r["path"]) for r in kept] != [("POST", "/v1/vision/results")]:
        fails.append(f"Keep sent more than the result: {kept}")
    photo = dom("look", steps=[*LOOK, press("Choose a photo"), {"op": "pick"}])
    fails += [f"photo look: {x}" for x in leaks(photo)] + [
        f"photo look used the door: {d}" for d in photo["door"]
    ]
    steps = [*LOOK, press("Choose a photo"), {"op": "pick"}, press("Attach to my message")]
    sent = dom("look", sees=True, steps=steps)
    if [d["how"] for d in sent["door"]] != ["attach"] or not sent["sent"].endswith(": 1"):
        fails.append("Attach did not go through the one door and count")
    return fails


async def ask_only_when_it_sees() -> list[str]:
    steps = [*LOOK, press("Choose a photo"), {"op": "pick"}]
    blind, sees = dom("look", sees=False, steps=steps), dom("look", sees=True, steps=steps)
    fails = []
    if ASK in blind["buttons"]:
        fails.append("Ask was offered while the brain can't see pictures")
    if ASK not in sees["buttons"]:
        fails.append("Ask was not offered while the brain sees pictures")
    return fails


async def results_only() -> list[str]:
    out = dom("engine", probe={"n": 1})
    fails = []
    plain = ("number", "string", "boolean", "[object Object]:frozen", "[object Array]:frozen")
    for got in out["got"]:
        if got["keys"] != ["at", "data", "device", "ms", "ok", "quality", "task", "v"]:
            fails.append(f"a use case got {got['keys']}")
        fails += [f"a use case got a {k}" for k in got["kinds"] if k not in plain]
    if use_case_problems(CLEAN_USE_CASE):
        fails.append("the guard refused a clean use case")
    for api in D13_APIS:
        call = "import('./x.js')" if api == "import(" else f"window.{api}(x)"
        if api not in use_case_problems(CLEAN_USE_CASE + "\n" + call):
            fails.append(f"the guard let {api} through")
    return fails


BAD_RESULTS: list[Any] = [
    {**text_result(), "pixels": "iVBORw0KGgo="},
    text_result("x" * 2001),
    result(
        "objects",
        {"objects": [{"label": "someone", "score": 0.9, "box": {"x": 0, "y": 0, "w": 1, "h": 1}}]},
    ),
    result("quality", {"light": 1.5, "sharp": 0.2}),
]


async def schema_drops() -> list[str]:
    fails = []
    probe = dom("engine", probe={"n": 2, "pixels": [82, 55, 80]})["results"][0]
    if probe["ok"] or probe["data"] != {}:
        fails.append("the engine kept an answer outside its schema")
    docs = MemoryDocs()
    s = store(docs=docs)
    with server_controls():
        for raw in BAD_RESULTS:
            try:
                await s.keep(UID, raw)
                fails.append(f"the store kept {json.dumps(raw)[:60]}")
            except Dropped:
                pass
    return fails


async def kept_sealed() -> list[str]:
    docs = MemoryDocs()
    await store(docs=docs).keep(UID, text_result())
    await store(docs=docs).keep(UID, quality_result())
    flat = json.dumps(docs._data)
    fails = ["the read text is in the document"] if LABEL_TEXT[:12] in flat or "MRP" in flat else []
    try:
        await store(docs=docs, key=OTHER_KEY).list(UID, days=7)
        fails.append("another key opened the kept results")
    except VisionUnavailable:
        pass
    return fails


def _script() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "r7_vision_assets", ROOT / "scripts" / "vision_assets.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


async def vendored_pinned() -> list[str]:
    from jarvis.api.console import vision_files

    fails = list(_script().check(assets.FOLDER, assets.RELEASE))
    vision_files.cache_clear()
    got = assets.installed(vision_files(assets.RELEASE))
    if got != {"text": True, "code": True, "objects": False, "pose": False, "quality": True}:
        fails.append(f"installed: {got}")
    return fails


CASES: tuple[Case, ...] = (
    only_the_door_asks,
    locked_means_off,
    cameras_off_by_voice,
    no_picture_leaves,
    ask_only_when_it_sees,
    results_only,
    schema_drops,
    kept_sealed,
    vendored_pinned,
)


async def _run() -> list[dict[str, Any]]:
    out = []
    for case in CASES:
        try:
            fails = await case()
        except Exception as exc:  # noqa: BLE001 - a case that crashes fails, with its reason
            fails = [f"crashed: {type(exc).__name__}: {str(exc)[:300]}"]
        out.append({"id": f"{PART}:{case.__name__}", "passed": not fails, "failures": fails})
    return out


async def cases() -> list[dict[str, Any]]:
    _active.clear()
    results = await _run()
    print(f"{PART}: {len(results)} cases; negative controls: {', '.join(CONTROLS)}")
    return results


async def control() -> dict[str, Any]:
    """Each control on its own: the suite fails only when EVERY one broke all it must break."""
    failed: dict[str, list[str]] = {}
    for name in CONTROLS:
        _active.clear()
        _active.add(name)
        try:
            got = await _run()
        finally:
            _active.clear()
        failed[name] = [r["id"] for r in got if not r["passed"]]
    caught = all({f"{PART}:{c}" for c in EXPECTED[name]} <= set(failed[name]) for name in CONTROLS)
    return {"name": " + ".join(CONTROLS), "suite_failed": caught, "failed_cases": failed}


if __name__ == "__main__":  # a quick look: python evals/r7/vision.py
    print(json.dumps(asyncio.run(cases()), indent=1))

__all__ = ["BUILT", "CASES", "CONTROLS", "EXPECTED", "PART", "cases", "control"]
