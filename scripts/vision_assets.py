#!/usr/bin/env python3
# scripts/vision_assets.py
"""R7 D14: fetch, verify and pin the vision tools JARVIS serves itself.

    python scripts/vision_assets.py check     every file matches MANIFEST.json (exit 1 if not)
    python scripts/vision_assets.py fetch     the libraries and the English data, from pinned
                                              sources, into vendor/vision/<release>/
    python scripts/vision_assets.py fetch --models [--object-licence Apache-2.0]
                                              also MediaPipe's model files (Google storage: run
                                              on CI or the owner's laptop)

Every source is pinned before a byte is kept: an npm tarball by its registry `sha512` integrity, a
GitHub file by a tag or commit address and its SHA-256. A model file has no recorded sum until its
first fetch; that fetch pins it in MANIFEST.json (commit the result), and every later fetch must
match it. The object model's licence must be read by a person first (its page links no model
card): without `--object-licence` (one of the recognised permissive names) only the pose model
is fetched; a model pinned on first fetch is trusted on first use, so check its SHA-256 against the
vendor's published hash before committing. A run downloads and verifies everything in memory,
writes each file atomically (temporary name, `os.replace`) and the manifest last. Only the files
a task loads are
kept (no source maps, no CommonJS or module-worker copies). Nothing here runs a downloaded file:
tarball members are read by name, never extracted. Standard library only.

MANIFEST.json (read by the route in `api/console.py`, which uses `files` only):

    {"release", "files": {name: {sha256, bytes, type, source, licence}},
     "licences": {LICENSE-*.txt beside the release folder: sha256},
     "models": {name: {url, licence, state: "not installed"}}}
"""

from __future__ import annotations

import argparse
import base64
import contextlib
import hashlib
import io
import json
import os
import re
import sys
import tarfile
import tempfile
import time
import urllib.error
import urllib.request
import zlib
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from jarvis.vision.assets import FOLDER, OBJECT_MODEL, POSE_MODEL, RELEASE  # noqa: E402

REGISTRY = "https://registry.npmjs.org"
RAW = "https://raw.githubusercontent.com"
MAX_DOWNLOAD = 64 * 1024 * 1024
TIMEOUT_S = 30  # one socket wait
DEADLINE_S = 180  # the whole of one download (a slow trickle cannot run past it)
CHUNK = 64 * 1024
# the licences a person may name for the object model (permissive ones only; nothing copyleft)
RECOGNISED_LICENCES = frozenset({"Apache-2.0", "MIT", "BSD-2-Clause", "BSD-3-Clause"})
PIN_NOTE = (
    "Pinned on first fetch (the sums in MANIFEST.json come from whatever Google's storage\n"
    "returned): before committing, check each model file's SHA-256 against the hash the vendor\n"
    "published for it, and run `python scripts/vision_assets.py check`.\n"
)
Fetch = Callable[[str], bytes]
JS, WASM, BYTES = "application/javascript", "application/wasm", "application/octet-stream"
MODELS_LICENCE = "LICENSE-mediapipe-models.txt"
MEDIAPIPE_LICENCE = "LICENSE-mediapipe-tasks-vision.txt"


@dataclass(frozen=True)
class Source:
    kind: str  # npm | url | model
    package: str = ""
    version: str = ""
    integrity: str = ""  # npm: the registry's dist.integrity (sha512, base64)
    members: Mapping[str, str] = field(default_factory=dict)  # tar member -> kept name
    licence_of: Mapping[str, str] = field(default_factory=dict)  # kept name -> licence file
    url: str = ""
    sha256: str = ""
    name: str = ""
    licence: str = ""  # model: the licence a person read ("" = not read yet)


