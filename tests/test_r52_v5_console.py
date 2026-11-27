# tests/test_r52_v5_console.py -- R5.2 V5 (row 84, docs/plans/r5-2-voice.md 3.5, D6): the speaker
# check in the console, read as text: what it may send (the model file's GET, nothing else), what
# it never touches (approvals, passkeys, unlocks, Telegram), the barge-in hook it adds, and the
# model slot (MANIFEST.json <-> the runtime's SLOT, licence, SHA-256, package data).
# Behaviour in a browser: tests/browser/test_r52_v5_voiceprint.py.
from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
import tomllib
from pathlib import Path

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from r52_v5_fakes import ROOT, STATIC

from jarvis.api import speaker_assets
from jarvis.localspeech.protocol import PERMISSIVE_LICENCES

OWN = ("console-voiceprint-math.js", "console-voiceprint.js", "console-voiceprint-panel.js")
BARGE = "console-voice-barge.js"
SLOT_DIR = STATIC / "vendor/speaker/spk-1"
# what gives, asks for or stands for an approval, a passkey or an unlock in the console
APPROVING = re.compile(
    r"/v1/approvals|/v1/passkeys|/approve\b|approve\(|navigator\.credentials|JarvisPasskey|"
    r"JarvisApprovals|JarvisVault|JarvisTelegram|\.unlock\(|x-jarvis-spoken-by",
    re.IGNORECASE,
)
APPROVAL_FILES = (
    "console-approvals.js",
    "console-approve-all.js",
    "console-permissions.js",
    "console-r7-lock.js",
    "console-vault.js",
    "console-vault-add.js",
    "console-telegram.js",
)


def read(name: str) -> str:
    return (STATIC / name).read_text(encoding="utf-8")


def _code(text: str) -> str:
    """The script without its // comments (the header says what it never does, in words)."""
    return "\n".join(re.sub(r"(^|\s)//.*$", "", line) for line in text.splitlines())


def _manifest() -> dict[str, object]:
    out: dict[str, object] = json.loads((SLOT_DIR / "MANIFEST.json").read_text(encoding="utf-8"))
    return out


def _slot_in_js() -> dict[str, str | None]:
    js = read("console-voiceprint.js")
    m = re.search(r"const SLOT = \{(.*?)\};", js, re.S)
    assert m, "SLOT is gone"
    body = m.group(1)
    fields: dict[str, str | None] = {}
    for key in ("id", "release", "file", "sha256", "window"):
        v = re.search(rf"\b{key}: (null|'([^']*)')", body)
        assert v, key
        fields[key] = v.group(2)
    return fields


# ---- privacy: the print never leaves the browser ---------------------------------------------
@pytest.mark.parametrize("name", OWN)
def test_the_speaker_check_sends_nothing_but_the_model_files_get(name: str) -> None:
    code = _code(read(name))
    for banned in (
        "XMLHttpRequest",
        "sendBeacon",
        "WebSocket",
        "EventSource",
        "JarvisChat",
        "JarvisConsole",
        "/v1/",
        "innerHTML",
        "console.log",
        "postMessage",
        "eval(",
        "new Function",
    ):
        assert banned not in code, (name, banned)
    fetches = re.findall(r"\bfetch\(([^)]*)\)", code)
    if name == "console-voiceprint.js":
        assert fetches == [
            "MODEL_BASE + MODEL.release + '/' + MODEL.file, { credentials: 'same-origin' }"
        ]
        assert "const MODEL_BASE = '/static/vendor/speaker/';" in code
    else:
        assert fetches == [], name


def test_the_print_is_encrypted_with_a_key_that_cannot_be_exported() -> None:
    code = _code(read("console-voiceprint.js"))
    assert "generateKey({ name: 'AES-GCM', length: 256 }, false, ['encrypt', 'decrypt'])" in code
    assert code.count("crypto.subtle.encrypt(") == 1 and "additionalData: AAD" in code
    assert "exportKey" not in code and "wrapKey" not in code
    # the only thing in localStorage is the per-device switch; the print goes to IndexedDB encrypted
    assert re.findall(r"store\.set\((\w+)", code) == ["OFF_KEY", "OFF_KEY", "OFF_KEY"]
    assert "put('print', { v: 1, iv, data })" in code
    assert "const OFF_KEY = 'jarvis_voiceprint_off_v1';" in code


# ---- the speaker check never approves anything -----------------------------------------------
@pytest.mark.parametrize("name", OWN)
def test_the_speaker_check_never_touches_an_approval_a_passkey_or_an_unlock(name: str) -> None:
    assert not APPROVING.search(_code(read(name))), name


@pytest.mark.parametrize("name", APPROVAL_FILES)
def test_no_approval_passkey_unlock_or_telegram_screen_reads_the_speaker_check(name: str) -> None:
    text = read(name)
    for word in ("JarvisVoicePrint", "voiceprint", "x-jarvis-spoken-by", "spoken by the owner"):
        assert word.lower() not in text.lower(), (name, word)


def test_only_the_barge_in_hook_asks_the_speaker_check() -> None:
    asks = re.compile(r"JarvisVoicePrint\b")
    users = {p.name for p in STATIC.glob("*.js") if asks.search(p.read_text(encoding="utf-8"))}
    assert users == {"console-voiceprint.js", "console-voiceprint-panel.js", BARGE}
    barge = _code(read(BARGE))
    calls = set(re.findall(r"JarvisVoicePrint\b(?:\.(\w+))?", barge))
    calls |= set(re.findall(r"\bp\.(\w+)\(", barge))
    assert calls == {"", "CHECK_MS", "active", "verify"}, calls


