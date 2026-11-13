# tests/test_r7_b_assets.py -- R7 Part B (docs/plans/r7-mobile.md D14): the vision tools JARVIS
# serves itself. Every vendored file matches the SHA-256 its MANIFEST.json records (the route
# serves nothing else); only the files a task really loads are vendored; every one has an Apache
# or MIT licence beside the release folder and nothing is AGPL; the two MediaPipe model files are
# absent here (storage.googleapis.com is refused), so `pose` and `objects` say "not installed"
# while `text`, `code` and `quality` are installed; and scripts/vision_assets.py pins every
# source (an npm integrity, a tag or commit address, or a model whose sum is still to be pinned).
from __future__ import annotations

import base64
import hashlib
import importlib.util
import io
import json
import shutil
import sys
import tarfile
from pathlib import Path
from types import ModuleType

import pytest
from httpx import AsyncClient

from jarvis.api import console
from jarvis.buildbook.gen.libs import VENDORED, licence_from_text
from jarvis.vision import assets

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "src" / "jarvis" / "api" / "static"
VISION = STATIC / "vendor" / "vision"
RELEASE = VISION / assets.RELEASE
MB = 1024 * 1024
BUDGET_BYTES = 25 * MB  # D14: about 35 MB with the two models; without them under 25 MB