SOURCES: tuple[Source, ...] = (
    Source(
        "npm",
        package="@mediapipe/tasks-vision",
        version="1.2.3",
        integrity="sha512-sxJyfhbN+EamexhaaCmUlw7v8vWWMum7VDsORe6d4c8Dk/xlI4qiIgoSw9cE9hpvYhVRRVLIA8y605FbqWkNeQ==",
        members={
            "package/vision_bundle.mjs": "vision_bundle.mjs",
            "package/wasm/vision_wasm_internal.js": "vision_wasm_internal.js",
            "package/wasm/vision_wasm_internal.wasm": "vision_wasm_internal.wasm",
        },
        licence_of={
            "vision_bundle.mjs": MEDIAPIPE_LICENCE,
            "vision_wasm_internal.js": MEDIAPIPE_LICENCE,
            "vision_wasm_internal.wasm": MEDIAPIPE_LICENCE,
        },
    ),
    Source(
        "npm",
        package="tesseract.js",
        version="7.0.0",
        integrity="sha512-exPBkd+z+wM1BuMkx/Bjv43OeLBxhL5kKWsz/9JY+DXcXdiBjiAch0V49QR3oAJqCaL5qURE0vx9Eo+G5YE7mA==",
        members={
            "package/dist/tesseract.esm.min.js": "tesseract.esm.min.js",
            "package/dist/worker.min.js": "tesseract-worker.min.js",
            "package/LICENSE.md": "LICENSE-tesseract.js.txt",
        },
        licence_of={
            "tesseract.esm.min.js": "LICENSE-tesseract.js.txt",
            "tesseract-worker.min.js": "LICENSE-tesseract.js.txt",
        },
    ),
    Source(
        "npm",
        package="tesseract.js-core",
        version="6.1.2",
        integrity="sha512-pv4GjmramjdObhDyR1q85Td8X60Puu/lGQn7Kw2id05LLgHhAcWgnz6xSdMCSxBMWjQDmMyDXPTC2aqADdpiow==",
        members={
            "package/tesseract-core-simd-lstm.js": "tesseract-core-simd-lstm.js",
            "package/tesseract-core-simd-lstm.wasm": "tesseract-core-simd-lstm.wasm",
            "package/LICENSE": "LICENSE-tesseract.js-core.txt",
        },
        licence_of={
            "tesseract-core-simd-lstm.js": "LICENSE-tesseract.js-core.txt",
            "tesseract-core-simd-lstm.wasm": "LICENSE-tesseract.js-core.txt",
        },
    ),
    Source(
        "npm",
        package="zxing-wasm",
        version="3.1.6",
        integrity="sha512-mU7UNuvl+hOT+nlSOQTMHZ2tM8lRMsbjDIp5IO/+HmBl/FOq77q0OSZPJ3cm42A9c1MKU6Uve67FiGdkhsrT9g==",
        members={
            "package/dist/iife/reader/index.js": "zxing-reader.iife.js",
            "package/dist/reader/zxing_reader.wasm": "zxing_reader.wasm",
            "package/LICENSE": "LICENSE-zxing-wasm.txt",
        },
        licence_of={
            "zxing-reader.iife.js": "LICENSE-zxing-wasm.txt",
            "zxing_reader.wasm": "LICENSE-zxing-cpp.txt",  # the reader is zxing-cpp, Apache-2.0
        },
    ),
    Source(
        "url",
        url=f"{RAW}/tesseract-ocr/tessdata_fast/4.1.0/eng.traineddata",
        sha256="7d4322bd2a7749724879683fc3912cb542f19906c83bcc1a52132556427170b2",
        name="eng.traineddata",
        licence="LICENSE-tessdata-eng.txt",
    ),
    Source(
        "url",
        url=f"{RAW}/tesseract-ocr/tessdata_fast/4.1.0/LICENSE",
        sha256="cfc7749b96f63bd31c3c42b5c471bf756814053e847c10f3eb003417bc523d30",
        name="LICENSE-tessdata-eng.txt",
    ),
    Source(
        "url",
        url=f"{RAW}/google-ai-edge/mediapipe/v1.2.3/LICENSE",
        sha256="8707eef0533987efc5b155d64761eeb6e20793f50b9bd1a68dad1cf4719d0ed8",
        name=MEDIAPIPE_LICENCE,
    ),
    Source(  # the commit zxing-wasm 3.1.6 builds (its ZXING_CPP_COMMIT)
        "url",
        url=f"{RAW}/zxing-cpp/zxing-cpp/2c3dcfeffa7878950a58c1703c86774a428b0c91/LICENSE",
        sha256="c6596eb7be8581c18be736c846fb9173b69eccf6ef94c5135893ec56bd92ba08",
        name="LICENSE-zxing-cpp.txt",
    ),
    Source(
        "model",
        url="https://storage.googleapis.com/mediapipe-models/pose_landmarker/"
        "pose_landmarker_lite/float16/1/pose_landmarker_lite.task",
        name=POSE_MODEL,
        licence="Apache-2.0",  # the Pose Landmarker model card [S24]
    ),
    Source(
        "model",
        url="https://storage.googleapis.com/mediapipe-models/object_detector/"
        "efficientdet_lite0/int8/1/efficientdet_lite0.tflite",
        name=OBJECT_MODEL,
        licence="",  # its page links no model card: a person reads the licence first (D14)
    ),
)
LICENCE_NAMES = frozenset(
    {
        *(n for s in SOURCES for n in s.licence_of.values()),
        *(s.licence for s in SOURCES if s.kind == "url" and s.licence),
        *(s.name for s in SOURCES if s.kind == "url" and s.name.startswith("LICENSE-")),
    }
)


