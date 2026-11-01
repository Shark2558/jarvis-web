# tests/test_wakeword_assets.py — slice 9 (D12): the on-device "Hey Jarvis" wake word's vendored
# files (onnxruntime-web + openWakeWord models): pinned sha256s, licences, allow-listed routes with
# exact media types, the one CSP addition, packaging, and the module's privacy/safety contract.
from __future__ import annotations

import fnmatch
import hashlib
import tomllib
from pathlib import Path

import pytest
from httpx import AsyncClient

from jarvis.api.console import (
    ORT_FILES,
    ORT_RELEASE,
    WAKEWORD_FILES,
    WAKEWORD_RELEASE,
)

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "src/jarvis/api/static"
ORT_DIR = STATIC / "vendor/ort"
WAKE_DIR = STATIC / "wakeword"
IMMUTABLE = "public, max-age=31536000, immutable"
ORT_BASE = f"/static/vendor/{ORT_RELEASE}/"
WAKE_BASE = f"/static/wakeword/{WAKEWORD_RELEASE}/"

# The pinned upstream releases. Changing either is a deliberate upgrade: new files, new MANIFEST,
# new parity reference (tests/fixtures/wakeword/make_reference.py).
EXPECTED_ORT = {
    "ort.wasm.min.mjs": "application/javascript",
    "ort-wasm-simd-threaded.mjs": "application/javascript",
    "ort-wasm-simd-threaded.wasm": "application/wasm",
}
EXPECTED_MODELS = ("melspectrogram.onnx", "embedding_model.onnx", "hey_jarvis_v0.1.onnx")
# Files in the vendored folders that we wrote ourselves (not upstream bytes, so not hashed).
OWN_FILES = {ORT_DIR: {"MANIFEST.txt"}, WAKE_DIR: {"MANIFEST.txt", "LICENSE.txt"}}

PREVIOUS_CSP = (
    "default-src 'none'; script-src 'self'; "
    "style-src 'self' 'unsafe-inline'; connect-src 'self'; img-src 'self' data:; "
    "font-src 'self'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'"
)


def _manifest(folder: Path) -> dict[str, tuple[str, int]]:
    """`sha256 <hex> <bytes> <name> ...` lines → {name: (hex, bytes)}."""
    entries: dict[str, tuple[str, int]] = {}
    for line in (folder / "MANIFEST.txt").read_text(encoding="utf-8").splitlines():
        if line.startswith("sha256 "):
            _, digest, size, name = line.split()[:4]
            entries[name] = (digest, int(size))
    return entries


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


# ---- pinned versions and hashes ----------------------------------------------------------------
def test_releases_are_the_pinned_ones() -> None:
    assert ORT_RELEASE == "ort-1.30.0"
    assert WAKEWORD_RELEASE == "oww-0.5.1"
    assert ORT_FILES == EXPECTED_ORT
    assert set(EXPECTED_MODELS) == WAKEWORD_FILES


@pytest.mark.parametrize("folder", [ORT_DIR, WAKE_DIR], ids=["ort", "wakeword"])
def test_every_vendored_file_matches_its_pinned_sha256_and_size(folder: Path) -> None:
    entries = _manifest(folder)
    assert entries, "MANIFEST.txt lists no files"
    for name, (digest, size) in entries.items():
        path = folder / name
        assert path.is_file(), name
        assert path.stat().st_size == size, name
        assert _sha256(path) == digest, f"{name} differs from the pinned upstream file"


@pytest.mark.parametrize("folder", [ORT_DIR, WAKE_DIR], ids=["ort", "wakeword"])
def test_no_unlisted_file_sits_in_the_vendored_folders(folder: Path) -> None:
    on_disk = {p.name for p in folder.iterdir()}
    assert on_disk == set(_manifest(folder)) | OWN_FILES[folder]


def test_manifests_record_versions_and_sources() -> None:
    ort = (ORT_DIR / "MANIFEST.txt").read_text(encoding="utf-8")
    assert "onnxruntime-web 1.30.0" in ort
    assert "https://registry.npmjs.org/onnxruntime-web/-/onnxruntime-web-1.30.0.tgz" in ort
    assert "sha512-q0y+JrrtukXSzsBWEMccVfqX25LRmosXHF+CaRJmg8pZClzcV7svNc4rKY3jL02Vb7Qm" in ort
    wake = (WAKE_DIR / "MANIFEST.txt").read_text(encoding="utf-8")
    assert "openWakeWord v0.5.1" in wake
    for name in EXPECTED_MODELS:
        assert f"https://github.com/dscripka/openWakeWord/releases/download/v0.5.1/{name}" in wake
    served = set(EXPECTED_ORT) | set(EXPECTED_MODELS)
    assert served <= set(_manifest(ORT_DIR)) | set(_manifest(WAKE_DIR))


# ---- licences ----------------------------------------------------------------------------------
def test_licences_ship_beside_the_vendored_files() -> None:
    mit = (ORT_DIR / "LICENSE-onnxruntime.txt").read_text(encoding="utf-8")
    assert mit.startswith("MIT License") and "Copyright (c) Microsoft Corporation" in mit
    notices = (ORT_DIR / "ThirdPartyNotices-onnxruntime.txt").read_text(encoding="utf-8")
    assert "THIRD PARTY SOFTWARE NOTICES" in notices.upper()
    apache = (WAKE_DIR / "LICENSE-openwakeword-code.txt").read_text(encoding="utf-8")
    assert "Apache License" in apache and "Version 2.0, January 2004" in apache