def _script() -> ModuleType:
    path = ROOT / "scripts" / "vision_assets.py"
    spec = importlib.util.spec_from_file_location("vision_assets_under_test", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _manifest() -> dict[str, object]:
    data = json.loads((RELEASE / "MANIFEST.json").read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    return data


def _files() -> dict[str, dict[str, object]]:
    files = _manifest()["files"]
    assert isinstance(files, dict)
    return files


def test_every_vendored_file_matches_its_recorded_sum_and_size() -> None:
    files = _files()
    assert files, "the manifest lists nothing"
    for name, entry in files.items():
        data = (RELEASE / name).read_bytes()
        assert hashlib.sha256(data).hexdigest() == entry["sha256"], name
        assert len(data) == entry["bytes"], name
        assert entry["type"] in console.VISION_TYPES, name


def test_the_release_folder_holds_only_what_the_manifest_lists() -> None:
    on_disk = {p.name for p in RELEASE.iterdir() if p.is_file()} - {"MANIFEST.json"}
    assert on_disk == set(_files())
    assert not any(p.is_dir() for p in RELEASE.iterdir())  # the route serves a flat folder


def test_only_the_files_a_task_loads_are_vendored() -> None:
    needed = {f for files in assets.TASK_FILES.values() for f in files}
    vendored = set(_files())
    assert vendored <= needed
    assert needed - vendored == {assets.POSE_MODEL, assets.OBJECT_MODEL}  # refused here (D14)
    for name in vendored:
        assert not name.endswith((".map", ".cjs", ".d.ts")), name
        assert "module_internal" not in name and "nosimd" not in name, name
    total = sum(int(str(e["bytes"])) for e in _files().values())
    assert total < BUDGET_BYTES, total / MB


def test_each_file_names_its_source_and_a_licence_beside_the_release() -> None:
    for name, entry in _files().items():
        licence = VISION / str(entry["licence"])
        assert licence.is_file(), (name, licence.name)
        assert licence_from_text(licence.read_text(encoding="utf-8")) in ("Apache-2.0", "MIT")
        assert str(entry["source"]).startswith(("npm:", "https://raw.githubusercontent.com/"))


def test_the_licences_are_apache_or_mit_and_nothing_is_copyleft() -> None:
    texts = {p.name: p.read_text(encoding="utf-8") for p in VISION.glob("LICENSE-*.txt")}
    assert {"LICENSE-zxing-wasm.txt", "LICENSE-tesseract.js.txt"} <= set(texts)
    for name, text in texts.items():
        assert licence_from_text(text) in ("Apache-2.0", "MIT"), name
    known = {k.rsplit("/", 1)[-1] for k in VENDORED if k.startswith("vendor/vision/")}
    # the book knows every licence (I0 seam 24); zxing-cpp's is the one I1 adds (INTEGRATION-B)
    assert set(texts) - known <= {"LICENSE-zxing-cpp.txt"}
    for path in VISION.rglob("*"):
        if path.is_file() and path.suffix in (".js", ".mjs", ".txt", ".json"):
            body = path.read_text(encoding="utf-8", errors="replace")
            assert "GNU AFFERO" not in body and "ultralytics" not in body.lower(), path.name


def test_the_licence_sums_are_recorded_too() -> None:
    licences = _manifest()["licences"]
    assert isinstance(licences, dict) and licences
    for name, digest in licences.items():
        assert hashlib.sha256((VISION / name).read_bytes()).hexdigest() == digest, name


def test_without_the_models_pose_and_objects_are_not_installed() -> None:
    console.vision_files.cache_clear()
    served = console.vision_files(assets.RELEASE)
    assert set(served) == set(_files())  # every listed file matches: all are served
    got = assets.installed(served)
    assert got == {"text": True, "code": True, "objects": False, "pose": False, "quality": True}
    assert assets.why("pose", served) == assets.NOT_INSTALLED == "not installed"
    assert assets.why("text", served) == ""


async def test_the_route_serves_every_file_and_never_the_manifest(client: AsyncClient) -> None:
    console.vision_files.cache_clear()
    base = f"/static/vendor/vision/{assets.RELEASE}"
    for name, entry in _files().items():
        r = await client.get(f"{base}/{name}")
        assert r.status_code == 200, name
        assert hashlib.sha256(r.content).hexdigest() == entry["sha256"], name
        assert r.headers["content-type"].split(";")[0] == entry["type"], name
        if entry["type"] == "application/javascript":
            assert r.headers["content-security-policy"] == console.CONSOLE_CSP, name
    assert (await client.get(f"{base}/MANIFEST.json")).status_code == 404
    assert (await client.get(f"{base}/{assets.POSE_MODEL}")).status_code == 404


def test_a_changed_byte_is_never_served(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    copy = tmp_path / assets.RELEASE
    shutil.copytree(RELEASE, copy)
    target = copy / "zxing-reader.iife.js"
    target.write_bytes(target.read_bytes() + b" ")
    monkeypatch.setattr(console, "_VISION", tmp_path)
    console.vision_files.cache_clear()
    try:
        served = console.vision_files(assets.RELEASE)
        assert "zxing-reader.iife.js" not in served and "zxing_reader.wasm" in served
        assert assets.installed(served)["code"] is False
    finally:
        console.vision_files.cache_clear()


def test_the_script_check_passes_here_and_fails_on_a_changed_byte(tmp_path: Path) -> None:
    va = _script()
    assert va.check(VISION, assets.RELEASE) == []
    copy = tmp_path / "vision"
    shutil.copytree(VISION, copy)
    wasm = copy / assets.RELEASE / "zxing_reader.wasm"
    data = wasm.read_bytes()
    wasm.write_bytes(data[:-1] + bytes([data[-1] ^ 0xFF]))  # one byte flipped
    problems = va.check(copy, assets.RELEASE)
    assert problems and "zxing_reader.wasm" in problems[0]
    (copy / "LICENSE-zxing-wasm.txt").write_text("changed", encoding="utf-8")
    assert any("LICENSE-zxing-wasm.txt" in p for p in va.check(copy, assets.RELEASE))


def test_every_source_is_pinned() -> None:
    va = _script()
    served = set(_files())
    for src in va.SOURCES:
        if src.kind == "npm":
            assert src.integrity.startswith("sha512-") and src.version[0].isdigit(), src.package
            assert set(src.members.values()) <= served | va.LICENCE_NAMES, src.package
        elif src.kind == "url":
            assert src.url.startswith("https://raw.githubusercontent.com/"), src.url
            assert "/main/" not in src.url and "/master/" not in src.url, src.url
            assert len(src.sha256) == 64, src.url
        else:
            assert src.kind == "model" and src.url.startswith("https://storage.googleapis.com/")
            assert src.name in (assets.POSE_MODEL, assets.OBJECT_MODEL)
    models = {s.name: s for s in va.SOURCES if s.kind == "model"}
    assert models[assets.POSE_MODEL].licence == "Apache-2.0"  # its model card [S24]
    assert models[assets.OBJECT_MODEL].licence == ""  # still to be read (D14)


def test_the_object_model_is_refused_until_its_licence_is_read() -> None:
    va = _script()
    with pytest.raises(SystemExit, match="licence"):
        va.plan_models(object_licence="")
    for unknown in ("whatever I read", "GPL-3.0", "see the page"):
        with pytest.raises(SystemExit, match="recognised"):
            va.plan_models(object_licence=unknown)
    picked = va.plan_models(object_licence="Apache-2.0")
    assert [m.name for m in picked] == [assets.POSE_MODEL, assets.OBJECT_MODEL]
    assert [m.name for m in va.plan_models(object_licence=None)] == [assets.POSE_MODEL]


def test_the_models_fetched_later_are_pinned_and_then_held_to_their_sum(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # CI or the owner's laptop (storage.googleapis.com is refused here): a fake download stands in
    va = _script()
    copy = tmp_path / "vision"
    shutil.copytree(VISION, copy)
    bytes_of = {assets.POSE_MODEL: b"pose model v1", assets.OBJECT_MODEL: b"object model v1"}

    def fake(url: str) -> bytes:
        return bytes_of[url.rsplit("/", 1)[-1]]

    files = dict(json.loads((copy / assets.RELEASE / "MANIFEST.json").read_text())["files"])
    files.update(va.fetch_models(copy, assets.RELEASE, "Apache-2.0", fetch=fake))
    va.write_manifest(copy, assets.RELEASE, files)
    assert va.check(copy, assets.RELEASE) == []
    doc = json.loads((copy / assets.RELEASE / "MANIFEST.json").read_text())
    assert doc["models"] == {}  # nothing left "not installed"
    pinned = doc["files"][assets.POSE_MODEL]
    assert pinned["sha256"] == hashlib.sha256(b"pose model v1").hexdigest()
    assert pinned["type"] == "application/octet-stream" and pinned["licence"] == va.MODELS_LICENCE
    words = (copy / va.MODELS_LICENCE).read_text(encoding="utf-8")
    assert f"{assets.OBJECT_MODEL}: Apache-2.0" in words
    assert licence_from_text(words) == "Apache-2.0"
    monkeypatch.setattr(console, "_VISION", copy)
    console.vision_files.cache_clear()
    try:
        assert assets.installed(console.vision_files(assets.RELEASE))["pose"] is True
    finally:
        console.vision_files.cache_clear()
    bytes_of[assets.POSE_MODEL] = b"a changed pose model"
    with pytest.raises(SystemExit, match="pinned before"):
        va.fetch_models(copy, assets.RELEASE, "Apache-2.0", fetch=fake)


def test_the_script_says_ok_with_its_size(capsys: pytest.CaptureFixture[str]) -> None:
    assert _script().main(["check"]) == 0
    assert f"{assets.RELEASE}: OK (22." in capsys.readouterr().out


# ---- review follow-ups: atomic writes, plain errors, an offline downloader, licences -----
def _tar(members: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for name, data in members.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    return buf.getvalue()


def _src(va: ModuleType, data: bytes, members: dict[str, str]) -> object:
    digest = base64.b64encode(hashlib.sha512(data).digest()).decode()
    return va.Source(
        "npm", package="pkg", version="1.0.0", integrity="sha512-" + digest, members=members
    )


def test_a_missing_folder_is_answered_plainly(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    va = _script()
    assert va.main(["check", "--folder", str(tmp_path / "nowhere")]) == 1
    out = capsys.readouterr().out
    assert "MANIFEST.json is missing" in out and "PROBLEMS" in out and "Traceback" not in out


def test_a_tarball_that_lost_a_member_or_is_not_a_tarball_gives_a_plain_message() -> None:
    va = _script()
    good = _tar({"package/a.js": b"1"})
    with pytest.raises(SystemExit, match=r"pkg.*package/b\.js"):
        va.npm_files(_src(va, good, {"package/b.js": "b.js"}), good)
    junk = b"this is not a gzip tarball"
    with pytest.raises(SystemExit, match="pkg.*could not be read"):
        va.npm_files(_src(va, junk, {"package/a.js": "a.js"}), junk)
    assert va.npm_files(_src(va, good, {"package/a.js": "a.js"}), good) == {"a.js": b"1"}


def test_a_download_stops_at_its_total_deadline_and_its_size() -> None:
    va = _script()

    class Slow(io.BytesIO):
        ticks = 0

    def opener_for(payload: bytes) -> object:
        def opener(url: str, timeout: float) -> io.BytesIO:  # noqa: ARG001
            return Slow(payload)

        return opener

    clock = iter(range(0, 10_000, 40))  # each read looks 40 s later
    with pytest.raises(SystemExit, match="too long"):
        va.download(
            "https://example.com/x",
            opener=opener_for(b"x" * 300_000),
            monotonic=lambda: next(clock),
        )
    with pytest.raises(SystemExit, match="larger than"):
        va.download("https://example.com/x", opener=opener_for(b"x" * 200), limit=100)
    assert va.download("https://example.com/x", opener=opener_for(b"ok")) == b"ok"


def test_a_failed_fetch_leaves_the_release_exactly_as_it_was(tmp_path: Path) -> None:
    va = _script()
    copy = tmp_path / "vision"
    shutil.copytree(VISION, copy)
    before = {p.name: p.read_bytes() for p in (copy / assets.RELEASE).iterdir()}
    served = {"n": 0}

    def flaky(url: str) -> bytes:
        served["n"] += 1
        if served["n"] > 3:
            raise SystemExit("could not fetch " + url)
        return b"not the pinned bytes"

    with pytest.raises(SystemExit):
        va.fetch_libraries(copy, assets.RELEASE, fetch=flaky)
    assert {p.name: p.read_bytes() for p in (copy / assets.RELEASE).iterdir()} == before
    assert not list(copy.rglob("*.tmp*"))


def test_files_are_written_through_a_temporary_name_then_replaced(tmp_path: Path) -> None:
    va = _script()
    target = tmp_path / "f.bin"
    target.write_bytes(b"old")
    va._write_atomic(target, b"new")
    assert target.read_bytes() == b"new" and [p.name for p in tmp_path.iterdir()] == ["f.bin"]


def test_a_later_models_fetch_keeps_the_object_models_licence_line(tmp_path: Path) -> None:
    va = _script()
    copy = tmp_path / "vision"
    shutil.copytree(VISION, copy)
    data = {assets.POSE_MODEL: b"pose", assets.OBJECT_MODEL: b"object"}

    def fake(url: str) -> bytes:
        return data[url.rsplit("/", 1)[-1]]

    files = dict(json.loads((copy / assets.RELEASE / "MANIFEST.json").read_text())["files"])
    files.update(va.fetch_models(copy, assets.RELEASE, "Apache-2.0", fetch=fake))
    va.write_manifest(copy, assets.RELEASE, files)
    again = va.fetch_models(copy, assets.RELEASE, None, fetch=fake)  # pose only, no licence word
    words = (copy / va.MODELS_LICENCE).read_text(encoding="utf-8")
    assert f"{assets.OBJECT_MODEL}: Apache-2.0" in words and f"{assets.POSE_MODEL}:" in words
    assert assets.POSE_MODEL in again and assets.OBJECT_MODEL not in again


def test_models_pinned_on_first_fetch_carry_a_note_to_check_the_vendors_hashes(
    tmp_path: Path,
) -> None:
    va = _script()
    copy = tmp_path / "vision"
    shutil.copytree(VISION, copy)
    va.fetch_models(copy, assets.RELEASE, None, fetch=lambda url: b"pose")
    words = (copy / va.MODELS_LICENCE).read_text(encoding="utf-8")
    assert "first fetch" in words and "published" in words and "hash" in words