def media_type(name: str) -> str:
    if name.endswith((".js", ".mjs")):
        return JS
    return WASM if name.endswith(".wasm") else BYTES


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def download(
    url: str,
    *,
    opener: Callable[..., object] = urllib.request.urlopen,
    limit: int = MAX_DOWNLOAD,
    deadline_s: float = DEADLINE_S,
    monotonic: Callable[[], float] = time.monotonic,
) -> bytes:
    """One https download, capped in size and in total time (`opener` is injectable for tests)."""
    began = monotonic()
    out = bytearray()
    try:
        with opener(url, timeout=TIMEOUT_S) as r:  # type: ignore[attr-defined]  # noqa: S310
            while chunk := r.read(CHUNK):
                out += chunk
                if len(out) > limit:
                    raise SystemExit(f"{url} is larger than {limit} bytes")
                if monotonic() - began > deadline_s:
                    raise SystemExit(f"{url} took too long to download")
    except (urllib.error.URLError, OSError) as exc:
        raise SystemExit(f"could not fetch {url}: {exc}") from None
    return bytes(out)


def _write_atomic(path: Path, data: bytes) -> None:
    """Write beside the target, flush to disk, then replace: a failure never leaves half a file."""
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=path.name + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise


def tarball_url(src: Source) -> str:
    base = src.package.rsplit("/", 1)[-1]
    return f"{REGISTRY}/{src.package}/-/{base}-{src.version}.tgz"


def npm_files(src: Source, data: bytes) -> dict[str, bytes]:
    """The kept members of a tarball whose sha512 equals the pinned integrity."""
    want = src.integrity.removeprefix("sha512-")
    got = base64.b64encode(hashlib.sha512(data).digest()).decode()
    if got != want:
        raise SystemExit(f"{src.package}@{src.version}: the tarball does not match its integrity")
    out: dict[str, bytes] = {}
    try:
        with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tar:
            for member, name in src.members.items():
                try:
                    info = tar.getmember(member)
                except KeyError:
                    raise SystemExit(f"{src.package}: {member} is not in the tarball") from None
                handle = tar.extractfile(info) if info.isfile() else None
                if handle is None:
                    raise SystemExit(f"{src.package}: {member} is not a file")
                out[name] = handle.read()
    except (tarfile.TarError, EOFError, OSError, zlib.error) as exc:
        raise SystemExit(f"{src.package}: the tarball could not be read ({exc})") from None
    return out


def plan_models(object_licence: str | None) -> list[Source]:
    """The model files to fetch: the pose model always; the object model only once a person has
    read its licence (`object_licence`: its name, one of RECOGNISED_LICENCES). Else it refuses."""
    models = [s for s in SOURCES if s.kind == "model"]
    if object_licence is None:
        return [m for m in models if m.name != OBJECT_MODEL]
    if not object_licence.strip():
        raise SystemExit("the object model's licence has not been read: pass what it says")
    if object_licence.strip() not in RECOGNISED_LICENCES:
        names = ", ".join(sorted(RECOGNISED_LICENCES))
        raise SystemExit(f"the object model's licence is not a recognised one (use one of {names})")
    return models


