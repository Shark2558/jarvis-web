# src/jarvis/buildbook/gen/snapshot.py
"""R6 D5: the source snapshot sealed with each release (`source.zip`).

Git-tracked files only. Left out, but listed in the zip's THIRD_PARTY.json with their bytes,
SHA-256 and licence: `static/vendor/**` and `static/wakeword/**` (vendored), binaries
(`*.onnx|wasm|wav|woff2|png|jpg|pdf|zip`), files over 1 MB and the home kit's skip rules. The
zip is built as home/kit.py builds the kit: names sorted and NFC under `JARVIS-source-<id>/`, every
entry at `model.ZIP_STAMP`, mode 0644, Unix — the same commit gives the same bytes (per zlib).

Before zipping, every kept file is scanned for secret shapes (`scrub.SECRET_SHAPES`: private-key
and PGP key blocks, `AIza…`, `GOCSPX-…`, `sk-ant-…`, `sk-…`, `sk-or-v1-…`, `gsk_…`, `tvly-…`,
`ghp_`/`github_pat_`, `AKIA…`, Telegram bot tokens). A hit refuses the snapshot unless its SHA-256
is listed FOR THAT FILE in gen/fake_secrets.txt (the known fakes in tests and evals; a private key
is hashed as its whole block, so a listed fake covers that one key and nothing else). Over
`SNAPSHOT_CAP_BYTES` (15 MB) is refused. Errors name paths and kinds, never a secret.
"""

from __future__ import annotations

import hashlib
import io
import json
import re
import unicodedata
import zipfile
from dataclasses import dataclass
from importlib.resources import files
from importlib.resources.abc import Traversable
from pathlib import Path

from jarvis.buildbook.gen.libs import licence_from_text
from jarvis.buildbook.gen.repo import GenError, Repo
from jarvis.buildbook.gen.scrub import SECRET_SHAPES
from jarvis.buildbook.model import MIB, SNAPSHOT_CAP_BYTES, ZIP_STAMP

# package data (pyproject.toml), read through importlib.resources; a missing file stays an error
FAKES_FILE: Traversable | Path = files("jarvis.buildbook.gen") / "fake_secrets.txt"
THIRD_PARTY = "THIRD_PARTY.json"
LARGE_BYTES = MIB  # a file over 1 MB is left out (listed)
OWN = "JARVIS's own"
VENDORED_DIRS = ("src/jarvis/api/static/vendor/", "src/jarvis/api/static/wakeword/")
BINARY_SUFFIXES: tuple[str, ...] = (
    *(".onnx", ".wasm", ".wav", ".woff2", ".png", ".jpg", ".pdf", ".zip"),
    *(".jar", ".ttf", ".task", ".tflite", ".gz", ".webp"),  # R7: Android and vision files
)
ANDROID_BUILD = re.compile(r"^android/(?:.+/)?build/")  # R7: an Android build output is never read
# the home kit's skip rules (home/kit.py), copied so the generator imports nothing from the app;
# tests/test_book_gen_snapshot.py keeps them equal
KIT_SKIP_NAMES = frozenset(
    {"bridge.env", "frigate.env", "passwd", "secret.json", ".env", "state.json"}
)
KIT_SKIP_PARTS = frozenset({"bridge-data", "__pycache__", ".git", "mosquitto-data"})
KIT_SKIP_SUFFIXES = (".pem", ".key", ".pyc", ".tmp", ".log")
_LICENCE_FILE = re.compile(r"^(?:LICENSE|OFL)(?:-(.+))?\.txt$")


class SecretFound(GenError):
    """A secret-shaped string not listed as a known fake (paths and kinds only)."""


class SnapshotTooLarge(GenError):
    """The zip is over its cap."""


@dataclass(frozen=True)
class Snapshot:
    data: bytes
    sha256: str
    skipped: int  # files left out (listed in THIRD_PARTY.json)


Fakes = frozenset[tuple[str, str]]  # (SHA-256 of the matched text, the tracked file it is in)


def load_fakes(path: Traversable | Path | None = None) -> Fakes:
    """The known fakes as (sha256, path): a fake is accepted only in the file it is listed for."""
    out = set()
    for line in (path or FAKES_FILE).read_text(encoding="utf-8").splitlines():
        words = line.split("#", 1)[0].split()
        if not words:
            continue
        if len(words) != 2 or not re.fullmatch(r"[0-9a-f]{64}", words[0]):
            raise GenError("gen/fake_secrets.txt: each line is a SHA-256 and a path")
        out.add((words[0], words[1]))
    return frozenset(out)