def test_model_licence_notice_attributes_and_warns() -> None:
    notice = (WAKE_DIR / "LICENSE.txt").read_text(encoding="utf-8")
    flat = " ".join(notice.split())
    assert "CC BY-NC-SA 4.0" in flat
    assert "https://creativecommons.org/licenses/by-nc-sa/4.0/" in flat
    assert "David Scripka" in flat and "https://github.com/dscripka/openWakeWord" in flat
    assert "personal, non-commercial" in flat
    assert "replace" in flat.lower() and "self-trained model before any public launch" in flat
    for name in EXPECTED_MODELS:
        assert name in flat


# ---- routes ------------------------------------------------------------------------------------
@pytest.mark.parametrize("name", sorted(EXPECTED_ORT))
async def test_serves_each_ort_file_with_its_media_type_and_immutable_cache(
    client: AsyncClient, name: str
) -> None:
    r = await client.get(ORT_BASE + name)
    assert r.status_code == 200
    assert r.headers["content-type"].split(";")[0] == EXPECTED_ORT[name]
    assert r.headers["cache-control"] == IMMUTABLE
    assert r.headers["x-content-type-options"] == "nosniff"
    assert hashlib.sha256(r.content).hexdigest() == _manifest(ORT_DIR)[name][0]
    if name.endswith(".wasm"):
        assert r.content[:4] == b"\0asm"


@pytest.mark.parametrize("name", EXPECTED_MODELS)
async def test_serves_each_model_as_octet_stream_with_immutable_cache(
    client: AsyncClient, name: str
) -> None:
    r = await client.get(WAKE_BASE + name)
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/octet-stream"
    assert r.headers["cache-control"] == IMMUTABLE
    assert r.headers["x-content-type-options"] == "nosniff"
    assert hashlib.sha256(r.content).hexdigest() == _manifest(WAKE_DIR)[name][0]


@pytest.mark.parametrize(
    "path",
    [
        ORT_BASE + "ort.wasm.min.mjs.map",  # not shipped
        ORT_BASE + "ort.min.mjs",  # other ORT builds are not shipped
        ORT_BASE + "ort-wasm-simd-threaded.jsep.wasm",
        ORT_BASE + "LICENSE-onnxruntime.txt",  # on disk, not served
        ORT_BASE + "MANIFEST.txt",
        ORT_BASE + "ORT.WASM.MIN.MJS",  # no case folding
        ORT_BASE + "three.module.min.js",  # another vendor's file under ort's release
        "/static/vendor/ort-1.29.0/ort.wasm.min.mjs",  # wrong release
        "/static/vendor/ort/ort.wasm.min.mjs",  # the folder name is not a release
        "/static/vendor/ort.wasm.min.mjs",
        ORT_BASE,
        ORT_BASE + "..%2F..%2Fconsole.py",
        ORT_BASE + "%2e%2e%2fthree.module.min.js",
        WAKE_BASE + "alexa_v0.1.onnx",  # not shipped
        WAKE_BASE + "hey_jarvis_v0.1.tflite",
        WAKE_BASE + "LICENSE.txt",  # on disk, not served
        WAKE_BASE + "MANIFEST.txt",
        WAKE_BASE + "HEY_JARVIS_V0.1.ONNX",
        "/static/wakeword/oww-0.6.0/hey_jarvis_v0.1.onnx",  # wrong release
        "/static/wakeword/hey_jarvis_v0.1.onnx",  # missing release segment
        WAKE_BASE,
        WAKE_BASE + "..%2F..%2Fconsole.py",
        "/static/wakeword/..%2Fvendor/hey_jarvis_v0.1.onnx",
    ],
)
async def test_rejects_unknown_names_releases_and_traversal(client: AsyncClient, path: str) -> None:
    r = await client.get(path)
    assert r.status_code == 404
    assert r.content[:4] != b"\0asm"
    assert b"onnxruntime" not in r.content.lower()


# ---- CSP: exactly one addition ------------------------------------------------------------------
async def test_csp_adds_only_wasm_unsafe_eval_to_script_src(client: AsyncClient) -> None:
    csp = (await client.get("/")).headers["content-security-policy"]
    added = "script-src 'self' 'wasm-unsafe-eval';"
    assert csp == PREVIOUS_CSP.replace("script-src 'self';", added)
    # nothing else: no unsafe-eval, no workers or blob:, no other hosts
    assert "'unsafe-eval'" not in csp and "blob:" not in csp and "worker-src" not in csp
    assert "http" not in csp


# ---- packaging ---------------------------------------------------------------------------------
def test_every_vendored_file_is_covered_by_package_data() -> None:
    """The image installs with `pip install .`: a file missing from package-data 404s in prod."""
    cfg = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    globs = cfg["tool"]["setuptools"]["package-data"]["jarvis.api"]
    base = ROOT / "src/jarvis/api"
    files = [p for d in (ORT_DIR, WAKE_DIR) for p in d.iterdir()]
    assert files
    for path in files:
        rel = path.relative_to(base).as_posix()
        assert any(fnmatch.fnmatch(rel, g) for g in globs), f"{rel} not in package-data"


def test_docker_context_keeps_the_vendored_files() -> None:
    lines = (ROOT / ".dockerignore").read_text(encoding="utf-8").splitlines()
    patterns = [p.strip() for p in lines if p.strip() and not p.strip().startswith(("#", "!"))]
    for path in [p for d in (ORT_DIR, WAKE_DIR) for p in d.iterdir()]:
        rel = path.relative_to(ROOT).as_posix()
        for pat in patterns:  # fnmatch's * also crosses "/": stricter than Docker's own matching
            assert not fnmatch.fnmatch(rel, pat), (pat, rel)
            assert not rel.startswith(pat.rstrip("/") + "/"), (pat, rel)