def _entry(name: str, data: bytes, source: str, licence: str) -> dict[str, object]:
    kind = media_type(name)
    return {
        "sha256": sha256(data),
        "bytes": len(data),
        "type": kind,
        "source": source,
        "licence": licence,
    }


def _pending_models(files: Mapping[str, object]) -> dict[str, object]:
    return {
        s.name: {"url": s.url, "licence": s.licence or "to be read", "state": "not installed"}
        for s in SOURCES
        if s.kind == "model" and s.name not in files
    }


def write_manifest(folder: Path, release: str, files: Mapping[str, object]) -> None:
    licences = {
        p.name: sha256(p.read_bytes()) for p in sorted(folder.glob("LICENSE-*.txt")) if p.is_file()
    }
    doc = {
        "release": release,
        "files": dict(sorted(files.items())),
        "licences": licences,
        "models": _pending_models(files),
    }
    text = json.dumps(doc, indent=1, sort_keys=False, ensure_ascii=True) + "\n"
    _write_atomic(folder / release / "MANIFEST.json", text.encode("utf-8"))


def _read_manifest(folder: Path, release: str) -> dict[str, object]:
    try:
        data = json.loads((folder / release / "MANIFEST.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


Staged = tuple[dict[Path, bytes], dict[str, object]]  # (every file to write, manifest entries)


def stage_libraries(folder: Path, release: str, fetch: Fetch | None = None) -> Staged:
    """Download and verify every library in memory (about 25 MB); nothing is written yet."""
    get = fetch or download
    out = folder / release
    writes: dict[Path, bytes] = {}
    files: dict[str, object] = {}
    for src in SOURCES:
        if src.kind == "npm":
            for name, data in npm_files(src, get(tarball_url(src))).items():
                if name.startswith("LICENSE-"):
                    writes[folder / name] = data
                    continue
                writes[out / name] = data
                where = f"npm:{src.package}@{src.version}/{_member_of(src, name)}"
                files[name] = _entry(name, data, where, src.licence_of[name])
        elif src.kind == "url":
            data = get(src.url)
            if sha256(data) != src.sha256:
                raise SystemExit(f"{src.url} does not match its pinned SHA-256")
            if src.name.startswith("LICENSE-"):
                writes[folder / src.name] = data
            else:
                writes[out / src.name] = data
                files[src.name] = _entry(src.name, data, src.url, src.licence)
    return writes, files


def write_staged(writes: Mapping[Path, bytes]) -> None:
    """Write every staged file, each through `_write_atomic` (the manifest comes after, last)."""
    for path, data in writes.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        _write_atomic(path, data)


def fetch_libraries(folder: Path, release: str, fetch: Fetch | None = None) -> dict[str, object]:
    """The libraries, all verified before the first file is written."""
    writes, files = stage_libraries(folder, release, fetch)
    write_staged(writes)
    return files


def _member_of(src: Source, name: str) -> str:
    return next(m for m, n in src.members.items() if n == name).removeprefix("package/")


def _model_words(folder: Path) -> dict[str, str]:
    """{model: licence word} already recorded in the models' licence file."""
    try:
        text = (folder / MODELS_LICENCE).read_text(encoding="utf-8")
    except OSError:
        return {}
    found = re.findall(r"^([A-Za-z0-9_.-]+): (\S+) \(from ", text, flags=re.M)
    return {name: word for name, word in found}


def stage_models(
    folder: Path, release: str, object_licence: str | None, fetch: Fetch | None = None
) -> Staged:
    """The model files, each checked against the sum an earlier fetch pinned (none yet: this
    fetch pins it), and their licence file (earlier words kept), all in memory."""
    get = fetch or download
    pinned = _read_manifest(folder, release).get("files")
    pinned = pinned if isinstance(pinned, dict) else {}
    writes: dict[Path, bytes] = {}
    files: dict[str, object] = {}
    picked = plan_models(object_licence)
    for src in picked:
        data = get(src.url)
        before = pinned.get(src.name)
        if isinstance(before, dict) and before.get("sha256") not in (None, sha256(data)):
            raise SystemExit(f"{src.name} does not match the sum pinned before")
        writes[folder / release / src.name] = data
        files[src.name] = _entry(src.name, data, src.url, MODELS_LICENCE)
    words = _model_words(folder)
    words.update({s.name: s.licence or str(object_licence) for s in picked})
    urls = {s.name: s.url for s in SOURCES if s.kind == "model"}
    head = "".join(f"{n}: {w} (from {urls.get(n, '')})\n" for n, w in sorted(words.items()))
    apache = (folder / MEDIAPIPE_LICENCE).read_text(encoding="utf-8")
    text = "MediaPipe model files served by JARVIS (R7 D14)\n" + head + "\n" + PIN_NOTE + "\n"
    writes[folder / MODELS_LICENCE] = (text + apache).encode("utf-8")
    return writes, files


def fetch_models(
    folder: Path, release: str, object_licence: str | None, fetch: Fetch | None = None
) -> dict[str, object]:
    """`stage_models`, then written."""
    writes, files = stage_models(folder, release, object_licence, fetch)
    write_staged(writes)
    return files


def check(folder: Path, release: str) -> list[str]:
    """Problems, one line each (empty: every listed file and licence matches its sum)."""
    doc = _read_manifest(folder, release)
    files, licences = doc.get("files"), doc.get("licences")
    if not isinstance(files, dict) or not isinstance(licences, dict):
        return [f"{release}/MANIFEST.json is missing or unreadable"]
    problems: list[str] = []
    for name, entry in sorted(files.items()):
        path = folder / release / str(name)
        if not isinstance(entry, dict) or not path.is_file():
            problems.append(f"{name}: listed but missing")
            continue
        data = path.read_bytes()
        if sha256(data) != entry.get("sha256") or len(data) != entry.get("bytes"):
            problems.append(f"{name}: does not match its recorded sum")
        if not (folder / str(entry.get("licence", ""))).is_file():
            problems.append(f"{name}: its licence file is missing")
    for name, digest in sorted(licences.items()):
        path = folder / str(name)
        if not path.is_file() or sha256(path.read_bytes()) != digest:
            problems.append(f"{name}: does not match its recorded sum")
    shelf = folder / release
    stray = {p.name for p in shelf.iterdir() if p.is_file()} - set(files) - {"MANIFEST.json"}
    problems.extend(f"{name}: in the folder but not in the manifest" for name in sorted(stray))
    return problems


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Fetch, verify and pin the vision files (R7 D14).")
    ap.add_argument("command", choices=("check", "fetch"), nargs="?", default="check")
    ap.add_argument("--models", action="store_true", help="also fetch MediaPipe's model files")
    ap.add_argument("--object-licence", default=None, help="the object model's licence, as read")
    ap.add_argument("--folder", type=Path, default=FOLDER)
    args = ap.parse_args(argv)
    if args.command == "fetch":
        # everything is downloaded and verified in memory first; files are written after, the
        # manifest last, so a failed run leaves the folder and its manifest as they were
        writes, files = stage_libraries(args.folder, RELEASE)
        old = _read_manifest(args.folder, RELEASE).get("files")
        for name, entry in (old if isinstance(old, dict) else {}).items():
            if name in (POSE_MODEL, OBJECT_MODEL) and (args.folder / RELEASE / name).is_file():
                files[name] = entry  # pinned before; `check` below proves it still matches
        if args.models:
            more_writes, more_files = stage_models(args.folder, RELEASE, args.object_licence)
            writes.update(more_writes)
            files.update(more_files)
            print(PIN_NOTE, end="")
        write_staged(writes)
        write_manifest(args.folder, RELEASE, files)
    problems = check(args.folder, RELEASE)
    for line in problems:
        print(line)
    shelf = args.folder / RELEASE
    total = sum(p.stat().st_size for p in shelf.iterdir() if p.is_file()) if shelf.is_dir() else 0
    print(f"{RELEASE}: {'OK' if not problems else 'PROBLEMS'} ({total / 1024 / 1024:.1f} MB)")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