def left_out(repo: Repo, rel: str) -> str | None:
    """Why a tracked file is not in the zip (None: it is)."""
    name, parts = rel.rsplit("/", 1)[-1], rel.split("/")
    if rel.startswith(VENDORED_DIRS):
        return "vendored"
    if ANDROID_BUILD.match(rel):
        return "build output"
    if any(p in KIT_SKIP_PARTS for p in parts) or name in KIT_SKIP_NAMES:
        return "home kit skip rule"
    if name.endswith(KIT_SKIP_SUFFIXES):
        return "home kit skip rule"
    if name.lower().endswith(BINARY_SUFFIXES):
        return "binary"
    if repo.size(rel) > LARGE_BYTES:
        return "over 1 MB"
    return None


def _licence(repo: Repo, rel: str) -> str:
    """The licence of the licence file beside a left-out file (matched by name), else our own."""
    folder, name = rel.rsplit("/", 1) if "/" in rel else ("", rel)
    prefix = f"{folder}/" if folder else ""
    beside = [f for f in repo.under(prefix) if "/" not in f[len(prefix) :]]
    found = {f: _LICENCE_FILE.match(f[len(prefix) :]) for f in beside}
    licences = {f: m for f, m in found.items() if m}
    pick = rel if rel in licences else None
    pick = pick or next(
        (f for f, m in licences.items() if m.group(1) and name.startswith(m.group(1))), None
    )
    pick = pick or next((f for f, m in licences.items() if not m.group(1)), None)
    pick = pick or (next(iter(licences)) if len(licences) == 1 else None)
    return licence_from_text(repo.text(pick) or "") if pick else OWN


def secret_hits(repo: Repo, files: tuple[str, ...], fakes: Fakes) -> list[tuple[str, str]]:
    """(path, kind) of every secret-shaped string not listed as a fake for that same file."""
    hits = set()
    for rel in files:
        text = repo.data(rel).decode("utf-8", errors="replace")
        for kind, pattern in SECRET_SHAPES:
            for m in pattern.finditer(text):
                if (hashlib.sha256(m.group(0).encode("utf-8")).hexdigest(), rel) not in fakes:
                    hits.add((rel, kind))
    return sorted(hits)


def _third_party(repo: Repo, rows: list[tuple[str, str]]) -> bytes:
    files = [
        {
            "path": rel,
            "bytes": repo.size(rel),
            "sha256": hashlib.sha256(repo.data(rel)).hexdigest(),
            "licence": _licence(repo, rel),
            "why": why,
        }
        for rel, why in rows
    ]
    doc = {"v": 1, "release": repo.id, "count": len(files), "files": files}
    return (json.dumps(doc, sort_keys=True, ensure_ascii=False, indent=1) + "\n").encode("utf-8")


def _zip(root: str, entries: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for name in sorted(entries):
            info = zipfile.ZipInfo(f"{root}/{name}", date_time=ZIP_STAMP)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.create_system = 3  # Unix, whatever the build machine
            info.external_attr = 0o644 << 16
            zf.writestr(info, entries[name])
    return buf.getvalue()


def build(repo: Repo, fakes: Fakes, *, cap: int = SNAPSHOT_CAP_BYTES) -> Snapshot:
    kept, skipped = [], []
    for rel in repo.files:
        why = left_out(repo, rel)
        (skipped.append((rel, why)) if why else kept.append(rel))
    hits = secret_hits(repo, tuple(kept), fakes)
    if hits:
        shown = "; ".join(f"{p} ({k})" for p, k in hits[:10])
        raise SecretFound(
            f"the code snapshot holds {len(hits)} secret-shaped string(s) not listed as fakes: "
            f"{shown}. Remove them, or list each fake's SHA-256 and path in "
            "buildbook/gen/fake_secrets.txt"
        )
    entries = {unicodedata.normalize("NFC", rel): repo.data(rel) for rel in kept}
    if len(entries) != len(kept):
        raise GenError("two tracked files have the same name once normalised (NFC)")
    entries[THIRD_PARTY] = _third_party(repo, skipped)
    data = _zip(f"JARVIS-source-{repo.id}", entries)
    if len(data) > cap:
        raise SnapshotTooLarge(
            f"the code snapshot is {len(data) / MIB:.1f} MB, over its {cap / MIB:.1f} MB cap"
        )
    return Snapshot(data=data, sha256=hashlib.sha256(data).hexdigest(), skipped=len(skipped))


__all__ = [
    "FAKES_FILE",
    "Fakes",
    "ANDROID_BUILD",
    "KIT_SKIP_NAMES",
    "KIT_SKIP_PARTS",
    "KIT_SKIP_SUFFIXES",
    "LARGE_BYTES",
    "OWN",
    "SecretFound",
    "Snapshot",
    "SnapshotTooLarge",
    "build",
    "left_out",
    "load_fakes",
    "secret_hits",
]