def test_the_barge_in_hook_is_the_smallest_edit() -> None:
    barge = read(BARGE)
    # read where a voice opens the gate, and where a clip starts, ends and is judged
    assert barge.count("s.check") == 6
    assert "check: printOn() ? pol : null" in barge
    assert "if (pol === 'speech' && !s.check) { interrupt(" in barge
    rejected = "if (who === 'other' || (who === 'short' && s.check === 'speech')) "
    assert rejected + "{ s.empties++; unduck(); return; }" in barge
    # a check clip is judged before anything is sent: the cloud request comes after it
    judge = barge[barge.index("return async function judge(c) {") :]
    assert judge.index("await heardBy(c.frames)") < judge.index("/v1/voice/transcribe")
    assert "return p ? await p.verify(frames) : 'skip'; } catch (_) { return 'skip'; }" in barge


# ---- the model slot --------------------------------------------------------------------------
def test_the_slot_names_one_permissive_model_and_the_runtime_names_the_same_one() -> None:
    m = _manifest()
    slot = m["slot"]
    assert isinstance(slot, dict) and m["release"] == speaker_assets.RELEASE == "spk-1"
    assert slot["licence"] in PERMISSIVE_LICENCES
    js = _slot_in_js()
    assert (
        js["release"] == m["release"] and js["file"] == slot["file"] and js["window"] == "hamming"
    )
    assert re.fullmatch(
        r"[A-Za-z0-9][A-Za-z0-9._-]{0,80}", str(js["file"])
    )  # the route's name rule


def test_no_model_file_is_shipped_until_its_sum_is_pinned_in_both_places() -> None:
    files = _manifest()["files"]
    assert isinstance(files, dict)
    js = _slot_in_js()
    on_disk = {p.name for p in SLOT_DIR.iterdir() if p.name != "MANIFEST.json"}
    assert on_disk == set(files), "every file in the release is listed, and only those"
    if not files:
        assert js["sha256"] is None  # today: an empty slot, the console says "no model"
        return
    entry = files[str(js["file"])]
    assert entry["sha256"] == js["sha256"] and entry["licence"] in PERMISSIVE_LICENCES
    data = (SLOT_DIR / str(js["file"])).read_bytes()
    assert hashlib.sha256(data).hexdigest() == entry["sha256"] and len(data) == entry["bytes"]
    cfg = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert "static/vendor/speaker/*/*" in cfg["tool"]["setuptools"]["package-data"]["jarvis.api"]


def _app() -> FastAPI:
    app = FastAPI()
    app.include_router(speaker_assets.router)
    return app


async def test_the_route_serves_nothing_from_the_empty_slot() -> None:
    speaker_assets.speaker_files.cache_clear()
    async with AsyncClient(transport=ASGITransport(app=_app()), base_url="http://t") as c:
        for path in (
            "spk-1/wespeaker-voxceleb-campplus.onnx",
            "spk-1/MANIFEST.json",
            "spk-2/x.onnx",
            "spk-1/..%2FMANIFEST.json",
            "Spk-1/x.onnx",
        ):
            assert (await c.get(f"/static/vendor/speaker/{path}")).status_code == 404, path


async def test_a_pinned_file_is_served_immutable_and_a_changed_one_is_not(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rel = tmp_path / "spk-9"
    rel.mkdir()
    (rel / "m.onnx").write_bytes(b"model bytes")
    (rel / "x.js").write_text("alert(1)", encoding="utf-8")
    sums = {n: hashlib.sha256((rel / n).read_bytes()).hexdigest() for n in ("m.onnx", "x.js")}
    listed = {
        "m.onnx": {"sha256": sums["m.onnx"], "type": "application/octet-stream"},
        "x.js": {"sha256": sums["x.js"], "type": "application/javascript"},
    }
    (rel / "MANIFEST.json").write_text(json.dumps({"files": listed}), encoding="utf-8")
    monkeypatch.setattr(speaker_assets, "SPEAKER", tmp_path)
    speaker_assets.speaker_files.cache_clear()
    async with AsyncClient(transport=ASGITransport(app=_app()), base_url="http://t") as c:
        r = await c.get("/static/vendor/speaker/spk-9/m.onnx")
        assert r.status_code == 200 and r.content == b"model bytes"
        assert r.headers["cache-control"] == "public, max-age=31536000, immutable"
        assert (
            await c.get("/static/vendor/speaker/spk-9/x.js")
        ).status_code == 404  # never JavaScript
        (rel / "m.onnx").write_bytes(b"other bytes")
        assert (await c.get("/static/vendor/speaker/spk-9/m.onnx")).status_code == 404
    speaker_assets.speaker_files.cache_clear()


# ---- the scripts parse -----------------------------------------------------------------------
@pytest.mark.parametrize("name", (*OWN, BARGE))
def test_the_script_parses(name: str) -> None:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed")
    run = subprocess.run(
        [node, "--check", str(STATIC / name)], capture_output=True, text=True, check=False
    )
    assert run.returncode == 0, run.stderr


@pytest.mark.parametrize("name", OWN)
def test_the_scripts_are_ascii_and_set_text_only(name: str) -> None:
    text = read(name)
    assert text.isascii(), name
    assert (
        "insertAdjacentHTML" not in text
        and "outerHTML" not in text
        and "document.write" not in text
    )
